# Component Lookup API

An API that finds datasheets for all major electronic components and uses AI to compile their specifications

Note:  
This API relies on Gemini's free tier plan for extracting pdf data, so when you request a new component that isnt in our database, the specifications table may be returned empty to avoid reaching the request free tier limit.

FastAPI  
Redis  
SSQAlchemy + Supabase  
BeautifulSoup  

Routes:  

GET /docs - API Documentation  
GET /redocs - API Documentation #2  
GET /health - Check the status of the API  
GET /components - Returns a list of every component currently stored  
GET /components/{part_number} - Fetch the data for a single component  
GET /components/sync - syncs the cache with the database (1min cooldown)  
GET /components/update - clears the data for a component and forces a refresh of that material  
GET /components/fillmissingspecs - (auth) find all the components that previously hit the AI limit and attempt to fill out their specification tables again.  
PUT /components/{part_number} - (auth) force update a component to specific specs that you have  
DELETE /components/{part_number} - (auth) delete a component off the database & cache  