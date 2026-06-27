
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import get_db
from models import ComponentModel, ComponentHistoryModel
from schemas import ComponentResponse, ComponentHistoryResponse, ComponentUpdate
from cache import get_from_cache, set_cache, redis_client
from scraper import fetch_datasheet_url, parse_pdf, models as ai_models
from ratelimit import limiter

from auth import get_api_key

router = APIRouter(prefix="/components", tags=["Components"])

def save_version_backup(db: Session, component: ComponentModel):
    """Save a backup of the current version of a component to the history table. (Doesn't commit to session)"""
    try:
        history_entry = ComponentHistoryModel(
            part_number=component.part_number,
            description=component.description,
            specifications=component.specifications,
            datasheet_url=component.datasheet_url,
            source=component.source
        )
        db.add(history_entry)
        print(f"Saved backup of {component.part_number} to history table.")
    except Exception as e:
        print(f"Could not save backup of {component.part_number} to history table. (components.py | line 30): {e}")


@router.get("", response_model=list[ComponentResponse])
@limiter.limit("30/minute") # limit to 30 requests per minute
def get_components(request: Request, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    """Fetch all components in our database!"""

    components = db.execute(select(ComponentModel).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    print(f"Fetched {len(components)} components from database (page {page}, page_size {page_size})")
    print(components)
    if not components:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No components found")

    return components

# # fetching should go in this order: check cache, db, then scrape external resources
@router.get("/{part_number}", response_model=ComponentResponse)
@limiter.limit("20/minute") # limit to 20 requests per minute
def components_part_number(request: Request, part_number: str, skip_ai: bool = Query(False, description="Skip AI parsing of datasheet PDF. (Faster response but won't get detailed specifications, only applies to new components not in our database)"), db: Session = Depends(get_db)):
    """Fetch the specifications for a specific component!"""    

    upn = part_number.upper() # uppercase part number
    key = f"component:{upn}"

    # Check cache first
    cached = get_from_cache(key)
    if cached:
        return cached

    # Checking database
    component_db = db.get(ComponentModel, upn)
    if component_db:
        print(f"Found {part_number} in database!")
        result = ComponentResponse.model_validate(component_db, from_attributes=True)

        set_cache(key, result) # if found in db but not cache, add it to cache

        return result

    print(f"{part_number} not found in database.")


    ## Scraping external resources
    scraped = fetch_datasheet_url(part_number, skip_ai=skip_ai)
    if not scraped: # Couldn't find part at all
        raise HTTPException(status_code=404, detail=f"Component {upn} not found in external resources")

    try:
        newComponent = ComponentModel(**scraped.model_dump()) # unpacked dumped data into a new pydantic component model
        db.add(newComponent)
        save_version_backup(db, newComponent)
        db.commit()
        db.refresh(newComponent)
    except IntegrityError as e:
        print(f"Database Integrity error while adding {part_number} to database. (components.py | line 83): {e}")
        db.rollback()
        raise HTTPException(status_code=409, detail=f"There was an integrity error while adding {part_number} to the database")

    except Exception as e:
        print(f"Could not add {part_number} to database. (components.py | line 87): {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error while adding {part_number} to the database")

    result = ComponentResponse.model_validate(newComponent, from_attributes=True)
    set_cache(key, result)

    return result

@router.get("/viewsaves/{part_number}", response_model=list[ComponentHistoryResponse])
@limiter.limit("20/minute") # limit to 20 requests per minute
def components(request: Request, part_number: str, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """View the past versions of a specific component. (AUTH REQUIRED)"""
    upn = part_number.upper() # uppercase part number

    if not upn:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Part number is required")

    query = select(ComponentHistoryModel).where(ComponentHistoryModel.part_number == upn).order_by(ComponentHistoryModel.saved_at.desc())
    history = db.execute(query).scalars().all()

    if not history:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No history found for component {upn}")
    
    return history

@router.put("/{part_number}", response_model=ComponentResponse) # post or put?
@limiter.limit("20/minute") # limit to 20 requests per minute
def components(request: Request, part_number: str, component_data: ComponentUpdate, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Manually add a component to the database. Expects part number and a table of specifications. (AUTH REQUIRED)"""
    upn = part_number.upper() # uppercase part number
    db_component = db.get(ComponentModel, upn)

    print(component_data)
    if not component_data.model_dump(exclude_unset=True): # if no data was provided in the request
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data provided to update the component")

    if not db_component:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found")
    
    updated_data = component_data.model_dump(exclude_unset=True) # only include fields that were provided in the request
    for key, value in updated_data.items():
        setattr(db_component, key, value) # update the component with the new data

    save_version_backup(db, db_component) # save a backup of the current version before updating
    db.commit()
    db.refresh(db_component)

    result = ComponentResponse.model_validate(db_component, from_attributes=True)
    set_cache(f"component:{upn}", result) # update the cache with the new data
    return result
    


@router.delete("/{part_number}", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute") # limit to 20 requests per minute
def components(request: Request, part_number: str, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Manually delete a component from the database. Expects a part number. (AUTH REQUIRED)"""
    upn = part_number.upper() # uppercase part number
    db_component = db.get(ComponentModel, upn)

    if not db_component:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found")
    
    db.delete(db_component)
    db.commit()

    redis_client.delete(f"component:{upn}") # update the cache with the new data
    return HTTPException(status_code=status.HTTP_200_OK, detail=f"Component {upn} deleted successfully")
