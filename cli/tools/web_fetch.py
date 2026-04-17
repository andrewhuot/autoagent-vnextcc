"""WebFetchTool — retrieve a URL's body over HTTP(S).

Used by the LLM loop when the user asks for documentation, a GitHub file,
or any URL-addressable resource. We intentionally gate network access
through the permission layer: even though a fetch is side-effect-free on
the workspace, it can leak intent (e.g. hitting an attacker-controlled URL
planted in a prompt-injected file), so :meth:`permission_action` scopes
approvals per host.

Design notes:

* Stdlib-only. ``urllib.request`` is sufficient for the Phase-F.4 contract
  and keeps the tool free of new ``pyproject.toml`` entries.
* The body is capped at 100k characters. Very large responses are
  truncated rather than failing, so the LLM can still reason about the
  head of a long page.
* HTML is naively stripped to text with a regex cleaner. This is *not* a
  full parser; it keeps the tool reliable without the ``lxml``/``bs4``
  dependency. If we ever need structured extraction we will move to a
  proper parser.
* Known secret shapes (OpenAI keys, Anthropic keys, GitHub PATs) are
  redacted before returning — a fetched page that echoes back an env var
  should never widen the blast radius.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cli.tools.base import Tool, ToolContext, ToolResult


DEFAULT_TIMEOUT_SECONDS = 15
MAX_BODY_CHARS = 100_000

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_MULTIBLANK_RE = re.compile(r"\n{3,}")

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"OPENAI_API_KEY\s*=\s*\S+"), "OPENAI_API_KEY=[REDACTED]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "[REDACTED:anthropic-key]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]+"), "[REDACTED:github-pat]"),
)


class WebFetchTool(Tool):
    """Fetch the body of an HTTP(S) URL."""

    name = "WebFetch"
    description = (
        "Fetch the body of an http(s) URL. Returns plain text (HTML is "
        "stripped of tags). The response is truncated to 100 000 characters "
        "and known secret patterns are redacted. Use for reading docs, "
        "GitHub files, or any URL-addressable resource."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Absolute http(s) URL to fetch.",
            },
            "prompt": {
                "type": "string",
                "description": "Optional hint for future summarisation; "
                "ignored by the current fetcher.",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }
    read_only = False
    is_concurrency_safe = True

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        url = str(tool_input.get("url") or "")
        host = ""
        try:
            host = urlparse(url).hostname or ""
        except ValueError:
            host = ""
        return f"tool:WebFetch:{host}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        url = str(tool_input.get("url", ""))
        return f"WebFetch {url[:200]}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        url = str(tool_input.get("url") or "").strip()
        if not url:
            return ToolResult.failure("WebFetch requires a 'url'.")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult.failure(
                f"WebFetch only supports http(s) URLs; got scheme '{parsed.scheme}'."
            )
        if not parsed.hostname:
            return ToolResult.failure(f"WebFetch could not parse host from '{url}'.")

        request = Request(url, headers={"User-Agent": "agentlab-webfetch/1.0"})
        try:
            with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                content_type = (response.headers.get("Content-Type") or "").lower()
                raw = response.read()
        except URLError as exc:
            return ToolResult.failure(f"Fetch failed: {exc}")
        except TimeoutError as exc:
            return ToolResult.failure(f"Fetch failed: {exc}")
        except OSError as exc:
            # urllib occasionally surfaces non-URLError OSError for DNS/TLS.
            return ToolResult.failure(f"Fetch failed: {exc}")

        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if "html" in content_type or _looks_like_html(text):
            text = _strip_html(text)
        text = _redact_secrets(text)

        truncated = len(text) > MAX_BODY_CHARS
        if truncated:
            text = text[:MAX_BODY_CHARS] + "\n[... truncated ...]"

        return ToolResult(
            ok=True,
            content=text,
            metadata={
                "url": url,
                "host": parsed.hostname,
                "content_type": content_type,
                "truncated": truncated,
            },
        )


def _looks_like_html(text: str) -> bool:
    head = text[:1024].lstrip().lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def _strip_html(text: str) -> str:
    no_script = _HTML_SCRIPT_STYLE_RE.sub(" ", text)
    no_tags = _HTML_TAG_RE.sub(" ", no_script)
    collapsed = _WHITESPACE_RE.sub(" ", no_tags)
    return _MULTIBLANK_RE.sub("\n\n", collapsed).strip()


def _redact_secrets(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
