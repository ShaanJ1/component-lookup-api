from fastapi import Security, status, HTTPException, Request
from fastapi.security.api_key import APIKeyHeader
from dotenv import load_dotenv
from os import getenv

from loguru import logger

load_dotenv()

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

API_KEY = getenv("API_KEY")

if not API_KEY:
    logger.critical("API_KEY environment variable is not set.")

def get_api_key(request: Request, api_key: str = Security(api_key_header)):
    if api_key == API_KEY:
        logger.debug(f"API key validated for IP: '{request.client.host}'")
        return api_key
    
    logger.debug(f"Invalid API key attempt from IP: '{request.client.host}'")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API Key."
    )