from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

app = FastAPI()

# fix not working
# @app.get("/")
# def read_root():
#     """Root page"""
#     return {"Welcome to component lookup api! Navigate through /docs for documentation"}

@app.get("/health")
def health():
    """Get the current API status and metrics"""
    return {"message": "I'm up!"}

@app.get("/components")
def components():
    """Fetch all components currently cached in our database!"""
    return {"message": "component list"}

# fetching should go in this order: check cache, db, then scrape external resources
@app.get("/components/{part_number}")
def components_part_number(part_number: str):
    """Fetch the specifications for a specific component!"""
    return {"message:": f"The specs for the {part_number} are...."}


@app.get("/components/search")
def components_search(query: str):
    """Search through the database of components!"""
    return {"message": f"'{query}' has been found"}

@app.post("/components")
def components(part_number: str, object: dict):
    """Manually add a component to the database. Expects part number and a table of specifications. (AUTH REQUIRED)"""
    return {"message": f"The added part was '{part_number}' and the added info was '{object}'"}

@app.delete("/components")
def components(part_number: str):
    """Manually delete a component from the database. Expects a part number. (REQUIRES AUTH)"""
    return {"message": f"Successfully deleted component '{part_number}' from database."}


uvicorn.run(app)
