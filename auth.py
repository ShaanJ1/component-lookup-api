from fastapi import Security, status, HTTPException
from fastapi.security.api_key import APIKeyHeader
from dotenv import load_dotenv
from os import getenv

load_dotenv()

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

API_KEY = getenv("API_KEY")

def get_api_key(api_key: str = Security(api_key_header)):
    if api_key == API_KEY:
        return api_key
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API Key."
    )