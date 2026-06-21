from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import uvicorn

from typing import Optional

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.types import JSON

import os
from dotenv import load_dotenv

from scraper import fetch_datasheet_url

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

engine = sa.create_engine(database_url)

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

## Classes ##
class Component(BaseModel):
    part_number: str
    description: str | None
    category: str | None
    specifications: dict[str, str] | None
    datasheet_url: str
    source: str


# cache functions

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


## API Endpoints ##
# Prioritize fetching from Redis Cache first for speed, then checks database to make sure, then scrapes external resources if not found at all


############ fix not working
# @app.get("/")
# async def root():
#     """Root page"""
#     return {"message": "Welcome to Component Lookup API!. Navigate through /docs for documentation"}
############

@app.get("/health") # add more detailed metric tracking
def health():
    """Get the current API status and metrics"""
    return {
        "message": "The API is running!",
        "status": "online"
        }

@app.get("/components")
def components():
    """Fetch all components currently cached in our database!"""

    with Session(engine) as session:
        query = select(ComponentModel)
        components = session.scalars(query).all()
        print(components)
        for component in components:
            print(f"Fetched {component.part_number} from database")
        
    return {} # check to see what prints out then add returned components

# fetching should go in this order: check cache, db, then scrape external resources
@app.get("/components/{part_number}", response_model=Component)
def components_part_number(part_number: str):
    """Fetch the specifications for a specific component!"""    

    upn = part_number.upper() # upper part number
    key = f"component:{upn}"

    # Check cache first
    key = f"component:{upn}"
    cached = get_from_cache(key)

    print(cached)
    if cached:
        return None

    # Checking database
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

    ## Scraping external resources
    # Todo: add pdf scraping in scraper.py and make it return all the arguments for a component
    scraped = fetch_datasheet_url(part_number)
    if (scraped):
        with Session(engine) as session:
            newComponent = ComponentModel(
                part_number = part_number,
                datasheet_url = scraped.datasheet_url,
                source = scraped.source
            )
            session.add(newComponent)
            session.commit()
    
        result = Component(
            part_number = part_number,
            description = "",
            category = "",
            specifications = {},
            datasheet_url = scraped.datasheet_url,
            source = scraped.source
        )
        set_cache(key, result)

        return result

    # if part_number.upper() == "NE555":## placeholder for testing
    #     return Component( 
    #         part_number = "NE555",
    #         description = "A timer IC",
    #         category = "Integrated Circuit",
    #         specifications = {
    #             "Operating Voltage": "4.5V to 15V",
    #             "Output Current": "200mA",
    #             "Frequency Range": "0.001Hz to 2MHz"
    #         }
    #     )
    
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
