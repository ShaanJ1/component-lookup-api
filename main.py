from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import uvicorn

from sqlalchemy import select, text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.types import JSON

import os
from dotenv import load_dotenv

from scraper import fetch_datasheet_url

import time

load_dotenv()

app = FastAPI(
    # Docs info
    title="Component Lookup API",
    summary="An API that allows people to search for specific electronic components and their specifications by scraping external resources and caching them in a database.",
    description="This API was made to help makers quickly find the specifications for electronic comopnents without having to manually search through websites and various datasheets to find the right information. All searches are case-insensitive.",
    version="1.0.0",
    #redirect_slashes=True # check if u should keep this on or not
    )


redis_client = redis.Redis(
    host='localhost', 
    port=6379, 
    db=0, 
    decode_responses=True
    )

CACHE_TTL = 24 * 60 * 60 # 24 hours in seconds

database_url = os.getenv("DATABASE_URL")

engine = create_engine(database_url)

class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, str]: JSON
    }

class ComponentModel(Base):
    __tablename__ = "component"
    part_number:    Mapped[str] = mapped_column(primary_key=True, unique=True)
    description:    Mapped[str | None] = mapped_column()
    category:       Mapped[str | None] = mapped_column()
    specifications: Mapped[dict[str, str] | None] = mapped_column()
    datasheet_url:  Mapped[str] = mapped_column()
    source:         Mapped[str] = mapped_column()
    
Base.metadata.create_all(engine)

app_start_time = time.time()

## Classes ##
class Component(BaseModel):
    part_number: str
    description: str | None
    category: str | None
    specifications: dict[str, str] | None
    datasheet_url: str
    source: str


# Cache functions

def get_from_cache(key: str):
    data = redis_client.get(key)
    if data:
        print(f"Cache found for {key}")
        return Component.model_validate_json(data)
    else:
        print(f"Cache not found for {key}")
        return None

def set_cache(key: str, value: Component):
    print("Called set_cache")
    redis_client.set(key, value.model_dump_json(), ex = CACHE_TTL)
    print(f"Set cache for {key} with value of {value.model_dump_json()}")


# Health check functions

def check_db_connection():
    with engine.connect() as connection:
        try:
            connection.execute(text("SELECT 1"))
            return True

        except Exception as e:
            print(f"Database connection failed: {e}")
            return False

def check_redis_connection():
    try:
        return redis_client.ping()
    
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return False



## API Endpoints ##
# Prioritize fetching from Redis first for speed, if it fails then check database, then finally scrape external resources


############ fix not working
# @app.get("/")
# async def root():
#     """Root page"""
#     return {"message": "Welcome to Component Lookup API!. Navigate through /docs for documentation"}
############

@app.get("/health")
def health():
    """Get the current API status and api metrics"""
    start_time = time.time_ns()
    start_time_seconds = start_time / 1_000_000_000

    uptime = start_time_seconds - app_start_time

    db_connection = check_db_connection()
    redis_connection = check_redis_connection()

    db_status = "down"
    cache_status = "down"

    if db_connection:
        db_status = "good"

    if redis_connection:
        cache_status = "good"

    ping = (time.time_ns() - start_time) / 1_000_000 # ping in ms
    return {
        "status": "online",
        "uptime": f"{round(uptime, 2)} seconds",
        "ping": f"{round(ping, 2)} milliseconds",
        "dependencies": {
            "database": db_status,
            "cache": cache_status
        }
    }

@app.get("/components")
def components():
    """Fetch all components in our database!"""

    with Session(engine) as session:
        query = select(ComponentModel)
        components = session.scalars(query).all()
        print(components)
        for component in components:
            print(f"Fetched {component.part_number} from database")
        
    return components

# fetching should go in this order: check cache, db, then scrape external resources
@app.get("/components/{part_number}", response_model=Component)
def components_part_number(part_number: str):
    """Fetch the specifications for a specific component!"""    

    upn = part_number.upper() # uppercase part number
    key = f"component:{upn}"

    for key in redis_client.scan_iter(match="*"):
        print(key)



    # Check cache first
    key = f"component:{upn}"
    cached = get_from_cache(key)

    print(cached)
    if cached:
        return cached

    # Checking database as a backup
    with Session(engine) as session:
        component = session.get(ComponentModel, upn)
        if component:
            print(f"Found {part_number} in database!")
            return Component(
                part_number = component.part_number,
                description = component.description,
                category = component.category,
                specifications = component.specifications,
                datasheet_url = component.datasheet_url,
                source = component.source
            )
        else:
            print(component)


    ## Scraping external resources
    # Todo: add pdf scraping in scraper.py and make it return all the arguments for a component
    scraped = fetch_datasheet_url(part_number)
    if (scraped):
        try:
            with Session(engine) as session:
                newComponent = ComponentModel(
                    part_number = upn,
                    description = "",
                    category = "",
                    specifications = {},
                    datasheet_url = scraped.datasheet_url,
                    source = scraped.source
                )
                session.add(newComponent)
                session.commit()

        except Exception as e:
            print(f"Could not add {part_number} to database: {e}")
    
        result = Component(
            part_number = upn,
            description = "",
            category = "",
            specifications = {},
            datasheet_url = scraped.datasheet_url,
            source = scraped.source
        )
        set_cache(key, result)

        return result

    # If all else fails, return a 404
    raise HTTPException(status_code=404, detail="Component not found")


@app.get("/components/search")
def components_search(q: str):
    """Search through the database of components!"""
    return {"message": f"'{q}' has been found"}

@app.put("/components") # post or put?
def components(part_number: str, object: dict):
    """Manually add a component to the database. Expects part number and a table of specifications. (AUTH REQUIRED)"""
    return {"message": f"The added part was '{part_number}' and the added info was '{object}'"}

@app.delete("/components")
def components(part_number: str):
    """Manually delete a component from the database. Expects a part number. (REQUIRES AUTH)"""
    return {"message": f"Successfully deleted component '{part_number}' from database."}


uvicorn.run(app)
