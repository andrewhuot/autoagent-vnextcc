"""CX Studio error types."""
from __future__ import annotations


class CxStudioError(Exception):
    """Base error for CX Studio operations."""


class CxAuthError(CxStudioError):
    """Authentication or authorization failure."""


class CxApiError(CxStudioError):
    """REST API call failed."""

    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class CxMappingError(CxStudioError):
    """Config mapping error."""


class CxImportError(CxStudioError):
    """Import pipeline error."""


class CxExportError(CxStudioError):
    """Export pipeline error."""
