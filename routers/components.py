
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status

from sqlalchemy import select, cast, String, func
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
from context import request_ctx

from loguru import logger
import time

router = APIRouter(prefix="/components", tags=["Components"])

logger.success("Components router initialized")

def component_fetch_ratelimit():
    request = request_ctx.get()
    part_number = request.path_params.get("part_number", "").lower()    

    component_already_exists = get_from_cache(f"component:{part_number.upper()}")

    using_ai = str(request.query_params.get("skip_ai", "")).lower() not in ["true", "1", "yes"]
    using_force = str(request.query_params.get("force_fetch", "")).lower() in ["true", "1", "yes"]

    if component_already_exists and not using_force: # no scraper or ai
        logger.log("RATELIMIT", f"Calculated a rate limit of 5/second for existing component: '{part_number}'")
        return "5/second"

    if using_ai: # using scraper and ai
        logger.log("RATELIMIT", f"Calculated rate limit of 5/minute for component: '{part_number}'")
        return "5/minute"

    logger.log("RATELIMIT", f"Calculated a rate limit of 50/minute for component: '{part_number}'")
    return "50/minute" # using scraper, no ai


def save_version_backup(db: Session, component: ComponentModel):
    """Save a backup of the current version of a component to the history table. (Doesn't commit to session)"""
    logger.debug(f"Saving backup of component: '{component.part_number}'")
    try:        
        latest_component = db.scalar(select(ComponentHistoryModel).where(ComponentHistoryModel.part_number == component.part_number).order_by(ComponentHistoryModel.id.desc()).limit(1)) # grab the highest id (latest version) of the component in the history table

        if (
            latest_component 
            and latest_component.description == component.description 
            and latest_component.specifications == component.specifications 
            and latest_component.datasheet_url == component.datasheet_url 
            and latest_component.source == component.source
        ):
            logger.debug(f"Duplicate found for {component.part_number} in history table. Not saving a new version.")
            return None
        
        history_entry = ComponentHistoryModel(
            part_number=component.part_number,
            description=component.description,
            specifications=component.specifications,
            datasheet_url=component.datasheet_url,
            source=component.source
        )
        db.add(history_entry)
        logger.success(f"Saved backup of {component.part_number} to history table.")
    except Exception as e:
        logger.error(f"Could not save backup of {component.part_number} to history table: {e}")

@router.put("/{part_number}", response_model=ComponentResponse)
@limiter.limit("20/minute") # limit to 20 requests per minute
def update_component(request: Request, part_number: str, component_data: ComponentUpdate | None = None, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Manually add a component to the database. Expects part number and a table of specifications. (AUTH REQUIRED)"""
    logger.info(f"PUT /components/{{part_number}} endpoint requested by IP: '{request.client.host}'")

    upn = part_number.upper() # uppercase part number
    db_component = db.get(ComponentModel, upn)

    if not db_component:
        logger.warning(f"Component {upn} not found in database for update")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found")
    
    if not component_data or not component_data.model_dump(exclude_unset=True): 
        logger.warning(f"Request body is empty")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body cannot be empty")


    updated_data = component_data.model_dump(exclude_unset=True) # only include fields that were provided in the request
    logger.debug(f"Updating component {upn} with data: {updated_data}")

    try:
        for key, value in updated_data.items():
            if key in ["part_number", "created_at", "updated_at"]: # don't allow updating these fields (pydantic will stop the request anyways, but this is just in case)
                continue

            setattr(db_component, key, value) # update the component with the new data

        save_version_backup(db, db_component) # save a backup of the current version before updating
        db.commit()
        db.refresh(db_component)

    except IntegrityError as e:
        logger.exception(f"Database Integrity error while updating component {upn}: {e}")
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database integrity error occurred while updating the component")

    except Exception as e:
        logger.exception(f"Error occurred while updating component {upn}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while updating the component")

    result = ComponentResponse.model_validate(db_component, from_attributes=True)
    set_cache(f"component:{upn}", result) # update the cache with the new data

    logger.success(f"Component {upn} updated successfully with data: {updated_data}")
    return result

@router.delete("/{part_number}", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute") # limit to 20 requests per minute
def delete_component(request: Request, part_number: str, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Manually delete a component from the database. Expects a part number. (AUTH REQUIRED)"""
    logger.info(f"DELETE /components/{{part_number}} endpoint requested by IP: '{request.client.host}'")

    upn = part_number.upper() # uppercase part number
    db_component = db.get(ComponentModel, upn)

    if not db_component:
        logger.warning(f"Component {upn} not found in database for deletion")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found")
    
    db.delete(db_component)
    db.commit()

    redis_client.delete(f"component:{upn}")

    logger.success(f"Component {upn} deleted successfully from database and cache")
    raise HTTPException(status_code=status.HTTP_200_OK, detail=f"Component {upn} deleted successfully")


@router.post("/fillmissingspecs", status_code=status.HTTP_200_OK)
@limiter.limit("1/minute") # limit to 1 request per minute, very ai intensive
def fill_missing_specs(request: Request, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Scans database for all components with empty specifications and re runs the AI parser. (AUTH REQUIRED)"""
    logger.info(f"POST /components/fillmissingspecs endpoint requested by IP: '{request.client.host}'")

    spec_query = select(ComponentModel).where(
        (cast(ComponentModel.specifications, String) == "{}") | (ComponentModel.specifications.is_(None))
    )
    components = db.execute(spec_query).scalars().all()

    if not components:
        logger.info("All components already have filled specifications, aborted job")
        raise HTTPException(status_code=status.HTTP_200_OK, detail="All components already have filled specifications. No components were updated.")

    ai_limit_reached = False
    update_count = 0
    for component in components:
        if ai_limit_reached:
            continue

        try:
            logger.info(f"Filling missing specifications for {component.part_number}...")
            pdf_bytes = requests.get(component.datasheet_url, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=10).content

            if not pdf_bytes:
                logger.error(f"Could not fetch PDF for {component.part_number} from {component.datasheet_url}. Skipping...")
                continue

            parsed_specs = parse_pdf(pdf_bytes, component.part_number.upper())

            # RATELIMIT HANDLING
            if "RATELIMIT_EXCEEDED" in parsed_specs:
                if update_count > 0:
                    ai_limit_reached = True
                    logger.warning(f"AI rate limit: '{parsed_specs.get("TYPE")}' reached after updating {update_count}/{len(components)} components. Stopping the rest of the job.")
                    continue
                if parsed_specs["TYPE"] == "MINUTE_LIMIT":
                    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"The AI exceeded it's rate limit. Please wait a minute before trying again. The component has been saved in the database without specifications")
                else:
                    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"The AI daily rate limit exceeded. Please wait until tomorrow before trying again. The component has been saved in the database without specifications")

            if not parsed_specs:
                logger.error(f"Failed to parse PDF for {component.part_number}. Skipping...")
                continue

            save_version_backup(db, component) # save a backup of the current version before updating
            component.specifications = parsed_specs.get("specifications")
            component.description = parsed_specs.get("description")
            db.commit()
            set_cache(f"component:{component.part_number.upper()}", ComponentResponse.model_validate(component, from_attributes=True)) # update the cache with the new data
            update_count += 1

        except IntegrityError as e:
            logger.exception(f"Database Integrity error while filling missing specifications for {component.part_number}: {e}")
            db.rollback() # rollback the session to prevent any issues
            break

        except Exception as e:
            logger.exception(f"Error while filling missing specifications for {component.part_number}: {e}")
            
            db.rollback() # rollback the session to prevent any issues
            break

    if update_count == 0 and len(components) > 0:
        logger.error(f"Failed to fill missing specifications for any components: {components}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fill missing specifications for any components.")

    if ai_limit_reached:
        logger.warning(f"AI limit reached before all components could be updated.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Filled missing specifications for {update_count}/{len(components)} components. AI rate limit was reached before all components could be updated, please try again later.")

    logger.success(f"Filled missing specifications for {update_count}/{len(components)} components.")
    raise HTTPException(status_code=status.HTTP_200_OK, detail=f"Filled missing specifications for {update_count}/{len(components)} components.")

@router.get("/viewsaves/{part_number}", response_model=list[ComponentHistoryResponse]) 
@limiter.limit("20/minute") # limit to 20 requests per minute
def view_saves(request: Request, part_number: str, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """View the past versions of a specific component. (AUTH REQUIRED)"""
    logger.info(f"GET /components/viewsaves/{part_number} endpoint requested by IP: '{request.client.host}'")

    upn = part_number.upper() # uppercase part number

    query = select(ComponentHistoryModel).where(ComponentHistoryModel.part_number == upn).order_by(ComponentHistoryModel.saved_at.desc())
    history = db.execute(query).scalars().all()

    if not history:
        logger.warning(f"No history found for component: {upn}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No history found for component {upn}")

    logger.debug(f"History for component {upn}: {history}")
    return history

@router.get("/viewsaves/", response_model=dict[str, list[ComponentHistoryResponse]]) 
@limiter.limit("20/minute") # limit to 20 requests per minute
def view_saves(request: Request, api_key: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """View the past versions of every component that was once in the database. (AUTH REQUIRED)"""
    logger.info(f"GET /components/viewsaves/ endpoint requested by IP: '{request.client.host}'")

    query = select(ComponentHistoryModel).order_by(ComponentHistoryModel.saved_at.desc())
    history = db.execute(query).scalars().all()

    if not history:
        logger.warning(f"No history found for any components in the database")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No history found for any components")
    
    # sort the history by grouping by the part number and then sort by saved_at timestamp in descending order
    sorted_history = {}

    for entry in history:
        if entry.part_number not in sorted_history:
            sorted_history[entry.part_number] = []

        sorted_history[entry.part_number].append(entry)

    logger.debug(f"Sorted history for all components: {sorted_history}")
    return sorted_history

@router.post("/updatespecs/{part_number}", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute") # limit to 5 requests per minute
def update_specs(request: Request, part_number: str, db: Session = Depends(get_db)):
    """Re runs the AI parser for a specific component and force updates its specifications."""
    logger.info(f"POST /components/updatespecs/{part_number} endpoint requested by IP: '{request.client.host}'")

    upn = part_number.upper() # uppercase part number
    component = db.get(ComponentModel, upn)

    if not component:
        logger.warning(f"Component {upn} not found in database")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found in database")

    logger.info(f"Updating specifications for {upn}...")
    response = requests.get(component.datasheet_url, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=10)
    pdf_bytes = response.content

    # if no pdf found
    if not pdf_bytes or response.headers.get('Content-Type') != 'application/pdf':
        logger.error(f"Could not fetch a valid PDF for {upn} from {component.datasheet_url}. Response content type: {response.headers.get('Content-Type')}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Could not fetch PDF for {upn}. Datasheet URL: {component.datasheet_url}")

    parsed_specs = parse_pdf(pdf_bytes, upn)

    if not parsed_specs:
        logger.error(f"AI Failed to parse the PDF for {upn}.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Failed to parse PDF for {upn}")
    
    # RATELIMIT HANDLING
    if "RATELIMIT_EXCEEDED" in parsed_specs:
        logger.warning(f"AI limit reached while updating specifications for {upn}. Info: {parsed_specs}")
        if parsed_specs["TYPE"] == "MINUTE_LIMIT":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"The AI exceeded it's rate limit. Please wait a minute before trying again. The component has been saved in the database without specifications")
        else:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"The AI daily rate limit exceeded. Please wait until tomorrow before trying again. The component has been saved in the database without specifications")

    try:
        save_version_backup(db, component) # save a backup of the current version before updating
        component.specifications = parsed_specs.get("specifications")
        component.description = parsed_specs.get("description")
        db.commit()
        set_cache(f"component:{upn}", ComponentResponse.model_validate(component, from_attributes=True)) # update the cache with the new data

    except Exception as e:
        logger.exception(f"Error while updating specifications for {upn}: {e}")
        
        db.rollback() # rollback the session to prevent issues
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update specifications for {upn}")

    logger.success(f"Successfully updated specifications for {upn}")
    logger.debug(f"New specifications: {component.specifications}")
    return component

@router.get("/{part_number}", response_model=ComponentResponse)
@limiter.limit(component_fetch_ratelimit) # dynamic rate limit

def fetch_component(
        request: Request, 
        part_number: str, 
        manufacturer: str | None = Query(None, description="Optionally specify the manufacturer of the component"), 
        skip_ai: bool = Query(False, description="Skip AI parsing of datasheet PDF. (Faster response but won't get detailed specifications, only applies to new components not in our database)"), 
        force_fetch: bool = Query(False, description="Force fetch the component from external sources. Useful if you want to fully refresh the component data"), 
        db: Session = Depends(get_db)
    ):
    """Fetch the specifications for a specific component!"""    
    logger.info(f"GET /components/{part_number} endpoint requested by IP: '{request.client.host}'")

    upn = part_number.upper() # uppercase part number
    key = f"component:{upn}"

    # Check cache first
    cached = get_from_cache(key)
    if cached and not force_fetch:
        logger.debug(f"Found {part_number} in cache, returning result")
        return cached

    # Checking database
    component_db = db.get(ComponentModel, upn)
    if component_db and not force_fetch:
        logger.debug(f"Found {part_number} in database, caching and returning result")
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
        logger.warning(f"Invalid manufacturer request: '{manufacturer}'")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"We don't have data for that manufacturer. Available manufacturers: {', '.join(available_manufacturers)}")

    # Race condition handling using redis:
    lock_key = f"lock:scraper:{upn}"
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=120) # set a lock for 2 minutes
    
    if not lock_acquired:
        logger.info(f"Race condition detected for {upn}. Another request is already fetching this component. Waiting...")
        for s in range(120): # wait for 2 minutes
            time.sleep(1)
            fetched = get_from_cache(key)
            if fetched:
                logger.success(f"Grabbed {upn} from cache after waiting {s} second/s")
                return fetched
        logger.error(f"Race condition timed out while waiting for other request to finish fetching {upn}.")
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Request timed out while waiting for component data, Please try again")


    logger.info(f"Fetching component {upn} from external resources...")
    try:
        scraped = fetch_datasheet_url(part_number, manufacturer=manufacturer, skip_ai=skip_ai)
        if not scraped: # Couldn't find part at all
            if manufacturer:
                logger.warning(f"Component {upn} from manufacturer: '{manufacturer.lower()}' could not be found in external resources")
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} from manufacturer: '{manufacturer.lower()}' not found in external resources")

            logger.warning(f"Component {upn} could not be found in external resources")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component {upn} not found in external resources")

        # RATELIMIT HANDLING
        if type(scraped) != int and "RATELIMIT_EXCEEDED" in scraped:
            logger.log("RATELIMIT", f"AI rate limit exceeded while fetching {upn}. Info: {scraped}")
            try:
                newComponent = ComponentModel(**scraped.get("component").model_dump())
                db.add(newComponent)
                save_version_backup(db, newComponent)
                db.commit()
                db.refresh(newComponent)
            except IntegrityError as e:
                logger.exception(f"Database Integrity error while adding {part_number} to database: {e}")
                db.rollback()
            except Exception as e:
                logger.exception(f"Could not add {part_number} to database after exceeded AI limit: {e}")

            if scraped["TYPE"] == "MINUTE_LIMIT":
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"The AI exceeded it's limit. Please wait a minute before trying again. The component has been saved in the database without specifications")
            else:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"The AI's daily limit has been exceeded. Please wait until tomorrow before trying again. The component has been saved in the database without specifications")

        if type(scraped) == int and scraped == 500:
            logger.error(f"Datasheet Scraper returned a 500 error when attempting to fetch component {upn}.")
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Our datasheet provider DatasheetArchive returned a 500 error for the component {upn}. Please try again later.")

        try:
            if force_fetch and db.get(ComponentModel, upn):
                logger.debug(f"Force fetch requested, deleting old database entry for {upn}")
                save_version_backup(db, db.get(ComponentModel, upn))
                db.delete(db.get(ComponentModel, upn)) # delete the old component if it exists so we can add the new one for force fetch

            newComponent = ComponentModel(**scraped.model_dump()) # unpacked dumped data into a new pydantic component model
            db.add(newComponent)
            save_version_backup(db, newComponent)
            db.commit()
            db.refresh(newComponent)
            logger.success(f"Component {upn} fetched and added to database")
        except IntegrityError as e:
            logger.exception(f"Database Integrity error while adding {part_number} to database: {e}")
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"There was an integrity error while adding {part_number} to the database")

        except Exception as e:
            logger.exception(f"Could not add {part_number} to database: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error while adding {part_number} to the database")

        result = ComponentResponse.model_validate(newComponent, from_attributes=True)
        set_cache(key, result)

        return result
    finally:
        redis_client.delete(lock_key)


@router.get("", response_model=list[ComponentResponse])
@limiter.limit("30/minute") # limit to 30 requests per minute
def get_components(request: Request, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=50), db: Session = Depends(get_db)): # minimum page size 1, default 25, max 50
    """Fetch all components in our database! Use the parameters 'page' and 'page_size' to paginate the results. (Default page size is 25, max 50)"""
    logger.info(f"GET /components/ endpoint requested by IP: '{request.client.host}'")

    components = db.execute(select(ComponentModel).offset((page - 1) * page_size).limit(page_size)).scalars().all()

    if not components:
        logger.warning(f"No components found in database for page {page} with page size {page_size}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No components found")

    logger.debug(f"Fetched {len(components)} components from database for page {page} with page size {page_size}")
    return components