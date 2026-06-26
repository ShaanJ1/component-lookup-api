# Component Lookup API

An API that finds datasheets for all major electronic components and compiles their specifications

### Features:
- Caching + Database  
- Rate limiting  
- AI powered pdf data extraction  
- 11 total endpoints  
- Input validation and error handling  

### Tech Stack
FastAPI - API Framework  
Uvicorn - ASGI Server  
Database - PostgreSQL  
ORM - SQLAchemy  
Data Validation - Pydantic  
AI - Google AI API  
Dependency Manager - uv  

### Clone Repository
- Clone this repository  
- Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/)  
- Create a `.env` file with your GOOGLE_API_KEY and postgres DATABASE_URL  
- Install the project dependencies with  `uv sync`  
- Run the program with `uv run main.py`  

### Limitations
- Data parsing of datasheets rely on the free tier of Google's AI  
- Allow up to a full minute for fetching a new component (largely due to AI limits)
- If a requested component is not in our database, the API fetches the datasheet and then sends it to an AI to extract the component specs  
- Because of the different failures that could occur (hitting free tier ratelimits, model experiencing high demand, etc), the API switches between 3 different models:  
    1. Gemini 3.5 Flash  
    2. Gemini 3 Flash Preview  
    3. Gemini 2.5 Flash  
- If all 3 models failed, the specifications table will return empty. You may try again later using the endpoint `/components/updatespecs/{part_number}` to restart the AI fetching process.

## Errors
Here are some error responses the API may produce.
| Status | Description |
| :----: | :---------- |
|   400  | Invalid Request |
|   401  | Authentication Required |
|   404  | Component not found |
|   429  | Rate Limit Exceeded |
|   500  | Internal Server Error |

### Endpoints:  

Base link: .....  

| Method  |  Auth? | Endpoint                                   | Description |
| :-----: | :----: | :----------------------------------------- | :----------- |
|   GET   |   ❌   | /docs                                      | Open the documentation of the API              |
|   GET   |   ❌   | /redocs                                    | Open the alternate documentation of the API    |
|   GET   |   ❌   | /health                                    | View detailed health metrics of the API        |
|   GET   |   ❌   | /components                                | View the list of components stored in our database. Optionally, you can add the parameters ?page=1&limit=20 |
|   GET   |   ❌   | /components/{part_number}                  | Fetch the specifications for your requested part. Will return a 000 Component not found error if our sources didn't have that component. Its normal to allow up to ~1 minute for a response if the part is not in our database and we have to actively fetch it. A majority of the time taken is waiting for the AI to compile the information. |
|   GET   |   ❌   | /components/sync                           | Sync the API's cache with the database (This shouldn't normally be used as the system rarely fails, but made as a fail safe if something goes wrong) |
|   GET   |   ❌   | /components/update/{part_number}           | Refetches all the data again for a specific component |
|   GET   |   ❌   | /components/updatespecs/{part_number}      | Forces a refresh for a specific part's specification |
|   GET   |   ✅   | /components/fillmissingspecs               | Cycles through every part in the database with missing information due to AI limits, and attempts to fill them in again |
|   GET   |   ✅   | /components/viewsaves/{part_number}        | View the older versions of a specific part (if applicable, part may have been changes due to a manual PUT or update request) |
|   PUT   |   ✅   | /components/{part_number}                  | Manually add in your own information to a specific part. |
|  DELETE |   ✅   | /components/{part_number}                  | Permanently delete a specific part's information out of our databases. |  