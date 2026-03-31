"""Low-level Dialogflow CX REST client used by the CX Studio integration."""

from __future__ import annotations

import importlib.util
import json
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from cx_studio.errors import CxApiError
from cx_studio.types import (
    CxAgent,
    CxAgentSnapshot,
    CxEntityType,
    CxEnvironment,
    CxFlow,
    CxIntent,
    CxPage,
    CxPlaybook,
    CxTestCase,
    CxWebhook,
)

_HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def build_dialogflow_cx_base_url(location: str) -> str:
    """Return the correct Dialogflow CX REST base URL for a location."""

    normalized = (location or "global").strip().lower()
    if normalized in {"", "global"}:
        return "https://dialogflow.googleapis.com/v3"
    return f"https://{normalized}-dialogflow.googleapis.com/v3"


class CxStudioClient:
    """Authenticated Dialogflow CX REST client with retries and pagination."""

    def __init__(
        self,
        auth: Any,
        *,
        timeout: float = 30.0,
        max_retries: int = 4,
        page_size: int = 100,
    ) -> None:
        self._auth = auth
        self._timeout = timeout
        self._max_retries = max_retries
        self._page_size = page_size

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        location: str,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        """Issue a JSON request to the Dialogflow CX REST API."""

        base_url = build_dialogflow_cx_base_url(location)
        query = urllib.parse.urlencode(
            {key: value for key, value in (params or {}).items() if value is not None},
            doseq=True,
        )
        url = f"{base_url}/{path}"
        if query:
            url = f"{url}?{query}"

        body_bytes = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                headers = dict(self._auth.get_headers())
                headers.setdefault("Content-Type", "application/json")
                headers.setdefault("User-Agent", "autoagent-cx/1.0")

                status_code, response_text, response_headers = self._send(
                    method=method,
                    url=url,
                    headers=headers,
                    body_bytes=body_bytes,
                )

                if status_code in _RETRYABLE_STATUS_CODES and attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay_seconds(attempt, response_headers))
                    continue

                if status_code < 200 or status_code >= 300:
                    raise CxApiError(
                        f"Dialogflow CX API error {status_code} for {path}",
                        status_code=status_code,
                        response_body=response_text,
                    )

                if not response_text:
                    return {}
                return json.loads(response_text)
            except CxApiError:
                raise
            except Exception as exc:  # pragma: no cover - exercised through retry path
                last_error = exc
                if attempt >= self._max_retries - 1:
                    break
                time.sleep(2 ** attempt)

        raise CxApiError(
            f"Request failed after {self._max_retries} attempts: {last_error}",
            status_code=0,
            response_body=str(last_error),
        )

    def _send(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body_bytes: bytes | None,
    ) -> tuple[int, str, dict[str, str]]:
        """Send a request via httpx when installed, otherwise urllib."""

        if _HTTPX_AVAILABLE:
            import httpx  # type: ignore[import-not-found]

            with httpx.Client(timeout=self._timeout) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=body_bytes,
                )
            return response.status_code, response.text, dict(response.headers)

        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            url,
            data=body_bytes,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.status, response.read().decode("utf-8"), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace"), dict(exc.headers.items())

    @staticmethod
    def _retry_delay_seconds(attempt: int, response_headers: dict[str, str]) -> float:
        """Return the backoff delay for a retryable response."""

        retry_after = response_headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return float(2 ** attempt)

    def _iterate_pages(
        self,
        path: str,
        *,
        item_key: str,
        location: str,
        params: dict[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect all paginated items for a list endpoint."""

        results: list[dict[str, Any]] = []
        next_page_token: str | None = None
        base_params = dict(params or {})
        base_params.setdefault("pageSize", self._page_size)

        while True:
            request_params = dict(base_params)
            if next_page_token:
                request_params["pageToken"] = next_page_token
            payload = self._request_json(
                "GET",
                path,
                location=location,
                params=request_params,
            )
            results.extend(payload.get(item_key, []))
            next_page_token = payload.get("nextPageToken")
            if not next_page_token:
                break

        return results

    def list_agents(self, project: str, location: str = "global") -> list[CxAgent]:
        """List agents under a project/location parent."""

        path = f"projects/{project}/locations/{location}/agents"
        items = self._iterate_pages(path, item_key="agents", location=location)
        return [self._parse_agent(item) for item in items]

    def get_agent(self, agent_name: str) -> CxAgent:
        """Fetch a single agent."""

        payload = self._request_json(
            "GET",
            agent_name,
            location=self._location_from_name(agent_name),
        )
        return self._parse_agent(payload)

    def create_agent(
        self,
        project: str,
        location: str,
        payload: dict[str, object],
        agent_id: str | None = None,
    ) -> CxAgent:
        """Create an agent under the provided parent."""

        response = self._request_json(
            "POST",
            f"projects/{project}/locations/{location}/agents",
            location=location,
            params={"agentId": agent_id} if agent_id else None,
            json_body=payload,
        )
        return self._parse_agent(response)

    def update_agent(
        self,
        agent_name: str,
        updates: dict[str, object],
        update_mask: list[str] | None = None,
    ) -> CxAgent:
        """Patch an existing agent."""

        payload = dict(updates)
        if "name" not in payload:
            payload["name"] = agent_name
        response = self._request_json(
            "PATCH",
            agent_name,
            location=self._location_from_name(agent_name),
            params={"updateMask": ",".join(update_mask)} if update_mask else None,
            json_body=payload,
        )
        return self._parse_agent(response)

    def list_flows(self, agent_name: str) -> list[CxFlow]:
        """List all flows for an agent."""

        items = self._iterate_pages(
            f"{agent_name}/flows",
            item_key="flows",
            location=self._location_from_name(agent_name),
        )
        return [self._parse_flow(item) for item in items]

    def create_flow(
        self,
        parent: str,
        payload: dict[str, object],
        flow_id: str | None = None,
    ) -> CxFlow:
        """Create a flow under an agent."""

        response = self._request_json(
            "POST",
            f"{parent}/flows",
            location=self._location_from_name(parent),
            params={"flowId": flow_id} if flow_id else None,
            json_body=payload,
        )
        return self._parse_flow(response)

    def update_flow(
        self,
        flow_name: str,
        updates: dict[str, object],
        update_mask: list[str] | None = None,
    ) -> CxFlow:
        """Patch a flow."""

        payload = dict(updates)
        payload.setdefault("name", flow_name)
        response = self._request_json(
            "PATCH",
            flow_name,
            location=self._location_from_name(flow_name),
            params={"updateMask": ",".join(update_mask)} if update_mask else None,
            json_body=payload,
        )
        return self._parse_flow(response)

    def list_pages(self, flow_name: str) -> list[CxPage]:
        """List pages under a flow."""

        items = self._iterate_pages(
            f"{flow_name}/pages",
            item_key="pages",
            location=self._location_from_name(flow_name),
        )
        return [self._parse_page(item) for item in items]

    def update_page(
        self,
        page_name: str,
        updates: dict[str, object],
        update_mask: list[str] | None = None,
    ) -> CxPage:
        """Patch a page."""

        payload = dict(updates)
        payload.setdefault("name", page_name)
        response = self._request_json(
            "PATCH",
            page_name,
            location=self._location_from_name(page_name),
            params={"updateMask": ",".join(update_mask)} if update_mask else None,
            json_body=payload,
        )
        return self._parse_page(response)

    def list_intents(self, agent_name: str) -> list[CxIntent]:
        """List intents for an agent."""

        items = self._iterate_pages(
            f"{agent_name}/intents",
            item_key="intents",
            location=self._location_from_name(agent_name),
        )
        return [self._parse_intent(item) for item in items]

    def create_intent(
        self,
        parent: str,
        payload: dict[str, object],
        intent_id: str | None = None,
    ) -> CxIntent:
        """Create an intent under an agent."""

        response = self._request_json(
            "POST",
            f"{parent}/intents",
            location=self._location_from_name(parent),
            params={"intentId": intent_id} if intent_id else None,
            json_body=payload,
        )
        return self._parse_intent(response)

    def update_intent(
        self,
        intent_name: str,
        updates: dict[str, object],
        update_mask: list[str] | None = None,
    ) -> CxIntent:
        """Patch an intent."""

        payload = dict(updates)
        payload.setdefault("name", intent_name)
        response = self._request_json(
            "PATCH",
            intent_name,
            location=self._location_from_name(intent_name),
            params={"updateMask": ",".join(update_mask)} if update_mask else None,
            json_body=payload,
        )
        return self._parse_intent(response)

    def list_entity_types(self, agent_name: str) -> list[CxEntityType]:
        """List entity types for an agent."""

        items = self._iterate_pages(
            f"{agent_name}/entityTypes",
            item_key="entityTypes",
            location=self._location_from_name(agent_name),
        )
        return [self._parse_entity_type(item) for item in items]

    def create_entity_type(
        self,
        parent: str,
        payload: dict[str, object],
        entity_type_id: str | None = None,
    ) -> CxEntityType:
        """Create an entity type under an agent."""

        response = self._request_json(
            "POST",
            f"{parent}/entityTypes",
            location=self._location_from_name(parent),
            params={"entityTypeId": entity_type_id} if entity_type_id else None,
            json_body=payload,
        )
        return self._parse_entity_type(response)

    def update_entity_type(
        self,
        entity_type_name: str,
        updates: dict[str, object],
        update_mask: list[str] | None = None,
    ) -> CxEntityType:
        """Patch an entity type."""

        payload = dict(updates)
        payload.setdefault("name", entity_type_name)
        response = self._request_json(
            "PATCH",
            entity_type_name,
            location=self._location_from_name(entity_type_name),
            params={"updateMask": ",".join(update_mask)} if update_mask else None,
            json_body=payload,
        )
        return self._parse_entity_type(response)

    def list_webhooks(self, agent_name: str) -> list[CxWebhook]:
        """List webhooks for an agent."""

        items = self._iterate_pages(
            f"{agent_name}/webhooks",
            item_key="webhooks",
            location=self._location_from_name(agent_name),
        )
        return [self._parse_webhook(item) for item in items]

    def create_webhook(
        self,
        parent: str,
        payload: dict[str, object],
        webhook_id: str | None = None,
    ) -> CxWebhook:
        """Create a webhook under an agent."""

        response = self._request_json(
            "POST",
            f"{parent}/webhooks",
            location=self._location_from_name(parent),
            params={"webhookId": webhook_id} if webhook_id else None,
            json_body=payload,
        )
        return self._parse_webhook(response)

    def update_webhook(
        self,
        webhook_name: str,
        updates: dict[str, object],
        update_mask: list[str] | None = None,
    ) -> CxWebhook:
        """Patch a webhook."""

        payload = dict(updates)
        payload.setdefault("name", webhook_name)
        response = self._request_json(
            "PATCH",
            webhook_name,
            location=self._location_from_name(webhook_name),
            params={"updateMask": ",".join(update_mask)} if update_mask else None,
            json_body=payload,
        )
        return self._parse_webhook(response)

    def list_playbooks(self, agent_name: str) -> list[CxPlaybook]:
        """List playbooks for an agent."""

        items = self._iterate_pages(
            f"{agent_name}/playbooks",
            item_key="playbooks",
            location=self._location_from_name(agent_name),
        )
        return [self._parse_playbook(item) for item in items]

    def create_playbook(
        self,
        parent: str,
        payload: dict[str, object],
        playbook_id: str | None = None,
    ) -> CxPlaybook:
        """Create a playbook under an agent."""

        response = self._request_json(
            "POST",
            f"{parent}/playbooks",
            location=self._location_from_name(parent),
            params={"playbookId": playbook_id} if playbook_id else None,
            json_body=payload,
        )
        return self._parse_playbook(response)

    def update_playbook(
        self,
        playbook_name: str,
        updates: dict[str, object],
        update_mask: list[str] | None = None,
    ) -> CxPlaybook:
        """Patch a playbook."""

        payload = dict(updates)
        payload.setdefault("name", playbook_name)
        response = self._request_json(
            "PATCH",
            playbook_name,
            location=self._location_from_name(playbook_name),
            params={"updateMask": ",".join(update_mask)} if update_mask else None,
            json_body=payload,
        )
        return self._parse_playbook(response)

    def list_test_cases(self, agent_name: str) -> list[CxTestCase]:
        """List test cases for an agent."""

        items = self._iterate_pages(
            f"{agent_name}/testCases",
            item_key="testCases",
            location=self._location_from_name(agent_name),
        )
        return [self._parse_test_case(item) for item in items]

    def list_environments(self, agent_name: str) -> list[CxEnvironment]:
        """List environments for an agent."""

        items = self._iterate_pages(
            f"{agent_name}/environments",
            item_key="environments",
            location=self._location_from_name(agent_name),
        )
        return [self._parse_environment(item) for item in items]

    def fetch_snapshot(self, agent_name: str) -> CxAgentSnapshot:
        """Fetch a point-in-time snapshot of an agent and its managed resources."""

        agent = self.get_agent(agent_name)
        flows = self.list_flows(agent_name)
        for flow in flows:
            flow.pages = self.list_pages(flow.name)

        return CxAgentSnapshot(
            agent=agent,
            flows=flows,
            intents=self.list_intents(agent_name),
            entity_types=self.list_entity_types(agent_name),
            webhooks=self.list_webhooks(agent_name),
            playbooks=self.list_playbooks(agent_name),
            test_cases=self.list_test_cases(agent_name),
            environments=self.list_environments(agent_name),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _location_from_name(resource_name: str) -> str:
        """Extract a GCP location from a full resource name."""

        parts = resource_name.split("/")
        try:
            index = parts.index("locations")
            return parts[index + 1]
        except (ValueError, IndexError):
            return "global"

    @staticmethod
    def _parse_agent(item: dict[str, Any]) -> CxAgent:
        """Parse a raw agent payload into a typed model."""

        return CxAgent(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            default_language_code=item.get("defaultLanguageCode", "en"),
            description=item.get("description", ""),
            time_zone=item.get("timeZone", ""),
            start_flow=item.get("startFlow", ""),
            generative_settings=item.get("generativeSettings", {}),
            speech_to_text_settings=item.get("speechToTextSettings", {}),
            text_to_speech_settings=item.get("textToSpeechSettings", {}),
            raw=dict(item),
        )

    def _parse_flow(self, item: dict[str, Any]) -> CxFlow:
        """Parse a raw flow payload into a typed model."""

        pages = [self._parse_page(page) for page in item.get("pages", [])]
        return CxFlow(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            description=item.get("description", ""),
            transition_routes=item.get("transitionRoutes", []),
            event_handlers=item.get("eventHandlers", []),
            pages=pages,
            raw=dict(item),
        )

    @staticmethod
    def _parse_page(item: dict[str, Any]) -> CxPage:
        """Parse a raw page payload into a typed model."""

        return CxPage(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            entry_fulfillment=item.get("entryFulfillment", {}),
            form=item.get("form", {}),
            transition_routes=item.get("transitionRoutes", []),
            event_handlers=item.get("eventHandlers", []),
            raw=dict(item),
        )

    @staticmethod
    def _parse_intent(item: dict[str, Any]) -> CxIntent:
        """Parse a raw intent payload into a typed model."""

        return CxIntent(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            description=item.get("description", ""),
            training_phrases=item.get("trainingPhrases", []),
            parameters=item.get("parameters", []),
            labels=item.get("labels", {}),
            raw=dict(item),
        )

    @staticmethod
    def _parse_entity_type(item: dict[str, Any]) -> CxEntityType:
        """Parse a raw entity type payload into a typed model."""

        return CxEntityType(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            kind=item.get("kind", ""),
            auto_expansion_mode=item.get("autoExpansionMode", ""),
            entities=item.get("entities", []),
            excluded_phrases=item.get("excludedPhrases", []),
            raw=dict(item),
        )

    @staticmethod
    def _parse_webhook(item: dict[str, Any]) -> CxWebhook:
        """Parse a raw webhook payload into a typed model."""

        timeout = item.get("timeout", {})
        timeout_seconds = 30
        if isinstance(timeout, str) and timeout.endswith("s"):
            try:
                timeout_seconds = int(float(timeout[:-1]))
            except ValueError:
                timeout_seconds = 30
        elif isinstance(timeout, (int, float)):
            timeout_seconds = int(timeout)

        return CxWebhook(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            generic_web_service=item.get("genericWebService", {}),
            service_directory=item.get("serviceDirectory", {}),
            timeout_seconds=timeout_seconds,
            disabled=bool(item.get("disabled", False)),
            raw=dict(item),
        )

    @staticmethod
    def _parse_playbook(item: dict[str, Any]) -> CxPlaybook:
        """Parse a raw playbook payload into a typed model."""

        instruction = item.get("instruction", {})
        if isinstance(instruction, str):
            instruction_text = instruction
            instructions = [instruction] if instruction else []
        else:
            instruction_text = instruction.get("text", "") or instruction.get("goal", "")
            instructions = instruction.get("steps", [])

        return CxPlaybook(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            instruction=instruction_text,
            instructions=instructions,
            goal=item.get("goal", ""),
            steps=item.get("steps", []),
            examples=item.get("examples", []),
            raw=dict(item),
        )

    @staticmethod
    def _parse_test_case(item: dict[str, Any]) -> CxTestCase:
        """Parse a raw test case payload into a typed model."""

        return CxTestCase(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            tags=item.get("tags", []),
            conversation_turns=item.get("testCaseConversationTurns", item.get("conversationTurns", [])),
            expected_output=item.get("lastTestResult", item.get("expectedOutput", {})),
            raw=dict(item),
        )

    @staticmethod
    def _parse_environment(item: dict[str, Any]) -> CxEnvironment:
        """Parse a raw environment payload into a typed model."""

        return CxEnvironment(
            name=item.get("name", ""),
            display_name=item.get("displayName", ""),
            description=item.get("description", ""),
            version_configs=item.get("versionConfigs", []),
            raw=dict(item),
        )
