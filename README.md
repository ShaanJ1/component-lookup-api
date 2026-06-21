# Component Lookup API

An API that searches for manufacturer electronic component specs 


FastAPI
Redis
SSQAlchemy + Supabase
Beautifulsoup

Routes:

/docs - documents
/redocs - other version of docs
/health - check the status of the api
/components - returns a list of all components currently in cache
/components/{component_name} - fetch a single component