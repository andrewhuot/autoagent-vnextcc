"""REST API client for CX Agent Studio (Dialogflow CX v3).

Uses ``httpx`` when available and falls back to ``urllib.request`` so the
module remains importable in environments that have not installed httpx.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from .auth import CxAuth
from .errors import CxApiError
from .types import (
    CxAgent,
    CxAgentSnapshot,
    CxEnvironment,
    CxFlow,
    CxIntent,
    CxPlaybook,
    CxTestCase,
    CxTool,
)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_HTTPX_AVAILABLE: bool
try:
    import httpx  # type: ignore[import]
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


def _build_base_url(location: str) -> str:
    """Return the Dialogflow CX v3 base URL for a given location."""
    if location == "global":
        return "https://dialogflow.googleapis.com/v3"
    return f"https://{location}-dialogflow.googleapis.com/v3"


class CxClient:
    """Thin REST client for the Dialogflow CX v3 API.

    All methods return parsed Python dicts/lists or typed Pydantic models.
    Network errors are translated into ``CxApiError``.

    Args:
        auth: A ``CxAuth`` instance that supplies Authorization headers.
        timeout: Per-request timeout in seconds.
        max_retries: Number of times to retry on transient (5xx / 429) errors.
    """

    def __init__(
        self,
        auth: CxAuth,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._auth = auth
        self._timeout = timeout
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request with retry logic.

        Retries on HTTP 429 and 5xx responses with exponential back-off.

        Args:
            method: HTTP verb (``"GET"``, ``"POST"``, ``"PATCH"``, …).
            url: Full URL including query parameters.
            json_body: Optional JSON-serialisable request body.

        Returns:
            Parsed JSON response (dict, list, or ``None`` for empty bodies).

        Raises:
            CxApiError: on non-2xx final response or network failure.
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                headers = self._auth.get_headers()
                body_bytes = (
                    json.dumps(json_body).encode() if json_body is not None else None
                )

                if _HTTPX_AVAILABLE:
                    response = self._httpx_request(method, url, headers, body_bytes)
                else:
                    response = self._urllib_request(method, url, headers, body_bytes)

                status_code, response_text = response

                if status_code in (429, 500, 502, 503, 504) and attempt < self._max_retries - 1:
                    # Exponential back-off: 1s, 2s, 4s…
                    time.sleep(2 ** attempt)
                    continue

                if status_code < 200 or status_code >= 300:
                    raise CxApiError(
                        f"CX API error {status_code}: {url}",
                        status_code=status_code,
                        response_body=response_text,
                    )

                if not response_text:
                    return None
                return json.loads(response_text)

            except CxApiError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    time.sleep(2 ** attempt)

        raise CxApiError(
            f"Request failed after {self._max_retries} attempts: {last_exc}",
            status_code=0,
            response_body=str(last_exc),
        )

    def _httpx_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body_bytes: bytes | None,
    ) -> tuple[int, str]:
        """Execute request via httpx."""
        import httpx  # type: ignore[import]

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.request(
                method,
                url,
                headers=headers,
                content=body_bytes,
            )
        return resp.status_code, resp.text

    def _urllib_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body_bytes: bytes | None,
    ) -> tuple[int, str]:
        """Execute request via stdlib urllib (fallback)."""
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return exc.code, body

    # ------------------------------------------------------------------
    # Agent
    # ------------------------------------------------------------------

    def get_agent(self, agent_name: str) -> CxAgent:
        """Fetch a single CX agent by resource name.

        Args:
            agent_name: Fully-qualified name, e.g.
                ``projects/my-proj/locations/us-central1/agents/abc123``.
        """
        location = self._location_from_name(agent_name)
        base = _build_base_url(location)
        data = self._request("GET", f"{base}/{agent_name}")
        return CxAgent(
            name=data.get("name", ""),
            display_name=data.get("displayName", ""),
            default_language_code=data.get("defaultLanguageCode", "en"),
            description=data.get("description", ""),
            generative_settings=data.get("generativeSettings", {}),
        )

    def list_agents(self, project: str, location: str) -> list[CxAgent]:
        """List all CX agents in a project/location."""
        base = _build_base_url(location)
        parent = f"projects/{project}/locations/{location}"
        data = self._request("GET", f"{base}/{parent}/agents")
        agents_raw = data.get("agents", []) if data else []
        return [
            CxAgent(
                name=a.get("name", ""),
                display_name=a.get("displayName", ""),
                default_language_code=a.get("defaultLanguageCode", "en"),
                description=a.get("description", ""),
                generative_settings=a.get("generativeSettings", {}),
            )
            for a in agents_raw
        ]

    def update_agent(self, agent_name: str, updates: dict[str, Any]) -> CxAgent:
        """Patch a CX agent resource.

        Args:
            agent_name: Fully-qualified agent resource name.
            updates: Fields to update (uses PATCH semantics).
        """
        location = self._location_from_name(agent_name)
        base = _build_base_url(location)
        data = self._request("PATCH", f"{base}/{agent_name}", json_body=updates)
        return CxAgent(
            name=data.get("name", ""),
            display_name=data.get("displayName", ""),
            default_language_code=data.get("defaultLanguageCode", "en"),
            description=data.get("description", ""),
            generative_settings=data.get("generativeSettings", {}),
        )

    # ------------------------------------------------------------------
    # Playbooks
    # ------------------------------------------------------------------

    def list_playbooks(self, agent_name: str) -> list[CxPlaybook]:
        """List all playbooks for a CX agent."""
        location = self._location_from_name(agent_name)
        base = _build_base_url(location)
        data = self._request("GET", f"{base}/{agent_name}/playbooks")
        items = data.get("playbooks", []) if data else []
        return [
            CxPlaybook(
                name=p.get("name", ""),
                display_name=p.get("displayName", ""),
                instructions=p.get("instruction", {}).get("steps", []),
                steps=p.get("steps", []),
                examples=p.get("examples", []),
            )
            for p in items
        ]

    def update_playbook(
        self, playbook_name: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Patch a CX playbook resource.

        Args:
            playbook_name: Fully-qualified playbook resource name.
            updates: Fields to update.
        """
        location = self._location_from_name(playbook_name)
        base = _build_base_url(location)
        return self._request("PATCH", f"{base}/{playbook_name}", json_body=updates)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def list_tools(self, agent_name: str) -> list[CxTool]:
        """List all tools registered on a CX agent."""
        location = self._location_from_name(agent_name)
        base = _build_base_url(location)
        data = self._request("GET", f"{base}/{agent_name}/tools")
        items = data.get("tools", []) if data else []
        return [
            CxTool(
                name=t.get("name", ""),
                display_name=t.get("displayName", ""),
                tool_type=t.get("toolType", ""),
                spec=t.get("openApiSpec", t.get("dataStoreSpec", {})),
            )
            for t in items
        ]

    # ------------------------------------------------------------------
    # Flows
    # ------------------------------------------------------------------

    def list_flows(self, agent_name: str) -> list[CxFlow]:
        """List all flows for a CX agent."""
        location = self._location_from_name(agent_name)
        base = _build_base_url(location)
        data = self._request("GET", f"{base}/{agent_name}/flows")
        items = data.get("flows", []) if data else []
        return [
            CxFlow(
                name=f.get("name", ""),
                display_name=f.get("displayName", ""),
                pages=f.get("pages", []),
                transition_routes=f.get("transitionRoutes", []),
                event_handlers=f.get("eventHandlers", []),
            )
            for f in items
        ]

    # ------------------------------------------------------------------
    # Intents
    # ------------------------------------------------------------------

    def list_intents(self, agent_name: str) -> list[CxIntent]:
        """List all intents for a CX agent."""
        location = self._location_from_name(agent_name)
        base = _build_base_url(location)
        data = self._request("GET", f"{base}/{agent_name}/intents")
        items = data.get("intents", []) if data else []
        return [
            CxIntent(
                name=i.get("name", ""),
                display_name=i.get("displayName", ""),
                training_phrases=i.get("trainingPhrases", []),
            )
            for i in items
        ]

    # ------------------------------------------------------------------
    # Test Cases
    # ------------------------------------------------------------------

    def list_test_cases(self, agent_name: str) -> list[CxTestCase]:
        """List all test cases for a CX agent."""
        location = self._location_from_name(agent_name)
        base = _build_base_url(location)
        data = self._request("GET", f"{base}/{agent_name}/testCases")
        items = data.get("testCases", []) if data else []
        return [
            CxTestCase(
                name=tc.get("name", ""),
                display_name=tc.get("displayName", ""),
                tags=tc.get("tags", []),
                conversation_turns=tc.get("testCaseConversationTurns", []),
                expected_output=tc.get("lastTestResult", {}),
            )
            for tc in items
        ]

    # ------------------------------------------------------------------
    # Environments
    # ------------------------------------------------------------------

    def list_environments(self, agent_name: str) -> list[CxEnvironment]:
        """List all environments for a CX agent."""
        location = self._location_from_name(agent_name)
        base = _build_base_url(location)
        data = self._request("GET", f"{base}/{agent_name}/environments")
        items = data.get("environments", []) if data else []
        return [
            CxEnvironment(
                name=e.get("name", ""),
                display_name=e.get("displayName", ""),
                description=e.get("description", ""),
                version_configs=e.get("versionConfigs", []),
            )
            for e in items
        ]

    def deploy_to_environment(
        self,
        environment_name: str,
        version_configs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Deploy a set of flow versions to an environment.

        Args:
            environment_name: Fully-qualified environment resource name.
            version_configs: List of ``{"version": "<flow_version_name>"}``
                dicts specifying which flow versions to activate.

        Returns:
            Long-running operation response dict.
        """
        location = self._location_from_name(environment_name)
        base = _build_base_url(location)
        body = {"versionConfigs": version_configs}
        return self._request(  # type: ignore[return-value]
            "PATCH", f"{base}/{environment_name}", json_body=body
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def fetch_snapshot(self, agent_name: str) -> CxAgentSnapshot:
        """Fetch and assemble a complete snapshot of a CX agent.

        Calls all list endpoints in sequence and returns a ``CxAgentSnapshot``
        that can be persisted for offline use.

        Args:
            agent_name: Fully-qualified agent resource name.
        """
        agent = self.get_agent(agent_name)
        playbooks = self.list_playbooks(agent_name)
        tools = self.list_tools(agent_name)
        flows = self.list_flows(agent_name)
        intents = self.list_intents(agent_name)
        test_cases = self.list_test_cases(agent_name)
        environments = self.list_environments(agent_name)

        return CxAgentSnapshot(
            agent=agent,
            playbooks=playbooks,
            tools=tools,
            flows=flows,
            intents=intents,
            test_cases=test_cases,
            environments=environments,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _location_from_name(resource_name: str) -> str:
        """Extract the GCP location from a fully-qualified resource name.

        Resource names follow the pattern::

            projects/{project}/locations/{location}/…

        Falls back to ``"global"`` when the name cannot be parsed.
        """
        parts = resource_name.split("/")
        try:
            loc_idx = parts.index("locations")
            return parts[loc_idx + 1]
        except (ValueError, IndexError):
            return "global"
