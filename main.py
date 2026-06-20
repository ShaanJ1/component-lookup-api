from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from scraper import fetch_datasheet_url

app = FastAPI(
    # Docs info
    title="Component Lookup API",
    summary="An API that allows people to search for specific electronic components and their specifications by scraping external resources and caching them in a database.",
    description="This API was made to help makers quickly find the specifications for electronic comopnents without having to manually search through websites and various datasheets to find the right information. All searches are case-insensitive.",
    version="1.0.0",
    #redirect_slashes=True # check if u should keep this on or not
    )

## Classes ##
class Component(BaseModel):
    part_number: str
    description: str
    category: str
    specifications: dict


## API Endpoints ##


############ fix not working
@app.get("/")
async def root():
    """Root page"""
    return {"message": "Welcome to Component Lookup API!. Navigate through /docs for documentation"}
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
    return {"message": "component list"}

# fetching should go in this order: check cache, db, then scrape external resources
@app.get("/components/{part_number}", response_model=Component)
def components_part_number(part_number: str):
    """Fetch the specifications for a specific component!"""
    
    scraped_data = fetch_datasheet_url(part_number)
    if (scraped_data):
        print(scraped_data)


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
