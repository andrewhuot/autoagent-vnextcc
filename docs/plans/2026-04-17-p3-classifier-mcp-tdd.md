# P3 — Permission classifier + MCP transports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task below ships as one failing test → minimal impl → passing test → conventional commit. One task per subagent. Verify the repo-wide suite green after every merge-back.

**Goal.** Reduce permission-prompt noise on obviously-safe tool calls (classifier + denial tracking + audit log), and let AgentLab talk to hosted MCP servers (SSE + HTTP transports with reconnect).

**Architecture.** Two independent slices sharing only `cli/permissions.py` (existing `PermissionManager.persist_allow_rule`) and `cli/workbench_app/tool_permissions.py` (existing `PermissionTable`).

- **Slice A — Transcript classifier.** New `cli/permissions/` subpackage (`classifier.py`, `denial_tracking.py`, `audit_log.py`). Heuristic `classify_tool_call(tool_name, tool_input, context) -> ClassifierDecision` returns `AUTO_APPROVE | AUTO_DENY | PROMPT`. Defaults to PROMPT on ambiguity. Bash allowlist is tiny (`ls`, `pwd`, `git status`, `git diff`, `git log`, `git show`, `cat`, `which`). Writes NEVER auto-approve. Denial tracker stops auto-approving a tool family after N user denials in a session. Every auto-approve appends a line to `.agentlab/permission_audit.log` (JSONL). Rotates at 10 MB. Dialog gains "save as rule" that calls the existing `PermissionManager.persist_allow_rule`. `/doctor` gets a classifier section.
- **Slice B — MCP SSE + HTTP transports.** New `cli/mcp/transports/` package with `Transport` Protocol (`connect/close/send/receive/is_connected`). Extract existing stdio client (the one that's constructed behind `McpClientFactory` in `cli/tools/mcp_bridge.py`) into `cli/mcp/transports/stdio.py`. Add `sse.py` (`httpx` EventSource long-poll), `http.py` (streamable HTTP — POST per call, SSE server-push). `cli/mcp/reconnect.py` wraps a transport with exponential backoff (1/2/4/8…/60 s), 30 s health-check pings, tool-schema invalidation on reconnect. `.mcp.json` schema accepts `"transport": "stdio" | "sse" | "http"` with either `command + args` (stdio) or `url` (sse/http). Load via P0 settings cascade, validate with pydantic.

**Tech stack.** Python 3.11, `httpx` (already a dep), pyyaml/json, pydantic, pytest. No websockets, no OAuth — both explicitly deferred.

**Test runner.** `/Users/andrew/Desktop/agentlab/.venv/bin/python -m pytest` (the worktree's own `.venv` lacks pytest; the parent venv is where we run tests). Invoke pytest foreground — do not self-start background monitors.

---

## Ground-truth findings

Where the canonical P3 handoff diverges from what's on `master` as of `2f63f08`:

1. **`cli/mcp_runtime.py` does NOT run stdio servers.** It's a config-management layer only (`load_mcp_config`, `save_mcp_config`, CLI subcommands). The actual stdio dispatch lives behind `McpClientFactory` in `cli/tools/mcp_bridge.py`. **Decision:** the new `Transport` lives under `cli/mcp/transports/`; `mcp_bridge.py` gains a new `transport`-aware factory (or `McpClientFactory` subclasses produce transport-wrapped clients). We do NOT rewrite `mcp_runtime.py` into an event loop — it stays as config I/O.
2. **`cli/permissions.py` already persists rules.** `PermissionManager.persist_allow_rule(pattern)` already writes `permissions.rules.allow` to `.agentlab/settings.json` via `update_workspace_settings`. The dialog's new "save as rule" button calls this function directly — no new persistence code needed.
3. **`PermissionTable` (`cli/workbench_app/tool_permissions.py`) is simpler than the handoff implies.** It owns a defaults dict, an overrides dict, and a `check(tool_name)` that raises `PermissionPending`/`PermissionDenied`. It has no workspace root, no classifier reference. **Decision:** the classifier lives OUTSIDE `PermissionTable`. The REPL's permission-resolution path consults the classifier first; if the classifier returns `PROMPT`, the existing `PermissionTable.check` fires. `PermissionTable` stays untouched.
4. **`cli/permissions/` — does not exist.** Free to create. (`cli/permissions.py` the MODULE exists, but Python package + module can coexist — if not, we promote `cli/permissions.py` → `cli/permissions/__init__.py` in a zero-content-change move.)
5. **`cli/mcp/` — does not exist.** Free to create.
6. **`.mcp.json` schema today.** `{"mcpServers": {<name>: {"command": str, "args": [...], "env": {...}}}}`. No `transport` field. **Decision:** treat absence of `transport` as `"stdio"` (backward compat). New `"transport": "sse"` and `"http"` cases require `url`. Pydantic validates via a tagged union.
7. **`httpx` availability** — already imported in `cli/llm/providers/openai_client.py`. Confirmed.
8. **`/doctor` is already extended** (P0 + P0.5). New `classifier_section(manager, tracker, classifier)` is a pure render helper.
9. **`tests/test_system_prompt.py` must stay byte-stable.** No change to `cli/workbench_app/system_prompt.py` in P3. The classifier has zero effect on system prompts.
10. **Existing permission tests.** `tests/test_permissions*.py` must all stay green; the classifier path is strictly additive (consulted BEFORE the existing `PermissionTable.check`, returns `PROMPT` on anything novel). Auto-deny tools never existed before; classifier's `AUTO_DENY` is limited to the same rules `PermissionManager.decision_for` would return `"deny"` for — it's a cheaper path, not a new policy.

---

## Task sequence

Two lanes, parallelisable once the plan commits:

- **Lane A (Slice A) — classifier.** T1 → T2 → T3 → T4 sequential (T3 depends on T1+T2; T4 depends on T3).
- **Lane B (Slice B) — MCP transports.** T5 (transport extraction + protocol) → T6 (SSE) + T7 (HTTP) parallel → T8 (reconnect supervisor) → T9 (config shape + wizard).

Lanes A and B are fully independent — they touch disjoint files. A single agent ships A first (more user impact), then B.

---

### P3.T1 — Classifier rule tables + safety guardrails (Slice A)

**Files.** Create `cli/permissions/__init__.py`, `cli/permissions/classifier.py`, `tests/test_permission_classifier.py`. (If a package vs module name-collision arises with the existing `cli/permissions.py`, promote that module first in a zero-change commit: `git mv cli/permissions.py cli/permissions/__init__.py`.)

**Tests.**

```python
# tests/test_permission_classifier.py
from cli.permissions.classifier import ClassifierDecision, classify_tool_call

def test_bash_allowlist_auto_approves_ls():
    d = classify_tool_call("bash", {"command": "ls"}, _ctx())
    assert d == ClassifierDecision.AUTO_APPROVE

def test_bash_pipeline_prompts():
    d = classify_tool_call("bash", {"command": "ls | grep foo"}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_bash_backticks_prompt():
    d = classify_tool_call("bash", {"command": "echo `whoami`"}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_bash_command_substitution_prompts():
    d = classify_tool_call("bash", {"command": "echo $(whoami)"}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_bash_and_chain_prompts():
    d = classify_tool_call("bash", {"command": "ls && rm -rf /"}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_bash_rm_never_auto_approves():
    d = classify_tool_call("bash", {"command": "rm file"}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_bash_null_byte_prompts():
    d = classify_tool_call("bash", {"command": "ls\x00-la"}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_bash_unknown_binary_prompts():
    d = classify_tool_call("bash", {"command": "curl https://x"}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_file_read_under_workspace_auto_approves():
    d = classify_tool_call("file_read", {"path": "/ws/src/main.py"}, _ctx(workspace_root="/ws"))
    assert d == ClassifierDecision.AUTO_APPROVE

def test_file_read_above_workspace_prompts():
    d = classify_tool_call("file_read", {"path": "/etc/passwd"}, _ctx(workspace_root="/ws"))
    assert d == ClassifierDecision.PROMPT

def test_file_read_symlink_escape_prompts():
    d = classify_tool_call("file_read", {"path": "/ws/../etc/passwd"}, _ctx(workspace_root="/ws"))
    assert d == ClassifierDecision.PROMPT

def test_file_write_always_prompts():
    d = classify_tool_call("file_write", {"path": "/ws/foo.py", "content": "x"}, _ctx(workspace_root="/ws"))
    assert d == ClassifierDecision.PROMPT

def test_file_edit_always_prompts():
    d = classify_tool_call("file_edit", {"path": "/ws/foo.py", "old": "a", "new": "b"}, _ctx(workspace_root="/ws"))
    assert d == ClassifierDecision.PROMPT

def test_glob_auto_approves():
    d = classify_tool_call("glob", {"pattern": "**/*.py"}, _ctx(workspace_root="/ws"))
    assert d == ClassifierDecision.AUTO_APPROVE

def test_grep_auto_approves():
    d = classify_tool_call("grep", {"pattern": "def foo"}, _ctx(workspace_root="/ws"))
    assert d == ClassifierDecision.AUTO_APPROVE

def test_web_fetch_allowlist_auto_approves():
    d = classify_tool_call("web_fetch", {"url": "https://docs.python.org/3/library/os.html"},
                           _ctx(web_allowlist={"docs.python.org"}))
    assert d == ClassifierDecision.AUTO_APPROVE

def test_web_fetch_unlisted_host_prompts():
    d = classify_tool_call("web_fetch", {"url": "https://evil.example.com"},
                           _ctx(web_allowlist={"docs.python.org"}))
    assert d == ClassifierDecision.PROMPT

def test_web_fetch_ip_address_prompts():
    d = classify_tool_call("web_fetch", {"url": "https://192.168.0.1/"}, _ctx(web_allowlist={"192.168.0.1"}))
    assert d == ClassifierDecision.PROMPT  # IPs never auto-approve even if allowlisted literally

def test_web_fetch_homoglyph_prompts():
    # cyrillic 'а' in 'docs.python.оrg' != latin 'a'
    d = classify_tool_call("web_fetch", {"url": "https://docs.python.оrg/"}, _ctx(web_allowlist={"docs.python.org"}))
    assert d == ClassifierDecision.PROMPT

def test_unknown_tool_always_prompts():
    d = classify_tool_call("deploy_prod", {}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_mcp_tool_always_prompts():
    d = classify_tool_call("mcp__notion__create_page", {"title": "x"}, _ctx())
    assert d == ClassifierDecision.PROMPT

def test_persisted_allow_rule_beats_classifier_ambiguity():
    # If the user saved an allow rule, classifier returns AUTO_APPROVE even
    # when heuristics would say PROMPT.
    d = classify_tool_call("deploy_prod", {}, _ctx(persisted_allow_patterns={"deploy_prod"}))
    assert d == ClassifierDecision.AUTO_APPROVE

def test_persisted_deny_rule_forces_auto_deny():
    d = classify_tool_call("bash", {"command": "ls"}, _ctx(persisted_deny_patterns={"bash"}))
    assert d == ClassifierDecision.AUTO_DENY
```

Aim for 50+ total cases. Include table-driven batch tests for the bash allowlist and adversarial inputs per class (metachars, homoglyphs, null bytes, URL-encoded hosts, relative path traversal).

**Minimal impl.**

```python
# cli/permissions/classifier.py
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import shlex

class ClassifierDecision(str, Enum):
    AUTO_APPROVE = "auto_approve"
    AUTO_DENY = "auto_deny"
    PROMPT = "prompt"

@dataclass(frozen=True)
class ClassifierContext:
    workspace_root: Path | None = None
    web_allowlist: frozenset[str] = field(default_factory=frozenset)
    persisted_allow_patterns: frozenset[str] = field(default_factory=frozenset)
    persisted_deny_patterns: frozenset[str] = field(default_factory=frozenset)

_BASH_ALLOWLIST = frozenset({"ls", "pwd", "cat", "which"})
_BASH_ALLOWLIST_GIT = frozenset({"status", "diff", "log", "show"})
_SHELL_METACHARS = set("|&;<>`$(){}\\'\"\n\r\t\x00")

def classify_tool_call(tool_name: str, tool_input: dict[str, Any],
                       context: ClassifierContext) -> ClassifierDecision:
    # 1. Persisted rules beat everything.
    if tool_name in context.persisted_deny_patterns:
        return ClassifierDecision.AUTO_DENY
    if tool_name in context.persisted_allow_patterns:
        return ClassifierDecision.AUTO_APPROVE

    handler = _HANDLERS.get(tool_name, _prompt_by_default)
    return handler(tool_input, context)

def _classify_bash(inp, ctx): ...
def _classify_file_read(inp, ctx): ...
def _classify_file_write(inp, ctx): return ClassifierDecision.PROMPT
def _classify_file_edit(inp, ctx): return ClassifierDecision.PROMPT
def _classify_glob(inp, ctx): return ClassifierDecision.AUTO_APPROVE
def _classify_grep(inp, ctx): return ClassifierDecision.AUTO_APPROVE
def _classify_web_fetch(inp, ctx): ...
def _prompt_by_default(inp, ctx): return ClassifierDecision.PROMPT
```

**Safety guardrails (pin every one with a test):**
- Any character in `_SHELL_METACHARS` appearing in a bash command → PROMPT.
- `shlex.split(..., posix=True)` failure → PROMPT (do NOT retry with `posix=False`).
- First token not in `_BASH_ALLOWLIST` (or `git` with arg-0 in `_BASH_ALLOWLIST_GIT`) → PROMPT.
- `cat` with any absolute path outside `workspace_root` → PROMPT.
- File-read path resolved via `Path(p).resolve()` must be relative-to `workspace_root.resolve()` — otherwise PROMPT (catches `..` traversal, symlinks out).
- URL must parse via `urlparse` with scheme in `{"http", "https"}` — otherwise PROMPT.
- URL host IS an IP address (`ipaddress.ip_address(host)` succeeds) → PROMPT regardless of allowlist.
- Host must match an allowlist entry literally (case-insensitive, ASCII NFC normalised, IDN-decoded). Wildcard matches only if the user prefixed the allowlist entry with `*.`.
- Unknown tool name → PROMPT (never AUTO_APPROVE).

**Commit.**
```
feat(permissions): transcript classifier with bash allowlist + web allowlist + file-read scope
```

**Dependencies.** None.

---

### P3.T2 — Denial tracking (Slice A)

**Files.** Create `cli/permissions/denial_tracking.py`, `tests/test_denial_tracking.py`.

**Tests.**

```python
def test_counter_starts_at_zero():
    t = DenialTracker(max_per_session_per_tool=3)
    assert t.denial_count("bash") == 0
    assert t.should_escalate_to_prompt("bash") is False

def test_counter_advances_and_fires():
    t = DenialTracker(max_per_session_per_tool=3)
    for _ in range(3): t.record_denial("bash")
    assert t.denial_count("bash") == 3
    assert t.should_escalate_to_prompt("bash") is True

def test_per_tool_independence():
    t = DenialTracker(max_per_session_per_tool=3)
    for _ in range(3): t.record_denial("bash")
    assert t.should_escalate_to_prompt("file_read") is False

def test_reset_clears_all_counters():
    t = DenialTracker(max_per_session_per_tool=3)
    for _ in range(3): t.record_denial("bash")
    t.reset()
    assert t.denial_count("bash") == 0

def test_negative_threshold_raises():
    with pytest.raises(ValueError):
        DenialTracker(max_per_session_per_tool=-1)
```

**Minimal impl.**

```python
# cli/permissions/denial_tracking.py
@dataclass
class DenialTracker:
    max_per_session_per_tool: int = 3
    _counts: dict[str, int] = field(default_factory=dict)

    def record_denial(self, tool_name: str) -> None: ...
    def denial_count(self, tool_name: str) -> int: ...
    def should_escalate_to_prompt(self, tool_name: str) -> bool: ...
    def reset(self) -> None: ...
```

In-memory only — no persistence. Session lifetime = DenialTracker instance lifetime.

**Commit.**
```
feat(permissions): denial tracker escalates borderline-safe tools back to prompt after N denials
```

**Dependencies.** None.

---

### P3.T3 — Permission-dialog wiring + "save as rule" (Slice A)

**Files.** Modify `cli/workbench_app/permission_dialog.py`. Modify `cli/workbench_app/tool_permissions.py` ONLY to accept a classifier / tracker reference (minimal — probably a new `check_with_classifier(tool_name, tool_input, context)` helper or a wrapping function in a new module `cli/workbench_app/classifier_gate.py`). Create `tests/test_permission_dialog_save_rule.py`, `tests/test_classifier_gate.py`.

**Tests — gate.**
```python
def test_gate_auto_approves_when_classifier_says_so():
    # ctx lacks persisted rules; bash 'ls' → AUTO_APPROVE
    gate = ClassifierGate(table=PermissionTable(), tracker=DenialTracker(3), context=_ctx())
    assert gate.check("bash", {"command": "ls"}) == "allow"  # no exception raised

def test_gate_falls_through_to_table_on_prompt():
    gate = ClassifierGate(table=PermissionTable(), tracker=DenialTracker(3), context=_ctx())
    with pytest.raises(PermissionPending):
        gate.check("eval_run", {"suite": "x"})  # PermissionTable default is ASK

def test_gate_escalates_after_denials():
    tracker = DenialTracker(max_per_session_per_tool=1)
    tracker.record_denial("bash")
    gate = ClassifierGate(table=PermissionTable(), tracker=tracker, context=_ctx())
    with pytest.raises(PermissionPending):
        gate.check("bash", {"command": "ls"})
```

**Tests — dialog.**
```python
def test_save_as_rule_writes_to_settings(tmp_path):
    mgr = PermissionManager(root=tmp_path)
    (tmp_path / ".agentlab").mkdir()
    save_as_rule_clicked(mgr, pattern="tool:Bash:*")
    reloaded = PermissionManager(root=tmp_path)
    assert "tool:Bash:*" in reloaded.explicit_rules.get("allow", [])
```

**Minimal impl.**

```python
# cli/workbench_app/classifier_gate.py (new)
@dataclass
class ClassifierGate:
    table: PermissionTable
    tracker: DenialTracker
    context: ClassifierContext

    def check(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        if self.tracker.should_escalate_to_prompt(tool_name):
            raise PermissionPending(tool_name)
        decision = classify_tool_call(tool_name, tool_input, self.context)
        if decision is ClassifierDecision.AUTO_APPROVE: return "allow"
        if decision is ClassifierDecision.AUTO_DENY: raise PermissionDenied(tool_name)
        self.table.check(tool_name)
        return "allow"

    def record_user_denial(self, tool_name: str) -> None:
        self.tracker.record_denial(tool_name)
```

Dialog: add a "save as rule" button that calls `PermissionManager.persist_allow_rule(pattern_for_tool(tool_name))`. Do NOT write a new persistence path — `persist_allow_rule` already exists.

**Commit.**
```
feat(permissions): classifier gate wraps table; dialog persists rules via existing manager
```

**Dependencies.** T1, T2.

---

### P3.T4 — `/doctor` classifier section + audit log (Slice A)

**Files.** Modify `cli/doctor_sections.py`. Create `cli/permissions/audit_log.py`, `tests/test_permission_audit_log.py`, `tests/test_doctor_classifier_section.py`.

**Tests — audit log.**
```python
def test_audit_log_appends_jsonl(tmp_path):
    log = AuditLog(path=tmp_path / "permission_audit.log")
    log.record(tool_name="bash", decision="auto_approve", inp={"command": "ls"})
    log.record(tool_name="grep", decision="auto_approve", inp={"pattern": "def"})
    lines = (tmp_path / "permission_audit.log").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["tool"] == "bash"

def test_audit_log_rotates_at_10mb(tmp_path):
    log = AuditLog(path=tmp_path / "audit.log", max_bytes=1024)
    for _ in range(200): log.record(tool_name="bash", decision="auto_approve", inp={"x": "y"*50})
    rotated = tmp_path / "audit.log.1"
    assert rotated.exists()

def test_audit_log_never_edits_in_place(tmp_path):
    # Write a line, read it, write another — the first line must be byte-identical.
    ...
```

**Tests — `/doctor`.**
```python
def test_classifier_section_counts_auto_approvals():
    classifier_counts = {"bash": 5, "grep": 12}
    tracker = DenialTracker(3); tracker.record_denial("bash"); tracker.record_denial("bash")
    output = classifier_section(classifier_counts=classifier_counts, tracker=tracker, rule_count=4)
    assert "Auto-approvals this session:" in output
    assert "bash: 5" in output
    assert "grep: 12" in output
    assert "Denials (escalating after 3):" in output
    assert "Persisted rules: 4" in output
```

**Minimal impl.**

```python
# cli/permissions/audit_log.py
@dataclass
class AuditLog:
    path: Path
    max_bytes: int = 10 * 1024 * 1024

    def record(self, *, tool_name: str, decision: str, inp: dict[str, Any]) -> None: ...
    def _rotate_if_needed(self) -> None: ...  # rename audit.log → audit.log.1

# cli/doctor_sections.py addition
def classifier_section(*, classifier_counts: Mapping[str, int], tracker: DenialTracker,
                       rule_count: int) -> str: ...
```

Rotation strategy: when `path.stat().st_size >= max_bytes`, rename `path` → `path.with_suffix(path.suffix + ".1")` (overwriting any existing `.1`), create a new empty file. No automatic deletion — user decides when to drop.

**Commit.**
```
feat(permissions): audit log for auto-approvals + /doctor classifier section
```

**Dependencies.** T1, T2.

---

### P3.T5 — MCP transport abstraction + stdio extraction (Slice B)

**Files.** Create `cli/mcp/__init__.py`, `cli/mcp/transports/__init__.py`, `cli/mcp/transports/stdio.py`, `tests/test_mcp_transport_stdio.py`. Modify `cli/tools/mcp_bridge.py` only to accept a `Transport`-based factory (injection seam).

**Tests.**
```python
def test_stdio_transport_connects_and_lists_tools(fake_stdio):
    t = StdioTransport(command=["echo-server"], args=[])
    t.connect()
    assert t.is_connected is True
    t.send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    msg = t.receive(timeout=1.0)
    assert msg["id"] == 1

def test_stdio_transport_close_is_idempotent():
    t = StdioTransport(command=["echo-server"], args=[])
    t.close(); t.close()  # no raise
    assert t.is_connected is False

def test_stdio_transport_receive_timeout_returns_none():
    # With no server bytes available, receive(timeout=0.01) returns None, not raises.
    ...
```

**Minimal impl.**

```python
# cli/mcp/transports/__init__.py
from typing import Protocol

class Transport(Protocol):
    is_connected: bool
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def send(self, payload: dict) -> None: ...
    def receive(self, timeout: float) -> dict | None: ...

# cli/mcp/transports/stdio.py
@dataclass
class StdioTransport:
    command: list[str]
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # internal: subprocess, reader thread, queue
    ...
```

Use `subprocess.Popen` with stdin/stdout pipes, line-delimited JSON per MCP spec. Reader thread posts parsed messages into a `queue.Queue` so `receive(timeout)` can block on `queue.get(timeout=timeout)`.

**Backward compat — critical:** the new `StdioTransport` is the module under test, but `cli/tools/mcp_bridge.py` must keep working with the existing factory shape. Add a new wrapper `McpTransportClient(transport)` that satisfies the existing `McpClient` Protocol (`list_tools`, `call_tool`) by issuing JSON-RPC calls over the transport. The existing `McpClientFactory` gains a sibling `TransportBackedClientFactory` for the transport-based path. Existing tests stay green.

**Commit.**
```
feat(mcp): transport protocol + stdio extraction (backward-compatible)
```

**Dependencies.** None.

---

### P3.T6 — SSE transport (Slice B)

**Files.** Create `cli/mcp/transports/sse.py`, `tests/test_mcp_transport_sse.py`.

**Tests.**
```python
def test_sse_transport_parses_event_stream(httpx_mock):
    httpx_mock.add_response(
        url="https://mcp.example.com/sse",
        stream=[b"event: message\n", b"data: {\"jsonrpc\":\"2.0\",\"id\":1}\n\n"],
    )
    t = SseTransport(url="https://mcp.example.com/sse")
    t.connect()
    msg = t.receive(timeout=1.0)
    assert msg["id"] == 1

def test_sse_transport_reconnects_on_stale_ping():
    # With last_ping older than 2× ping_interval, is_connected → False; next receive() triggers reconnect.
    ...

def test_sse_transport_honors_keepalive_pings():
    # :ping comments reset the stale timer without emitting messages to receive().
    ...
```

**Minimal impl.**

```python
# cli/mcp/transports/sse.py
@dataclass
class SseTransport:
    url: str
    ping_interval_seconds: float = 30.0
    client: httpx.Client | None = None
    # internal event parser

    def connect(self) -> None: ...  # POST for handshake if the server advertises that
    def send(self, payload: dict) -> None: ...  # SSE is receive-only from server; sends go over a sibling POST endpoint
    def receive(self, timeout: float) -> dict | None: ...
```

Use `httpx.Client` with `httpx.Timeout(connect=5, read=None, write=5)`. Parse `event: <name>\ndata: <json>\n\n` frames. Ignore `:ping` comment lines except to update `last_event_time`.

**Commit.**
```
feat(mcp): SSE transport for hosted MCP servers
```

**Dependencies.** T5.

---

### P3.T7 — HTTP transport (Streamable HTTP per MCP spec) (Slice B)

**Files.** Create `cli/mcp/transports/http.py`, `tests/test_mcp_transport_http.py`.

**Tests.**
```python
def test_http_transport_posts_and_reads_json(httpx_mock):
    httpx_mock.add_response(
        url="https://mcp.example.com/rpc", method="POST",
        json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}},
    )
    t = HttpTransport(url="https://mcp.example.com/rpc")
    t.connect()
    t.send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    msg = t.receive(timeout=1.0)
    assert msg["result"]["tools"] == []

def test_http_transport_degrades_from_streaming_to_request_response():
    # Server responds 200 with content-type: application/json — fall back to single-shot RPC.
    ...

def test_http_transport_sends_accept_header():
    # Initial POST must include Accept: application/json, text/event-stream.
    ...
```

**Minimal impl.**

```python
# cli/mcp/transports/http.py
@dataclass
class HttpTransport:
    url: str
    client: httpx.Client | None = None
    _session_id: str | None = None
    _in_flight: dict[int, asyncio.Future] = field(default_factory=dict)

    def connect(self) -> None: ...  # initialize MCP session via initialize RPC
    def send(self, payload: dict) -> None: ...  # POST with Accept: application/json, text/event-stream
    def receive(self, timeout: float) -> dict | None: ...  # drain SSE or return single JSON
```

**Commit.**
```
feat(mcp): Streamable HTTP transport with SSE fallback
```

**Dependencies.** T5.

---

### P3.T8 — Reconnect supervisor (Slice B)

**Files.** Create `cli/mcp/reconnect.py`, `tests/test_mcp_reconnect.py`.

**Tests.**
```python
def test_reconnecting_transport_retries_with_exponential_backoff(monkeypatch):
    attempts = []
    inner = _flaky_transport(fail_first_n=3, log=attempts)
    t = ReconnectingTransport(inner, backoff_base=0.01, backoff_cap=0.1, sleep=lambda s: attempts.append(("sleep", s)))
    t.connect()
    sleeps = [s for tag, s in attempts if tag == "sleep"]
    assert sleeps == [0.01, 0.02, 0.04]

def test_reconnecting_transport_caps_backoff_at_60s():
    # After ~7 failures, the requested sleep is capped.
    ...

def test_reconnect_invalidates_cached_tool_schemas():
    cached_schema = [{"name": "foo"}]
    t = ReconnectingTransport(_always_fail(), on_reconnect=lambda: cached_schema.clear())
    # simulate drop + reconnect → cached_schema is empty
    ...

def test_reconnect_invokes_re_registration_callback():
    called = []
    t = ReconnectingTransport(_reconnectable(), on_reconnect=lambda: called.append("re-reg"))
    # force reconnect
    ...
    assert called == ["re-reg"]
```

**Minimal impl.**

```python
# cli/mcp/reconnect.py
@dataclass
class ReconnectingTransport:
    inner: Transport
    backoff_base: float = 1.0
    backoff_cap: float = 60.0
    ping_interval: float = 30.0
    sleep: Callable[[float], None] = time.sleep
    on_reconnect: Callable[[], None] | None = None
    # delegates send/receive/close to inner; traps connection errors and retries

    def connect(self) -> None: ...
    def send(self, payload): ...
    def receive(self, timeout: float): ...
    def close(self) -> None: ...
    @property
    def is_connected(self) -> bool: ...
```

Exponential backoff `min(base * 2**n, cap)`, cap 60. Ping loop posts `{"jsonrpc": "2.0", "id": <ping_id>, "method": "ping"}` every `ping_interval`. Missed ping → reconnect.

**Commit.**
```
feat(mcp): reconnecting transport with exponential backoff and re-registration callbacks
```

**Dependencies.** T5, T6, T7.

---

### P3.T9 — MCP config shape + wizard (Slice B)

**Files.** Modify `cli/mcp_runtime.py` (extend pydantic/dict validation to tagged-union transport). Modify `cli/mcp_setup.py` (wizard prompts for SSE/HTTP URL). Modify `cli/tools/mcp_bridge.py` to dispatch on `transport` field when building clients. Create `tests/test_mcp_config_shape.py`, `tests/test_mcp_setup_wizard.py`.

**Tests — config.**
```python
def test_stdio_config_back_compat():
    cfg = _load_server_config({"command": "mcp-server-foo", "args": ["--flag"]})
    assert cfg.transport == "stdio"
    assert cfg.command == "mcp-server-foo"

def test_sse_config_requires_url():
    with pytest.raises(ValidationError):
        _load_server_config({"transport": "sse"})  # missing url

def test_http_config_round_trips():
    cfg = _load_server_config({"transport": "http", "url": "https://mcp.example.com/rpc"})
    assert cfg.url == "https://mcp.example.com/rpc"
```

**Tests — wizard.**
```python
def test_wizard_offers_transport_choice(monkeypatch, tmp_path):
    # Mock click.prompt to answer (name="foo", transport="sse", url="https://x")
    # Run the wizard main path; assert .mcp.json contains the sse entry.
    ...
```

**Tests — dispatch.**
```python
def test_bridge_factory_routes_to_stdio(fake_factory_registry):
    client = build_mcp_client({"transport": "stdio", "command": "x"})
    assert isinstance(client.transport, StdioTransport)

def test_bridge_factory_routes_to_sse():
    client = build_mcp_client({"transport": "sse", "url": "https://x"})
    assert isinstance(client.transport, SseTransport)
```

**Minimal impl.**

Add a tagged-union pydantic model:

```python
class StdioServerConfig(BaseModel):
    name: str
    transport: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

class SseServerConfig(BaseModel):
    name: str
    transport: Literal["sse"]
    url: str

class HttpServerConfig(BaseModel):
    name: str
    transport: Literal["http"]
    url: str

ServerConfig = Annotated[Union[StdioServerConfig, SseServerConfig, HttpServerConfig], Field(discriminator="transport")]
```

Wizard: add a second prompt `transport? [stdio/sse/http] (default: stdio)`; on non-stdio, prompt for `url` instead of `command`.

`mcp_bridge.py`: replace the single-client factory with a dispatch on `config.transport`.

**Commit.**
```
feat(mcp): tagged config union for stdio/sse/http transports + wizard extension
```

**Dependencies.** T5, T6, T7, T8.

---

## Phase 2 — Integration (Slice A only)

P3a is runtime code — wire the `ClassifierGate` into `cli/llm/orchestrator.py` where `PermissionTable.check` is currently called. **Deferred until P1 merges** (same constraint as P2.orch — `orchestrator.py` is P1's territory). A one-line change:

```python
# inside run_turn, before dispatching a tool:
gate.check(tool.name, tool_input)  # replaces table.check(tool.name)
```

Gate construction happens in `build_workbench_runtime` (wherever the `PermissionTable` is built today).

P3b is passive infrastructure — `mcp_bridge.py` picks up the new transport dispatch without any `orchestrator.py` change. Ships immediately.

---

## Critical invariants P3 must preserve

- **Classifier defaults to PROMPT on ambiguity.** Every unknown / uncovered branch returns PROMPT.
- **Writes never auto-approve.** `file_edit`, `file_write`, `config_edit`, bash writes, `task_create`, `agent_spawn`, `todo_write`, any MCP → PROMPT unless the user saved an allow rule.
- **Persisted rules beat heuristics.** Checked first in `classify_tool_call`.
- **Denials never silently disappear.** Denial tracker only escalates — never auto-approves.
- **Audit log is append-only.** Rotate at 10 MB, never delete automatically.
- **MCP server failures are visible.** `/doctor` gains a transport-status row per server.
- **Old stdio users unaffected.** `.mcp.json` entries without `transport` keep working (implicit `"stdio"`).
- **Snapshot stability.** `tests/test_system_prompt.py` byte-stable.
- **`cli/llm/orchestrator.py` untouched** (P1 parallel).

---

## Self-review — spec coverage

| P3 handoff item | Covered by |
|---|---|
| P3a.1 rule tables + safety guardrails | T1 |
| P3a.2 denial tracking | T2 |
| P3a.3 permission-dialog wiring | T3 |
| P3a.4 `/doctor` + audit log | T4 |
| P3b.1 transport abstraction + stdio extraction | T5 |
| P3b.2 SSE transport | T6 |
| P3b.3 HTTP transport | T7 |
| P3b.4 reconnect supervisor | T8 |
| P3b.5 config shape + wizard | T9 |

No placeholders, no "TBD", no unresolved type references. T1-T9 are each independently TDD-able.

## Execution

Subagent-driven — one subagent per task, ships one commit, merges back to master in pairs.
