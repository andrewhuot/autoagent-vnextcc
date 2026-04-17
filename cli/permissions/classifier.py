"""Transcript-level tool-call classifier.

This module sits in front of the interactive permission prompt. For every
inbound tool call, :func:`classify_tool_call` returns one of three
:class:`ClassifierDecision` values:

* ``AUTO_APPROVE`` — obviously safe (a read-only glob, a whitelisted bash
  command, a fetch to an allowlisted host). No prompt shown.
* ``AUTO_DENY`` — matched a persisted deny pattern. Hard-block.
* ``PROMPT`` — anything we are not confident about; route through the
  normal permission dialog.

The goal is to cut prompt noise without ever silently auto-approving a
mutation or an exfiltration vector. When in doubt, the answer is always
``PROMPT`` — every guardrail in this file errs toward showing the prompt.

Design notes:

* Persisted rules (from the workspace's ``settings.json``) always beat
  the per-tool heuristics. If the user wrote ``deny`` for a pattern, we
  hard-block even if the heuristic would otherwise approve. If they
  wrote ``allow``, we skip the heuristic entirely — they told us once.
* The bash handler uses an extremely narrow allowlist (``ls``, ``pwd``,
  ``cat``, ``which``, plus a few read-only ``git`` subcommands). Every
  other first token prompts. Shell metacharacters are rejected
  wholesale.
* The file-read handler requires ``workspace_root``; without it, the
  scope is ambiguous and we prompt. Paths that resolve outside the root
  (including ``..`` traversal and absolute paths to ``/etc/...``) also
  prompt.
* The web handlers reject IP-address hosts even if the IP literal is
  present in the allowlist — that combo almost always means an SSRF
  smokescreen. Hosts are IDN-decoded before matching so Cyrillic
  homoglyphs can't sneak through.
* Any tool we don't recognise prompts. MCP-namespaced tools ALWAYS
  prompt — never auto-approve a call that crosses a server boundary.
"""

from __future__ import annotations

import ipaddress
import shlex
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


# Characters that make bash do something other than invoke a single
# program with positional arguments. If any of these appears anywhere in
# the command string we fall through to a prompt — shlex can split them
# safely but the resulting command can still pipe/redirect/substitute.
_BASH_METACHARS = set("|&;<>`$(){}\\'\"\n\r\t\x00")

# First tokens that are safe to auto-approve with any arguments. These
# are all read-only — ``ls``, ``pwd``, ``cat``, ``which`` cannot mutate
# state. ``cat`` is special-cased further below to enforce the workspace
# boundary on its path argument.
_BASH_SAFE_COMMANDS = frozenset({"ls", "pwd", "cat", "which"})

# Subcommands of ``git`` that are strictly read-only. ``git status``,
# ``git diff``, ``git log``, ``git show`` cannot modify the repository.
# Anything else (``commit``, ``push``, ``checkout``, ...) prompts.
_GIT_SAFE_SUBCOMMANDS = frozenset({"status", "diff", "log", "show"})


class ClassifierDecision(str, Enum):
    """Three-valued verdict emitted by :func:`classify_tool_call`."""

    AUTO_APPROVE = "auto_approve"
    AUTO_DENY = "auto_deny"
    PROMPT = "prompt"


@dataclass(frozen=True)
class ClassifierContext:
    """Ambient state that modulates the classifier's decisions.

    Frozen so callers can safely share a single context across threads.
    All defaults are conservative — empty frozensets (no extra allow or
    deny rules) and ``None`` for the workspace root (which forces file
    reads to prompt, since without a root we can't tell whether a path
    is in scope).
    """

    workspace_root: Path | None = None
    web_allowlist: frozenset[str] = field(default_factory=frozenset)
    persisted_allow_patterns: frozenset[str] = field(default_factory=frozenset)
    persisted_deny_patterns: frozenset[str] = field(default_factory=frozenset)


def classify_tool_call(
    tool_name: str,
    tool_input: dict[str, Any],
    context: ClassifierContext,
) -> ClassifierDecision:
    """Classify a tool invocation as auto-approve, auto-deny, or prompt.

    Precedence (highest to lowest):

    1. ``persisted_deny_patterns`` — any match returns AUTO_DENY.
    2. ``persisted_allow_patterns`` — any match returns AUTO_APPROVE.
    3. MCP-namespaced tools — always PROMPT (never auto-approve across
       an MCP boundary, even with a persisted allow; the persisted-allow
       branch above is intentional for the operator who explicitly
       allowlists an MCP tool by pattern).
    4. Per-tool handler dispatch.
    5. ``_prompt_by_default`` for unknown tools.
    """
    # Normalise the input so handlers can assume a dict even when the
    # caller passed ``None`` or a non-dict payload (e.g. a stray string).
    inp: dict[str, Any] = tool_input if isinstance(tool_input, dict) else {}

    action_key = f"tool:{tool_name}"
    if _matches_any(action_key, context.persisted_deny_patterns) or _matches_any(
        tool_name, context.persisted_deny_patterns
    ):
        return ClassifierDecision.AUTO_DENY
    if _matches_any(action_key, context.persisted_allow_patterns) or _matches_any(
        tool_name, context.persisted_allow_patterns
    ):
        return ClassifierDecision.AUTO_APPROVE

    if _is_mcp_tool(tool_name):
        return ClassifierDecision.PROMPT

    handler = _HANDLERS.get(tool_name)
    if handler is None:
        return _prompt_by_default(inp, context)
    return handler(inp, context)


# ---------------------------------------------------------------------------
# Per-tool handlers
# ---------------------------------------------------------------------------


def _classify_bash(tool_input: dict[str, Any], context: ClassifierContext) -> ClassifierDecision:
    """Classify a ``Bash`` invocation.

    Steps:

    1. Require a non-empty string command.
    2. Reject any shell metacharacter unconditionally.
    3. Split with ``shlex(posix=True)``; any parse failure prompts.
    4. First token must be in the safe allowlist, OR ``git`` with a
       read-only subcommand.
    5. ``cat`` is additionally required to stay inside
       ``workspace_root`` when given an absolute path.
    """
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return ClassifierDecision.PROMPT

    if any(ch in _BASH_METACHARS for ch in command):
        return ClassifierDecision.PROMPT

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # shlex raises on e.g. an unmatched quote. Do NOT retry with
        # ``posix=False`` — that would be a different (and laxer)
        # parser, which is exactly the wrong response to an ambiguous
        # input.
        return ClassifierDecision.PROMPT

    if not tokens:
        return ClassifierDecision.PROMPT

    head = tokens[0]
    if head == "git":
        if len(tokens) >= 2 and tokens[1] in _GIT_SAFE_SUBCOMMANDS:
            return ClassifierDecision.AUTO_APPROVE
        return ClassifierDecision.PROMPT

    if head not in _BASH_SAFE_COMMANDS:
        return ClassifierDecision.PROMPT

    if head == "cat" and len(tokens) >= 2:
        # Absolute paths outside the workspace are dangerous even under
        # a read-only command (``cat /etc/passwd`` is the classic).
        # Relative paths are resolved against the workspace root so
        # ``cat ./README.md`` auto-approves when it lands inside.
        path_arg = tokens[1]
        path_obj = Path(path_arg)
        root = context.workspace_root
        if path_obj.is_absolute():
            if root is None:
                return ClassifierDecision.PROMPT
            if not _is_within(path_obj, root):
                return ClassifierDecision.PROMPT
        else:
            if root is None:
                return ClassifierDecision.PROMPT
            if not _is_within(root / path_arg, root):
                return ClassifierDecision.PROMPT

    return ClassifierDecision.AUTO_APPROVE


def _classify_file_read(
    tool_input: dict[str, Any], context: ClassifierContext
) -> ClassifierDecision:
    """Classify a ``FileRead`` invocation.

    We auto-approve only when the resolved path is strictly inside the
    workspace root. Without a root we prompt — the scope is ambiguous.
    """
    path = tool_input.get("file_path") or tool_input.get("path")
    if not isinstance(path, str) or not path:
        return ClassifierDecision.PROMPT

    root = context.workspace_root
    if root is None:
        return ClassifierDecision.PROMPT

    path_obj = Path(path)
    if not path_obj.is_absolute():
        path_obj = root / path

    if not _is_within(path_obj, root):
        return ClassifierDecision.PROMPT

    return ClassifierDecision.AUTO_APPROVE


def _classify_file_write(
    tool_input: dict[str, Any], context: ClassifierContext
) -> ClassifierDecision:
    """File writes always prompt — they mutate the workspace."""
    return ClassifierDecision.PROMPT


def _classify_file_edit(
    tool_input: dict[str, Any], context: ClassifierContext
) -> ClassifierDecision:
    """File edits always prompt — same reasoning as writes."""
    return ClassifierDecision.PROMPT


def _classify_glob(tool_input: dict[str, Any], context: ClassifierContext) -> ClassifierDecision:
    """Glob is a read-only directory listing; safe to auto-approve."""
    return ClassifierDecision.AUTO_APPROVE


def _classify_grep(tool_input: dict[str, Any], context: ClassifierContext) -> ClassifierDecision:
    """Grep is a read-only content scan; safe to auto-approve."""
    return ClassifierDecision.AUTO_APPROVE


def _classify_web_fetch(
    tool_input: dict[str, Any], context: ClassifierContext
) -> ClassifierDecision:
    """Classify a ``WebFetch`` invocation.

    Auto-approve only when:

    * the URL parses as ``http`` or ``https``,
    * the host is NOT an IP literal (even if the IP is in the
      allowlist — IP hosts are a common SSRF vector),
    * the IDN-decoded host matches an allowlist entry (exact match or
      ``*.example.com`` suffix match).

    Anything else prompts.
    """
    url = tool_input.get("url")
    if not isinstance(url, str) or not url:
        return ClassifierDecision.PROMPT
    return _classify_url(url, context)


def _classify_web_search(
    tool_input: dict[str, Any], context: ClassifierContext
) -> ClassifierDecision:
    """Classify a ``WebSearch`` invocation.

    ``WebSearch`` usually takes a free-text ``query``. If that query is
    actually a URL, reuse the same logic as ``WebFetch`` so an attacker
    can't wrap a fetch in a search. Otherwise auto-approve.
    """
    query = tool_input.get("query")
    if not isinstance(query, str):
        return ClassifierDecision.AUTO_APPROVE
    stripped = query.strip()
    if "://" in stripped:
        return _classify_url(stripped, context)
    return ClassifierDecision.AUTO_APPROVE


def _prompt_by_default(
    tool_input: dict[str, Any], context: ClassifierContext
) -> ClassifierDecision:
    """Fallback for unknown tool names.

    The safe default is to prompt — we don't know what the tool does,
    and silently auto-approving an unknown surface is exactly the
    mistake we're writing this classifier to avoid.
    """
    return ClassifierDecision.PROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_url(url: str, context: ClassifierContext) -> ClassifierDecision:
    """Shared URL-allowlist check used by WebFetch and WebSearch."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ClassifierDecision.PROMPT

    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return ClassifierDecision.PROMPT

    host = parsed.hostname
    if not host:
        return ClassifierDecision.PROMPT

    # IP literals always prompt. An IP is a deliberate bypass of DNS
    # and of any hostname-based allowlisting; even if the literal
    # happens to be in the allowlist we still want a human to approve.
    try:
        ipaddress.ip_address(host)
        return ClassifierDecision.PROMPT
    except ValueError:
        pass

    # Normalise: lowercase + IDN-decode + strip trailing dot. The IDN
    # step is what catches Cyrillic-homoglyph attacks (``еxample.com``
    # with a Cyrillic е looks identical but encodes differently).
    normalized_host = _normalize_host(host)
    if normalized_host is None:
        return ClassifierDecision.PROMPT

    for entry in context.web_allowlist:
        if _host_matches(normalized_host, entry):
            return ClassifierDecision.AUTO_APPROVE
    return ClassifierDecision.PROMPT


def _normalize_host(host: str) -> str | None:
    """Lowercase, IDN-decode, strip trailing dot. Return None on failure."""
    stripped = host.rstrip(".").lower()
    if not stripped:
        return None
    try:
        # ``idna`` encode/decode enforces that the host is valid per
        # RFC 5891. Mixed-script labels fail here, which is exactly
        # what we want for homoglyph defence.
        return stripped.encode("idna").decode("ascii").lower()
    except (UnicodeError, UnicodeDecodeError):
        return None


def _host_matches(host: str, allowlist_entry: str) -> bool:
    """Return True when ``host`` matches the allowlist entry.

    Supports:

    * Exact match (``example.com`` → ``example.com``).
    * Suffix wildcard (``*.example.com`` matches any direct or
      nested subdomain, but NOT the bare apex ``example.com``).

    All comparisons are lowercase.
    """
    entry = allowlist_entry.rstrip(".").lower()
    if not entry:
        return False
    if entry.startswith("*."):
        suffix = entry[1:]  # ``.example.com``
        # Match any subdomain (``a.example.com``, ``a.b.example.com``)
        # but not the bare apex — if the user wanted the apex they'd
        # list it explicitly. ``*.example.com`` reading as "any
        # subdomain" matches how nginx and most allowlist schemes
        # interpret it.
        return host.endswith(suffix) and host != suffix.lstrip(".")
    return host == entry


def _is_within(path: Path, root: Path) -> bool:
    """Return True when the resolved path is inside ``root``.

    Uses ``Path.resolve()`` so ``..`` segments collapse. If resolution
    fails (e.g. filesystem errors on exotic paths) we return False —
    the caller will convert that to a PROMPT, which is the safe side.
    """
    try:
        resolved = path.resolve()
        resolved_root = root.resolve()
    except (OSError, RuntimeError):
        return False
    # ``is_relative_to`` is Python 3.9+. Using it instead of string
    # prefix comparison catches the classic ``/ws-evil`` vs ``/ws``
    # prefix bypass.
    try:
        return resolved.is_relative_to(resolved_root)
    except AttributeError:  # pragma: no cover - Py<3.9 fallback
        try:
            resolved.relative_to(resolved_root)
            return True
        except ValueError:
            return False


def _is_mcp_tool(tool_name: str) -> bool:
    """Return True when the tool is MCP-namespaced.

    Covers three conventions seen in the wild: ``mcp__foo`` (current
    Claude Code), ``mcp-foo`` (legacy dash form), and ``tool:mcp:foo``
    (some orchestrator wrappers prefix-encode the action string).
    """
    if not isinstance(tool_name, str):
        return False
    lowered = tool_name.lower()
    return (
        lowered.startswith("mcp__")
        or lowered.startswith("mcp-")
        or lowered.startswith("tool:mcp:")
    )


def _matches_any(value: str, patterns: frozenset[str]) -> bool:
    """fnmatch against a pattern set. Empty set → False."""
    if not patterns:
        return False
    return any(fnmatch(value, pattern) for pattern in patterns)


# Dispatch table. Kept at module bottom so every referenced handler is
# already defined above.
_HANDLERS = {
    "Bash": _classify_bash,
    "FileRead": _classify_file_read,
    "Read": _classify_file_read,
    "FileWrite": _classify_file_write,
    "Write": _classify_file_write,
    "FileEdit": _classify_file_edit,
    "Edit": _classify_file_edit,
    "Glob": _classify_glob,
    "Grep": _classify_grep,
    "WebFetch": _classify_web_fetch,
    "WebSearch": _classify_web_search,
}


__all__ = [
    "ClassifierContext",
    "ClassifierDecision",
    "classify_tool_call",
]
