"""ASGI entrypoint alias for `uvicorn api.main:app`."""

from api.server import app

__all__ = ["app"]
