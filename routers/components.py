
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status

from sqlalchemy import select, cast, String
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import get_db
from models import ComponentModel, ComponentHistoryModel
from schemas import ComponentResponse, ComponentHistoryResponse, ComponentUpdate
from cache import get_from_cache, set_cache, redis_client
from scraper import fetch_datasheet_url, parse_pdf
from ratelimit import limiter
import requests


from auth import get_api_key

router = APIRouter(prefix="/components", tags=["Components"])

from main import request_ctx

def component_fetch_ratelimit():
    request = request_ctx.get()

    skip_ai = request.query_params.get("skip_ai", "").lower()
    force_fetch = request.query_params.get("force_fetch", "").lower()

    if skip_ai in ["true", "1", "yes", True]:
        return "50/minute"  # Limit to 50 requests per minute if skip_ai is true

    if force_fetch in ["true", "1", "yes", True]:
        return "2/minute"  # Limit to 2 requests per minute if force_fetch is true
    
    return "20/minute"  # Default limit to 20 requests per minute


def save_version_backup(db: Session, component: ComponentModel):
    """Save a backup of the current version of a component to the history table. (Doesn't commit to session)"""
    try:
        # Include duplicates or not?
        
        # duplicate_query = select(ComponentHistoryModel).where(
        #     ComponentHistoryModel.part_number == component.part_number and 
        #     ComponentHistoryModel.description == component.description and 
        #     ComponentHistoryModel.specifications == component.specifications and 
        #     ComponentHistoryModel.datasheet_url == component.datasheet_url and 
        #     ComponentHistoryModel.source == component.source
        # )
        # duplicate_results = db.execute(duplicate_query).scalars().all()

        # if duplicate_results:
        #     print(f"Duplicate found for {component.part_number} in history table. Not saving a new version.")
        #     return None
        
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
        print(f"Could not save backup of {component.part_number} to history table. (components.py | line 48): {e}")

@router.put("/{part_number}", response_model=ComponentResponse)
@limiter.limit("20/minute") # limit to 20 requests per minute
def update_component(request: Request, part_number: str, component_data: ComponentUpdate | None = None, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Manually add a component to the database. Expects part number and a table of specifications. (AUTH REQUIRED)"""

    upn = part_number.upper() # uppercase part number
    db_component = db.get(ComponentModel, upn)

    if not db_component:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found")
    
    if not component_data or not component_data.model_dump(exclude_unset=True): 
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body cannot be empty")


    updated_data = component_data.model_dump(exclude_unset=True) # only include fields that were provided in the request
    for key, value in updated_data.items():
        if key in ["part_number", "created_at", "updated_at"]: # don't allow updating these fields (pydantic will stop the request anyways, but this is just in case)
            continue

        setattr(db_component, key, value) # update the component with the new data

    save_version_backup(db, db_component) # save a backup of the current version before updating
    db.commit()
    db.refresh(db_component)

    result = ComponentResponse.model_validate(db_component, from_attributes=True)
    set_cache(f"component:{upn}", result) # update the cache with the new data
    return result

@router.delete("/{part_number}", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute") # limit to 20 requests per minute
def delete_component(request: Request, part_number: str, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Manually delete a component from the database. Expects a part number. (AUTH REQUIRED)"""
    upn = part_number.upper() # uppercase part number
    db_component = db.get(ComponentModel, upn)

    if not db_component:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found")
    
    db.delete(db_component)
    db.commit()

    redis_client.delete(f"component:{upn}")
    raise HTTPException(status_code=status.HTTP_200_OK, detail=f"Component {upn} deleted successfully")


@router.post("/fillmissingspecs", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute") # limit to 20 requests per minute
def fill_missing_specs(request: Request, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Scans database for all components with empty specifications and re runs the AI parser. (AUTH REQUIRED)"""
    spec_query = select(ComponentModel).where(
        (cast(ComponentModel.specifications, String) == "{}") | (ComponentModel.specifications.is_(None))
    )
    components = db.execute(spec_query).scalars().all()

    if not components:
        raise HTTPException(status_code=status.HTTP_200_OK, detail="All components already have filled specifications. No components were updated.")

    update_count = 0
    for component in components:
        try:
            print(f"Filling missing specifications for {component.part_number}...")
            pdf_bytes = requests.get(component.datasheet_url, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=10).content

            if not pdf_bytes:
                print(f"Could not fetch PDF for {component.part_number} from {component.datasheet_url}. Skipping...")
                continue

            parsed_specs = parse_pdf(pdf_bytes, component.part_number.upper())

            if not parsed_specs:
                print(f"Failed to parse PDF for {component.part_number}. Skipping...")
                continue

            save_version_backup(db, component) # save a backup of the current version before updating
            component.specifications = parsed_specs.get("specifications")
            component.description = parsed_specs.get("description")
            db.commit()
            set_cache(f"component:{component.part_number.upper()}", ComponentResponse.model_validate(component, from_attributes=True)) # update the cache with the new data
            update_count += 1

        except Exception as e:
            print(f"Error while filling missing specifications for {component.part_number} (components.py | line 133): {e}")
            
            db.rollback() # rollback the session to prevent any issues
            break

    if update_count == 0 and len(components) > 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fill missing specifications for any components.")

    raise HTTPException(status_code=status.HTTP_200_OK, detail=f"Filled missing specifications for {update_count}/{len(components)} components.")

@router.get("/viewsaves/{part_number}", response_model=list[ComponentHistoryResponse]) 
@limiter.limit("20/minute") # limit to 20 requests per minute
def view_saves(request: Request, part_number: str, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """View the past versions of a specific component. (AUTH REQUIRED)"""
    upn = part_number.upper() # uppercase part number

    if not upn:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Part number is required")

    query = select(ComponentHistoryModel).where(ComponentHistoryModel.part_number == upn).order_by(ComponentHistoryModel.saved_at.desc())
    history = db.execute(query).scalars().all()

    if not history:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No history found for component {upn}")

    return history

@router.get("/viewsaves/", response_model=dict[str, list[ComponentHistoryResponse]]) 
@limiter.limit("20/minute") # limit to 20 requests per minute
def view_saves(request: Request, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """View the past versions of every component that was once in the database. (AUTH REQUIRED)"""
    query = select(ComponentHistoryModel).order_by(ComponentHistoryModel.saved_at.desc())
    history = db.execute(query).scalars().all()

    if not history:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No history found for any components")
    
    # sort the history by grouping by the part number and then sorting by the saved_at timestamp in descending order
    sorted_history = {}

    for entry in history:
        if entry.part_number not in sorted_history:
            sorted_history[entry.part_number] = []

        sorted_history[entry.part_number].append(entry)


    return sorted_history

@router.post("/updatespecs/{part_number}", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute") # limit to 20 requests per minute
def update_specs(request: Request, part_number: str, db: Session = Depends(get_db)):
    """Re runs the AI parser for a specific component and force updates its specifications."""
    upn = part_number.upper() # uppercase part number
    component = db.get(ComponentModel, upn)

    if not component:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found in database")

    print(f"Updating specifications for {component.part_number}...")
    pdf_bytes = requests.get(component.datasheet_url, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=10)

    # if no pdf found
    if not pdf_bytes.content or pdf_bytes.headers.get('Content-Type') != 'application/pdf':
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Could not fetch PDF for {component.part_number}. Datasheet URL: {component.datasheet_url}")

    parsed_specs = parse_pdf(pdf_bytes, component.part_number.upper())

    if not parsed_specs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Failed to parse PDF for {component.part_number}")
    
    try:
        save_version_backup(db, component) # save a backup of the current version before updating
        component.specifications = parsed_specs.get("specifications")
        component.description = parsed_specs.get("description")
        db.commit()
        set_cache(f"component:{component.part_number.upper()}", ComponentResponse.model_validate(component, from_attributes=True)) # update the cache with the new data

    except Exception as e:
        print(f"Error while updating specifications for {component.part_number} (components.py | line 212): {e}")
        
        db.rollback() # rollback the session to prevent issues
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update specifications for {component.part_number}")

    return component

@router.get("/{part_number}", response_model=ComponentResponse)
@limiter.limit(component_fetch_ratelimit) # dynamic rate limit

# if 2 people request the same part at the same time, it will scrape datasheetarchive twice. 
# implement a solution and have it immediately return the result to the second person after the first persons request is done
def fetch_component(
        request: Request, 
        part_number: str, 
        manufacturer: str | None = Query(None, description="Optionally specify the manufacturer of the component"), 
        skip_ai: bool = Query(False, description="Skip AI parsing of datasheet PDF. (Faster response but won't get detailed specifications, only applies to new components not in our database)"), 
        force_fetch: bool = Query(False, description="Force fetch the component from external sources. Useful if you want to fully refresh the component data"), 
        db: Session = Depends(get_db)
    ):
    """Fetch the specifications for a specific component!"""    

    upn = part_number.upper() # uppercase part number
    key = f"component:{upn}"

    # Check cache first
    cached = get_from_cache(key)
    if cached and not force_fetch:
        return cached

    # Checking database
    component_db = db.get(ComponentModel, upn)
    if component_db and not force_fetch:
        print(f"Found {part_number} in database!")
        result = ComponentResponse.model_validate(component_db, from_attributes=True)

        set_cache(key, result) # if found in db but not cache, add it to cache

        return result

    available_manufacturers = [
        "Texas-Instruments", 
        "Central-Semiconductor",
        "GigaDevice-Semiconductor-(Beijing)-Inc",
        "SLKOR",
        "2Pai-Semiconductor",
        "3peak-Incorporated",
        "Shanghai-Awinic-Technology",
        "Murata-Manufacturing-Co-Ltd",
        "Amphenol-Positronic",
        "Microchip-Technology-Inc",
        "Littelfuse-Inc",
        "Phoenix-Contact",
        "ROHM-Semiconductor",
        "onsemi",
        "STMicroelectronics",
        "Analog-Devices",
        "Advantech-Co-Ltd",
        "Toshiba-America-Electronic-Components",
        "Same-Sky",
        "NXP-Semiconductors",
        "Allegro-MicroSystems-LLC",
        "Renesas",
        "SG-Micro",
        "Broadcom",
        "KEMET-Corporation",
        "Vishay",
        "Apex-Microtechnology-Inc",
        "Nisshinbo-Micro-Devices",
        "YAGEO-Corporation",
        "Wima",
        "Rubycon-Corporation",
        "Infineon",
        "Honeywell",
        "HARTING-Elektronik",
        "Coilcraft",
        "3M",
        "WAGO-Innovative-Connections",
        "ECS-Inc-International",
        "Abracon-Corporation",
        "Cirrus-Logic",
        "Bourns-Inc",
        "Molex",
        "Omron",
        "EDAC-Inc",
        "Advanced-Power-Technologies",
        "KEC",
        "Kingbright",
        "SanRex",
        "Seiko-Instruments-Inc",
        "Kyocera-AVX-Components",
        "Integrated-Silicon-Solution-Inc",
        "Stellar-Technology-Inc",
        "Holtek-Semiconductor-Inc",
        "Telemechanique-Sensors",
        "HPMicro-Semiconductor-Co-Ltd",
        "XINGLIGHT",
        "Microdiode-Semiconductor",
        "Geehy-Semiconductor",
        "Shikues-Semiconductor",
        "NEC",
        "Semikron",
        "Dialight",
        "TE-Connectivity",
        "Mini--Circuits",
        "Vicor",
        "Keystone-Electronics",
        "Quanzhou-KTsense-Microelectronics-Co..Ltd",
        "RUNIC",
        "Intel",
        "MCC",
        "Fujitsu",
        "EIC-Semiconductor",
        "Altera",
        "Agilent-Technologies",
        "Advanced-Micro-Devices",
        "Wurth-Elektronik"
    ]

    if manufacturer and not any(manufacturer.lower() == item.lower() for item in available_manufacturers):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"We don't have data for that manufacturer. Available manufacturers: {', '.join(available_manufacturers)}")

    ## Scraping external resources
    scraped = fetch_datasheet_url(part_number, manufacturer=manufacturer, skip_ai=skip_ai)
    if not scraped: # Couldn't find part at all
        if manufacturer:
            raise HTTPException(status_code=404, detail=f"Component {upn} from manufacturer: '{manufacturer.lower()}' not found in external resources")
        
        raise HTTPException(status_code=404, detail=f"Component {upn} not found in external resources")

    try:
        if force_fetch and db.get(ComponentModel, upn):
            save_version_backup(db, db.get(ComponentModel, upn))
            db.delete(db.get(ComponentModel, upn)) # delete the old component if it exists so we can add the new one for force fetch

        newComponent = ComponentModel(**scraped.model_dump()) # unpacked dumped data into a new pydantic component model
        db.add(newComponent)
        save_version_backup(db, newComponent)
        db.commit()
        db.refresh(newComponent)
    except IntegrityError as e:
        print(f"Database Integrity error while adding {part_number} to database. (components.py | line 355): {e}")
        db.rollback()
        raise HTTPException(status_code=409, detail=f"There was an integrity error while adding {part_number} to the database")

    except Exception as e:
        print(f"Could not add {part_number} to database. (components.py | line 360): {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error while adding {part_number} to the database")

    result = ComponentResponse.model_validate(newComponent, from_attributes=True)
    set_cache(key, result)

    return result


@router.get("", response_model=list[ComponentResponse])
@limiter.limit("30/minute") # limit to 30 requests per minute
def get_components(request: Request, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=50), db: Session = Depends(get_db)):
    """Fetch all components in our database! Use the parameters 'page' and 'page_size' to paginate the results. (Default page size is 25, max 50)"""

    components = db.execute(select(ComponentModel).offset((page - 1) * page_size).limit(page_size)).scalars().all()

    if not components:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No components found")

    return components