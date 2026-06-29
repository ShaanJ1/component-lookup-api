from contextvars import ContextVar
from fastapi import Request

# Context variable for request object
request_ctx: ContextVar[Request] = ContextVar("request_ctx")