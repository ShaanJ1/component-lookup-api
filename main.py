from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from cache import redis_host, redis_port

from sqlalchemy import text

import os
from dotenv import load_dotenv

import psutil
import time

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from routers import components

from database import engine
from cache import redis_client
from ratelimit import limiter
from contextvars import ContextVar

load_dotenv()

app_start_time = time.time()

# Set up FastAPI app
app = FastAPI(
    # Docs info
    title="Component Lookup API",
    summary="An API that allows people to search for specific electronic components and their specifications by scraping external resources and caching them in a database.",
    description="This API was made to help people quickly find the specifications for electronic components without having to manually search through websites and various datasheets to find the right information. All searches are case-insensitive.",
    version="1.0.0"
    )

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(components.router)

## Custom API Ratelimit Message

@app.exception_handler(RateLimitExceeded)
def handle_rate_limit_exceeded(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded errors"""
    return JSONResponse(
        status_code=exc.status_code, # 429
        content={
            "error": "Too Many Requests",
            "message": "You have exceeded the API's rate limit. Please try again later.",
            "cooldown": f"{exc.limit.limit.get_expiry()} second/s"
            }
    )

# Context variable for request object
request_ctx: ContextVar[Request] = ContextVar("request_ctx")

@app.middleware("http")
async def add_request_to_context(request: Request, call_next):
    token = request_ctx.set(request)
    try:
        return await call_next(request)
    finally:
        request_ctx.reset(token)

# Health check functions
def check_db_connection():
    """Check if the database connection is good by executing a query"""
    with engine.connect() as connection:
        try:
            connection.execute(text("SELECT 1")) # simple query that checks if the database is reachable
            return True

        except Exception as e:
            print(f"Database connection failed. (main.py | line 65): {e}")
            return False

def check_redis_connection():
    """Checks if the redis connection is good by pinging the redis server"""
    try:
        return redis_client.ping()
    
    except Exception as e:
        print(f"Redis connection failed. (main.py | line 74): {e}")
        return False

## API Endpoints ##

@app.get("/health")
@limiter.limit("1/second") # limit to 1 request per second
def health(request: Request):
    """Get the current API status and api metrics"""
    start_time = time.time_ns()
    start_time_seconds = start_time / 1_000_000_000 # convert to seconds

    uptime = start_time_seconds - app_start_time #

    db_connection = check_db_connection()
    redis_connection = check_redis_connection()

    db_status = "down"
    cache_status = "down"

    if db_connection:
        db_status = "good"

    if redis_connection:
        cache_status = "good"

    ping = (time.time_ns() - start_time) / 1_000_000 # calculate ping in milliseconds
    process = psutil.Process(os.getpid()) # get the current process to check system metrics

    return {
        "status": "online",
        "uptime": f"{round(uptime, 2)} seconds",
        "ping": f"{round(ping, 2)} milliseconds",
        "system": {
            "cpu_usage": f"{psutil.cpu_percent(interval=0.05)}%", # sample interval of 0.05 seconds
            "memory_usage": f"{round(process.memory_info().rss / 1024 / 1024, 2)} MB", # physical ram used by process, converting bytes to MB
            "threads": process.num_threads(), # threads used by process
            "available_memory": f"{round(psutil.virtual_memory().available / 1024 / 1024, 2)} MB" # available memory on system, converting bytes to MB
        },
        "dependencies": {
            "database": db_status,
            "cache": cache_status
        }
    }

@app.get("/")
async def root():
    """Root page"""
    return {"message": "Welcome to Component Lookup API!. Navigate through /docs or /redocs for documentation"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) # 127.0.0.1 for local testing, 0.0.0.0 for production