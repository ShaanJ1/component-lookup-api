from slowapi import Limiter
from slowapi.util import get_remote_address

from cache import redis_host, redis_port

limiter = Limiter(
    key_func = get_remote_address, 
    storage_uri = f"redis://{redis_host}:{redis_port}" 
    )