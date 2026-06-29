from slowapi import Limiter
from slowapi.util import get_remote_address

from cache import redis_host, redis_port
from loguru import logger

logger.debug("Initializing SlowAPI Rate Limiter")
limiter = Limiter(
    key_func = get_remote_address, 
    storage_uri = f"redis://{redis_host}:{redis_port}" 
    )
logger.success("SlowAPI Rate Limiter initialized with Redis")