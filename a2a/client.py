"""A2A protocol client — discover and invoke remote A2A-compatible agents.

Uses only the stdlib (urllib.request / urllib.parse / json) so the package
remains dependency-free.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterator, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from a2a.types import A2ATask, AgentCard, TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_jsonrpc(method: str, params: dict[str, Any], request_id: str) -> bytes:
    """Serialise a JSON-RPC 2.0 request to bytes."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": request_id,
    }
    return json.dumps(payload).encode("utf-8")


def _agent_card_url(base_url: str) -> str:
    """Construct the /.well-known/agent-card.json URL from a base URL."""
    parsed = urlparse(base_url.rstrip("/"))
    root = f"{parsed.scheme}://{parsed.netloc}"
    return urljoin(root, "/.well-known/agent-card.json")


def _tasks_url(base_url: str) -> str:
    """Construct the /api/a2a/tasks/send URL from a base URL."""
    return base_url.rstrip("/") + "/api/a2a/tasks/send"


def _task_status_url(base_url: str, task_id: str) -> str:
    return base_url.rstrip("/") + f"/api/a2a/tasks/{task_id}"


def _task_cancel_url(base_url: str, task_id: str) -> str:
    return base_url.rstrip("/") + f"/api/a2a/tasks/{task_id}/cancel"


def _stream_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/a2a/tasks/stream"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class A2AClient:
    """HTTP client for discovering and invoking remote A2A agents.

    Uses only ``urllib.request`` — no third-party dependencies.

    Args:
        timeout_seconds: Per-request socket timeout in seconds (default 30).
    """

    def __init__(self, timeout_seconds: int = 30) -> None:
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, url: str) -> AgentCard:
        """Fetch and parse the agent card at ``/.well-known/agent-card.json``.

        Args:
            url: Base URL of the remote agent (scheme + host, e.g.
                 ``https://agent.example.com``).  The well-known path is
                 derived automatically.

        Returns:
            Parsed AgentCard.

        Raises:
            ValueError: If the response cannot be parsed as an AgentCard.
            URLError: On network failure.
        """
        card_url = _agent_card_url(url)
        data = self._get_json(card_url)
        try:
            return AgentCard.from_dict(data)
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Could not parse agent card from {card_url}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Task submission
    # ------------------------------------------------------------------

    def send_task(
        self,
        url: str,
        message: str,
        skill_id: Optional[str] = None,
    ) -> A2ATask:
        """Submit a task to a remote agent.

        Args:
            url: Base URL of the remote agent.
            message: Plain-text input message.
            skill_id: Optional skill identifier to route the task.

        Returns:
            The A2ATask returned by the remote server.
        """
        params: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": message}],
            }
        }
        if skill_id is not None:
            params["skillId"] = skill_id

        body = _build_jsonrpc(
            method="tasks/send",
            params=params,
            request_id=uuid.uuid4().hex,
        )
        response = self._post_json(_tasks_url(url), body)
        return self._parse_task(response, url)

    # ------------------------------------------------------------------
    # Task retrieval / cancel
    # ------------------------------------------------------------------

    def get_task_status(self, url: str, task_id: str) -> A2ATask:
        """Retrieve the current status of a remote task.

        Args:
            url: Base URL of the remote agent.
            task_id: Task identifier returned by :meth:`send_task`.

        Returns:
            Current A2ATask state.
        """
        data = self._get_json(_task_status_url(url, task_id))
        return self._parse_task(data, url)

    def cancel_task(self, url: str, task_id: str) -> A2ATask:
        """Request cancellation of a remote task.

        Args:
            url: Base URL of the remote agent.
            task_id: Task identifier to cancel.

        Returns:
            Updated A2ATask with CANCELED status (if the server accepted).
        """
        cancel_url = _task_cancel_url(url, task_id)
        body = json.dumps({}).encode("utf-8")
        data = self._post_json(cancel_url, body)
        return self._parse_task(data, url)

    # ------------------------------------------------------------------
    # Streaming (SSE)
    # ------------------------------------------------------------------

    def stream_task(self, url: str, message: str) -> Iterator[dict[str, Any]]:
        """Submit a task and yield Server-Sent Events as they arrive.

        The remote endpoint must support SSE (``text/event-stream``).
        Each yielded item is a parsed JSON dict representing one SSE event.

        Args:
            url: Base URL of the remote agent.
            message: Plain-text input message.

        Yields:
            Parsed event dicts, e.g. ``{"event": "status", "data": {...}}``.
        """
        params: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": message}],
            }
        }
        body = _build_jsonrpc(
            method="tasks/stream",
            params=params,
            request_id=uuid.uuid4().hex,
        )

        req = Request(
            _stream_url(url),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=self._timeout) as response:
                yield from self._parse_sse(response)
        except (HTTPError, URLError) as exc:
            raise ConnectionError(
                f"SSE stream failed for {url}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _get_json(self, url: str) -> dict[str, Any]:
        """Perform a GET request and return the parsed JSON body."""
        req = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(req, timeout=self._timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raise ConnectionError(
                f"GET {url} returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except URLError as exc:
            raise ConnectionError(f"GET {url} failed: {exc.reason}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON from GET {url}: {exc}"
            ) from exc

    def _post_json(self, url: str, body: bytes) -> dict[str, Any]:
        """Perform a POST request with a JSON body and return parsed JSON."""
        req = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=self._timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raise ConnectionError(
                f"POST {url} returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except URLError as exc:
            raise ConnectionError(f"POST {url} failed: {exc.reason}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON from POST {url}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Response parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_task(data: dict[str, Any], _url: str) -> A2ATask:
        """Parse a task dict into an A2ATask.

        Handles both direct task dicts and JSON-RPC result wrappers.
        """
        # JSON-RPC wrapper: {"jsonrpc": "2.0", "result": {...}, "id": "..."}
        if "result" in data and isinstance(data["result"], dict):
            data = data["result"]
        try:
            return A2ATask.from_dict(data)
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Could not parse A2ATask from response: {exc}") from exc

    @staticmethod
    def _parse_sse(response: Any) -> Iterator[dict[str, Any]]:
        """Parse raw SSE bytes from an HTTP response object.

        Yields one dict per complete SSE event.
        """
        event_type: str = "message"
        data_lines: list[str] = []

        for raw_line in response:
            line: str
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8").rstrip("\n\r")
            else:
                line = str(raw_line).rstrip("\n\r")

            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
            elif line == "":
                # Blank line signals end of one event
                if data_lines:
                    raw_data = "\n".join(data_lines)
                    try:
                        parsed = json.loads(raw_data)
                    except json.JSONDecodeError:
                        parsed = {"raw": raw_data}
                    yield {"event": event_type, "data": parsed}
                event_type = "message"
                data_lines = []
