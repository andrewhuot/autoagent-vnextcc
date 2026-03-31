"""Google Cloud authentication for CX Agent Studio API."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .errors import CxAuthError


class CxAuth:
    """Handles Google Cloud auth via ADC or service account JSON.

    Usage::

        # Application Default Credentials (gcloud auth application-default login)
        auth = CxAuth()

        # Explicit service account key file
        auth = CxAuth(credentials_path="/path/to/key.json")

        headers = auth.get_headers()  # {"Authorization": "Bearer …", …}
    """

    def __init__(self, credentials_path: str | None = None) -> None:
        self._credentials_path = credentials_path
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._project_id: str | None = None
        self._auth_type: str = "adc"
        self._principal: str | None = None
        self._init_credentials()

    def _init_credentials(self) -> None:
        """Initialize credentials from ADC or service account file.

        For service account files we eagerly read the project_id so it is
        available before the first token refresh.  ADC project_id is resolved
        lazily during ``_refresh_if_needed``.
        """
        if self._credentials_path:
            path = Path(self._credentials_path)
            if not path.exists():
                raise CxAuthError(
                    f"Credentials file not found: {self._credentials_path}"
                )
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._project_id = data.get("project_id")
                self._principal = data.get("client_email")
                self._auth_type = "service_account"
            except (json.JSONDecodeError, KeyError) as exc:
                raise CxAuthError(f"Invalid credentials file: {exc}") from exc
        # For ADC we rely on google.auth.default() at token refresh time

    def get_headers(self) -> dict[str, str]:
        """Return Authorization headers with a fresh access token.

        Refreshes the token automatically if it is expired or within 60 s of
        expiry.

        Raises:
            CxAuthError: if no valid token can be obtained.
        """
        self._refresh_if_needed()
        if self._token is None:
            raise CxAuthError("No valid access token available")
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _refresh_if_needed(self) -> None:
        """Refresh the access token if expired or about to expire (within 60 s)."""
        if self._token and time.time() < self._token_expiry - 60:
            return
        try:
            import google.auth
            import google.auth.transport.requests

            _scopes = [
                "https://www.googleapis.com/auth/cloud-platform",
                "https://www.googleapis.com/auth/dialogflow",
            ]

            if self._credentials_path:
                from google.oauth2 import service_account

                creds = service_account.Credentials.from_service_account_file(
                    self._credentials_path,
                    scopes=_scopes,
                )
                self._auth_type = "service_account"
                self._principal = getattr(creds, "service_account_email", self._principal)
            else:
                creds, project = google.auth.default(scopes=_scopes)
                if not self._project_id:
                    self._project_id = project
                self._principal = getattr(
                    creds,
                    "service_account_email",
                    getattr(creds, "account", self._principal),
                )
                if getattr(creds, "service_account_email", None):
                    self._auth_type = "service_account"
                else:
                    self._auth_type = "adc"

            creds.refresh(google.auth.transport.requests.Request())
            self._token = creds.token
            self._token_expiry = time.time() + 3500  # ~1 hour

        except ImportError:
            raise CxAuthError(
                "google-auth package not installed. "
                "Install with: pip install google-auth"
            )
        except Exception as exc:
            raise CxAuthError(f"Failed to refresh credentials: {exc}") from exc

    @property
    def project_id(self) -> str | None:
        """GCP project ID, resolved from credentials or ADC."""
        return self._project_id

    @property
    def auth_type(self) -> str:
        """Return the current credential source."""

        return self._auth_type

    @property
    def principal(self) -> str | None:
        """Return the authenticated principal when available."""

        return self._principal

    def describe(self) -> dict[str, str | None]:
        """Refresh credentials if needed and return auth metadata for UX surfaces."""

        self._refresh_if_needed()
        return {
            "project_id": self._project_id,
            "auth_type": self._auth_type,
            "principal": self._principal,
            "credentials_path": self._credentials_path,
        }
