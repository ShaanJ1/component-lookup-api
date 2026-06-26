from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import redis
import uvicorn

import requests

from sqlalchemy import select, text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.types import JSON

import os
from dotenv import load_dotenv

from scraper import fetch_datasheet_url, parse_pdf, models

from typing import Any

import psutil
import time

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

redis_host ="localhost"
redis_port = 6379

# Set up rate limiter
limiter = Limiter(
    key_func = get_remote_address, 
    storage_uri = f"redis://{redis_host}:{redis_port}" 
    ) 

# Set up FastAPI app
app = FastAPI(
    # Docs info
    title="Component Lookup API",
    summary="An API that allows people to search for specific electronic components and their specifications by scraping external resources and caching them in a database.",
    description="This API was made to help people quickly find the specifications for electronic components without having to manually search through websites and various datasheets to find the right information. All searches are case-insensitive.",
    version="1.0.0",
    #redirect_slashes=True # check if u should keep this on or not
    )

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Set up Redi Client
redis_client = redis.Redis(
    host=redis_host, 
    port=redis_port, 
    db=0, 
    decode_responses=True
    )

CACHE_TTL = 24 * 60 * 60 # cache redis data for 24hr

# start up the database
database_url = os.getenv("DATABASE_URL")
engine = create_engine(database_url)

## Database Models ##
class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSON
    }

class ComponentModel(Base):
    __tablename__ = "component"
    part_number:    Mapped[str] = mapped_column(primary_key=True, unique=True)
    description:    Mapped[str | None] = mapped_column()
    specifications: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    datasheet_url:  Mapped[str] = mapped_column()
    source:         Mapped[str] = mapped_column()
    
Base.metadata.create_all(engine) 

app_start_time = time.time()

## Classes ##
class Component(BaseModel):
    part_number: str
    description: str | None
    specifications: dict[str, Any] | None
    datasheet_url: str
    source: str


## Cache functions ##
def get_from_cache(key: str):
    data = redis_client.get(key)
    if data:
        print(f"Cache found for {key}")
        return Component.model_validate_json(data)
    else:
        print(f"Cache not found for {key}")
        return None

def set_cache(key: str, value: Component):
    redis_client.set(key, value.model_dump_json(), ex = CACHE_TTL)
    print(f"Set cache for {key} with value of {value.model_dump_json()}")


# Health check functions
def check_db_connection():
    with engine.connect() as connection:
        try:
            connection.execute(text("SELECT 1")) # simple query that checks if the database is reachable
            return True

        except Exception as e:
            print(f"Database connection failed. (main.py | line 115): {e}")
            return False

def check_redis_connection():
    try:
        return redis_client.ping()
    
    except Exception as e:
        print(f"Redis connection failed. (main.py | line 123): {e}")
        return False

## Custom API Ratelimit Message

@app.exception_handler(RateLimitExceeded)
def handle_rate_limit_exceeded(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=exc.status_code, # 429
        content={
            "error": "Too Many Requests",
            "message": "You have exceeded the API's rate limit. Please try again later.",
            "retry_after": f"{exc.limit.limit.get_expiry()} second/s"
            }
    )

## API Endpoints ##

############ fix not working
# @app.get("/")
# async def root():
#     """Root page"""
#     return {"message": "Welcome to Component Lookup API!. Navigate through /docs for documentation"}
############

@app.get("/health")
@limiter.limit("1/second") # limit to 1 request per second
def health(request: Request):
    """Get the current API status and api metrics"""
    start_time = time.time_ns()
    start_time_seconds = start_time / 1_000_000_000 # convert to seconds

    uptime = start_time_seconds - app_start_time #

    db_connection = check_db_connection()
    redis_connection = check_redis_connection()

    db_status = "down"
    cache_status = "down"

    if db_connection:
        db_status = "good"

    if redis_connection:
        cache_status = "good"

    ping = (time.time_ns() - start_time) / 1_000_000 # calculate ping in milliseconds
    process = psutil.Process(os.getpid()) # get the current process to check system metrics

    return {
        "status": "online",
        "uptime": f"{round(uptime, 2)} seconds",
        "ping": f"{round(ping, 2)} milliseconds",
        "system": {
            "cpu_usage": f"{psutil.cpu_percent(interval=0.05)}%", # sample interval of 0.05 seconds
            "memory_usage": f"{round(process.memory_info().rss / 1024 / 1024, 2)} MB", # physical ram used by process, converting bytes to MB
            "threads": process.num_threads(), # threads used by process
            "available_memory": f"{round(psutil.virtual_memory().available / 1024 / 1024, 2)} MB" # available memory on system, converting bytes to MB
        },
        "dependencies": {
            "database": db_status,
            "cache": cache_status
        }
    }

@app.get("/components")
@limiter.limit("30/minute") # limit to 30 requests per minute
def components(request: Request):
    """Fetch all components in our database!"""

    with Session(engine) as session:
        query = select(ComponentModel)
        components = session.scalars(query).all()
        for component in components:
            print(f"Fetched {component.part_number} from database")
        
    if components == []:
        components = {"message": "No components found in our database"}

    return components

# fetching should go in this order: check cache, db, then scrape external resources
@app.get("/components/{part_number}", response_model=Component)
@limiter.limit("20/minute") # limit to 20 requests per minute
def components_part_number(request: Request, part_number: str):
    """Fetch the specifications for a specific component!"""    

    upn = part_number.upper() # uppercase part number
    key = f"component:{upn}"

    # Check cache first
    cached = get_from_cache(key)
    if cached:
        return cached

    # Checking database as a backup
    with Session(engine) as session:
        component = session.get(ComponentModel, upn)
        if component:
            print(f"Found {part_number} in database!")
            result = Component(
                part_number = component.part_number,
                description = component.description,
                specifications = component.specifications,
                datasheet_url = component.datasheet_url,
                source = component.source
            )

            set_cache(key, result) # if found in db but not cache, add it to cache

            return result
        else:
            print(f"{part_number} not found in database.")


    ## Scraping external resources
    scraped = fetch_datasheet_url(part_number)
    if (scraped):
        try:
            with Session(engine) as session: 
                newComponent = ComponentModel(
                    part_number = upn,
                    description = scraped.description,
                    specifications = scraped.specifications,
                    datasheet_url = scraped.datasheet_url,
                    source = scraped.source
                )
                session.add(newComponent)
                session.commit()

        except Exception as e:
            print(f"Could not add {part_number} to database. (main.py | line 254): {e}")
    
        result = Component(
            part_number = upn,
            description = scraped.description,
            specifications = scraped.specifications,
            datasheet_url = scraped.datasheet_url,
            source = scraped.source
        )
        set_cache(key, result)

        return result

    # If all else fails, return a 404
    raise HTTPException(status_code=404, detail="Component not found")

@app.get("/components/sync")
@limiter.limit("40/minute") # limit to 40 requests per minute
def components(request: Request, part_number: str, object: dict):
    """."""

@app.get("/components/update/{part_number}")
@limiter.limit("10/minute") # limit to 10 requests per minute
def components(request: Request, part_number: str, object: dict):
    """."""

@app.get("/components/updatespecs/{part_number}")
@limiter.limit("10/minute") # limit to 10 requests per minute
def components(request: Request, part_number: str, object: dict):
    """."""
    """Fill out the missing specifications for a specific component."""
    datasheet_url = ""

    try:
        with Session(engine) as session:
            component = session.get(ComponentModel, part_number.upper())
            datasheet_url = component.datasheet_url

    except Exception as e:
        print(f"Could not fetch datasheet URL from database for {part_number}. (main.py | line 293): {e}")
        raise HTTPException(status_code=404, detail="Could not fetch datasheet URL from database")

    if datasheet_url == "" or datasheet_url is None: # if the component is not in the database/datasheet url is empty, refetch the datasheet
        scraped = fetch_datasheet_url(part_number.upper())
        if not scraped:
            print(f"Could not fetch datasheet URL from external resources for {part_number}.")
            raise HTTPException(status_code=404, detail="Could not fetch datasheet URL from external resources")
        

        try: # add new fetched data to database
            datasheet_url = scraped.datasheet_url
            with Session(engine) as session:
                newComponent = ComponentModel(
                    part_number = part_number.upper(),
                    description = scraped.description,
                    specifications = scraped.specifications,
                    datasheet_url = scraped.datasheet_url,
                    source = scraped.source
                )
                session.add(newComponent)
                session.commit()

            set_cache(f"component:{part_number.upper()}", Component(
                part_number = part_number.upper(),
                description = scraped.description,
                specifications = scraped.specifications,
                datasheet_url = scraped.datasheet_url,
                source = scraped.source
            ))

        except Exception as e:
            print(f"Could not fetch datasheet URL from database for {part_number}. (main.py | line 325): {e}")
            raise HTTPException(status_code=404, detail="Could not fetch datasheet from database")


    response = requests.get(datasheet_url)
    if not response.status_code == 200:
        print(f"Could not fetch datasheet from URL: {datasheet_url}")
        raise HTTPException(status_code=404, detail="Could not fetch datasheet from URL")

    parsed = parse_pdf(response.content, part_number, models[0])

    if not parsed:
        print(f"Could not parse datasheet for {part_number}")
        raise HTTPException(status_code=404, detail="Could not parse datasheet for component")
    
    component = Component()
    
## AUTH PROTECTED ENDPOINTS ##

@app.get("/components/fillmissingspecs")
@limiter.limit("5/minute") # limit to 5 requests per minute
def components(request: Request, part_number: str):
    """Fill out the missing specifications for all components. (AUTH REQUIRED)"""

@app.get("/components/viewsaves/{part_number}")
@limiter.limit("50/minute") # limit to 50 requests per minute
def components(request: Request, part_number: str, object: dict):
    """View the past versions of a specific component. (AUTH REQUIRED)"""


@app.put("/components/{part_number}") # post or put?
@limiter.limit("20/minute") # limit to 20 requests per minute
def components(request: Request, part_number: str, object: dict):
    """Manually add a component to the database. Expects part number and a table of specifications. (AUTH REQUIRED)"""
    return {"message": f"The added part was '{part_number}' and the added info was '{object}'"}

@app.delete("/components/{part_number}")
@limiter.limit("20/minute") # limit to 20 requests per minute
def components(request: Request, part_number: str):
    """Manually delete a component from the database. Expects a part number. (AUTH REQUIRED)"""
    return {"message": f"Successfully deleted component '{part_number}' from database."}


uvicorn.run(app)