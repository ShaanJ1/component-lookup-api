import redis
from schemas import ComponentResponse

from loguru import logger

redis_host ="localhost"
redis_port = 6379

redis_client = redis.Redis(
    host=redis_host, 
    port=redis_port, 
    db=0, 
    decode_responses=True
    )

CACHE_TTL = 24 * 60 * 60 # cache redis data for 24hr

def get_from_cache(key: str):
    """Get a value from the cache by key, returns None if not found"""
    data = redis_client.get(key)
    if data:
        logger.debug(f"Cache found for {key} with value: '{data}'")
        return ComponentResponse.model_validate_json(data)
    
    logger.trace(f"Cache miss for {key}")
    return None

def set_cache(key: str, value: ComponentResponse):
    """Set a component in the cache with a key"""
    logger.debug(f"Setting cache for {key}")
    redis_client.set(key, value.model_dump_json(), ex = CACHE_TTL)
    logger.success(f"Cache set for key: '{key}' with value: '{value.model_dump_json()}'")