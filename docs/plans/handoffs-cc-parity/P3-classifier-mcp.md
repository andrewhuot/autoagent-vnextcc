# P3 Handoff — Permission classifier + MCP transports

Paste the block below into a fresh Claude Code session at the repo root (`/Users/andrew/Desktop/agentlab`).

**Prerequisites:**
- **P0 merged** (classifier persists rules via settings cascade).
- **P0.5 merged** (classifier consults `capabilities` to reason about per-provider tool safety).
- **Parallel-safe with P1** — no file overlap. Parallel-safe with P4.
- **Not dependent on P2.**

**What this unlocks:** Much less prompting on safe ops; MCP servers hosted remotely (SSE/HTTP) work, not just local stdio.

---

## Session prompt

You are picking up the AgentLab Claude-Code-parity roadmap at **P3 — Permission classifier + MCP transports**. P0 (settings+hooks) and P0.5 (provider parity) have shipped. P1 may or may not have shipped — P3 is independent of it. The roadmap lives at `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

### Your job

Ship **P3** in two slices, following subagent-driven TDD:

- **Slice A — Transcript classifier for auto-approval** (P3a). Reduces permission-prompt noise for read-only ops.
- **Slice B — MCP SSE + HTTP transports + reconnect** (P3b). Hosted MCP servers work.

Slices are independent — parallel-safe. Single engineer: A first (more user impact), then B.

- `.venv/bin/python -m pytest` (Python 3.11).
- Failing test → minimal impl → passing test → conventional commit.

### P3 goal

**Slice A:** Replicate Claude Code's `TRANSCRIPT_CLASSIFIER` feature. A small heuristic-first pipeline that auto-approves obviously-safe tool calls (read-only file/grep, well-known web hosts, bash commands matching a strict allowlist). Ambiguity → prompt, not auto-approve. Denial-tracking falls back to prompting after N denials per tool.

**Slice B:** Today `cli/mcp_runtime.py` runs stdio servers only. Add SSE and HTTP transports with graceful reconnect and a daemon-style health-check supervisor. OAuth deferred to a future phase.

**Reference shape (read for architectural inspiration, do NOT copy code):**
- Classifier: `/Users/andrew/Desktop/claude-code-main/src/utils/permissions/bashClassifier.ts`, `yoloClassifier.ts`, `classifierShared.ts`, `classifierDecision.ts`, `denialTracking.ts`, `dangerousPatterns.ts`, `shellRuleMatching.ts`.
- Permission rules: `PermissionRule.ts`, `PermissionUpdate.ts`, `permissionRuleParser.ts`, `permissionsLoader.ts`.
- MCP: `/Users/andrew/Desktop/claude-code-main/src/services/mcp/client.ts`, `config.ts`, `normalization.ts`, `utils.ts`, `MCPConnectionManager.tsx`.

### Before dispatching anything

1. **Read the P3 section** of `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

2. **Ground-truth these files:**
   - `cli/permissions.py` — existing `PermissionManager`, rule-based gate.
   - `cli/workbench_app/tool_permissions.py` — `PermissionTable`, `Policy` enum (`ALLOW`/`DENY`/`ASK`), `PermissionPending` exception.
   - `cli/workbench_app/permission_dialog.py` — modal prompt; must gain a "save as rule" button.
   - `cli/mcp_runtime.py` — existing stdio server dispatch.
   - `cli/mcp_setup.py` — onboarding/wizard.
   - `cli/tools/mcp_bridge.py` — dynamic `McpTool` subclass per server tool.
   - `cli/settings/` (P0) — cascade destination for classifier rules.
   - `cli/llm/provider_capabilities.py` (P0.5) — capability consumption.

3. **Write a TDD expansion plan** at `docs/plans/2026-04-17-p3-classifier-mcp-tdd.md`. Commit alone first.

### P3a — Transcript classifier (tasks)

**P3a.1 — Rule tables + safety guardrails.**
- Create `cli/permissions/classifier.py`:
  - `classify_tool_call(tool_name, tool_input, context) -> ClassifierDecision` where decision is `AUTO_APPROVE`, `AUTO_DENY`, or `PROMPT`.
  - Per-tool rule functions: `_classify_bash`, `_classify_file_read`, `_classify_glob`, `_classify_grep`, `_classify_web_fetch`, `_classify_web_search`. Anything unlisted → `PROMPT`.
  - Bash allowlist is tiny: `ls`, `pwd`, `git status`, `git diff`, `git log`, `git show`, `cat` of files under workspace root, `which`. Pipelines / redirects / backticks / `$()` / `&&` / `||` always PROMPT. Absolute paths outside workspace always PROMPT.
  - Web hosts: a short domain allowlist in settings; anything else PROMPT.
  - File reads under workspace root → AUTO_APPROVE. Reads above root → PROMPT.
- Tests: `tests/test_permission_classifier.py` — table-driven: 50+ cases per tool, including adversarial inputs (null bytes, unicode homoglyphs, shell metachars, URL-encoded hosts).

**P3a.2 — Denial tracking.**
- Create `cli/permissions/denial_tracking.py`:
  - `DenialTracker(max_per_session_per_tool=3)` counts user "deny" responses per tool per session.
  - After N denials, the classifier *stops* auto-approving that tool family for the rest of the session even if heuristics say it's safe — falls back to PROMPT.
  - State is in-memory; not persisted across sessions.
- Tests: `tests/test_denial_tracking.py` — count advances, threshold fires, independence per tool, session reset.

**P3a.3 — Permission-dialog wiring.**
- Modify `cli/workbench_app/tool_permissions.py` to consult classifier + denial tracker before showing the prompt.
- Modify `cli/workbench_app/permission_dialog.py` — add a "save as rule" button that writes to `<project>/.agentlab/settings.json::permissions.rules` via the P0 cascade's write path. Persisted rules win over classifier output.
- Tests: `tests/test_permission_dialog_save_rule.py` — writing a rule round-trips through settings load.

**P3a.4 — `/doctor` + audit log.**
- Extend `cli/doctor_sections.py` with `classifier_section(tracker, classifier)` — auto-approvals this session (count by tool), denials, rule count.
- Every auto-approval writes a line to `.agentlab/permission_audit.log` (one JSON object per line) so users can audit what got auto-approved. Rotated at 10MB.
- Tests: `tests/test_permission_audit_log.py`.

### P3b — MCP transports (tasks)

**P3b.1 — Transport abstraction.**
- Create `cli/mcp/transports/__init__.py` with a `Transport` Protocol:
  ```python
  class Transport(Protocol):
      def connect(self) -> None: ...
      def close(self) -> None: ...
      def send(self, payload: dict) -> None: ...
      def receive(self, timeout: float) -> dict | None: ...
      is_connected: bool
  ```
- Extract the existing stdio implementation in `cli/mcp_runtime.py` into `cli/mcp/transports/stdio.py` (rename + adapter). Preserve existing behavior.
- Tests: `tests/test_mcp_transport_stdio.py` — extracted-module regression tests.

**P3b.2 — SSE transport.**
- Create `cli/mcp/transports/sse.py` — uses `httpx` (already a dev dep) in EventSource mode. Long-poll with keep-alives.
- Tests: `tests/test_mcp_transport_sse.py` — fixture mock server emits canned events; assert parsing + reconnect.

**P3b.3 — HTTP transport.**
- Create `cli/mcp/transports/http.py` — streamable HTTP (POST per call, SSE for server-initiated messages). Follow MCP spec `Streamable HTTP` transport.
- Tests: `tests/test_mcp_transport_http.py`.

**P3b.4 — Reconnect supervisor.**
- Create `cli/mcp/reconnect.py` — `ReconnectingTransport(inner, backoff)` wrapper. Exponential backoff (1s, 2s, 4s, ..., cap 60s), health-check pings every 30s, invalidates cached tool schemas on reconnect, re-registers with the executor.
- Modify `cli/mcp_runtime.py` to dispatch on `transport: stdio | sse | http` from the server config, wrapping with `ReconnectingTransport`.
- Modify `cli/mcp_setup.py` — wizard supports entering an SSE or HTTP URL.
- Tests: `tests/test_mcp_reconnect.py` — simulate dropped connection, assert reconnect, schema invalidation, tool re-registration.

**P3b.5 — Config shape.**
- MCP server config in `Settings.mcp.servers` accepts:
  ```json
  {"name": "foo", "transport": "stdio", "command": ["mcp-server-foo"], "args": [...]}
  {"name": "bar", "transport": "sse", "url": "https://..."}
  {"name": "baz", "transport": "http", "url": "https://..."}
  ```
- Load via P0's cascade; validate with pydantic.

### Critical invariants P3 must preserve

- **Classifier defaults to prompt on ambiguity.** Unknown tool, unknown bash command, unknown URL host, anything that contains shell metacharacters → PROMPT.
- **Writes never auto-approve.** `file_edit`, `file_write`, `config_edit`, `bash` (except the tiny allowlist), `task_create`, `agent_spawn`, `todo_write`, anything MCP → always PROMPT unless the user explicitly saved a rule.
- **Persisted rules beat heuristics.** If the user denied a tool via "save as rule", no classifier path can auto-approve it.
- **Denials never silently disappear.** Denial tracking never auto-*approves*; it only *escalates* borderline-safe things back to prompting.
- **Audit log is append-only.** Never edit in place; rotate, never delete auto.
- **MCP server failures are visible.** Connection drops, reconnect attempts, schema changes all surface in `/doctor`.
- **Old stdio users unaffected.** No config change required for existing users.
- **Snapshot stability.** `tests/test_system_prompt.py` stays byte-for-byte.

### Workflow

1. Worktree: `git worktree add .claude/worktrees/p3-classifier-mcp -b claude/cc-parity-p3 master` (after P0.5 merged).
2. Slices parallel-safe. Single engineer: P3a first.
3. Adversarial testing matters more here than anywhere else — the classifier is a new attack surface. Dedicate a focused review pass on P3a.1's rule table before merging.
4. Dogfood: run a few tool-heavy turns, confirm auto-approval feels correct, try to fool the bash classifier with obvious injection attempts (backticks, variable substitution, null bytes).
5. Open a PR per slice.

### If you get stuck

- Bash command parsing: don't try to fully parse shell syntax. Use `shlex.split` with `posix=True` for the one allowlisted command, then match the first token against a literal set. Any failure to split cleanly → PROMPT.
- Web host matching: parse the URL; compare the host to the allowlist literally. No subdomain wildcards unless the user explicitly added `*.example.com` to their rule set. Never auto-approve IP addresses.
- SSE edge cases: proxies buffer, so reconnect when the server's last `ping` is older than 2× the ping interval. `httpx` timeouts need to be tuned; see `httpx.Timeout(connect=5, read=None, write=5)` for long-poll sessions.
- HTTP transport: the spec requires `Accept: application/json, text/event-stream` on the initial POST. Servers that don't honor streaming degrade to request/response; fall back gracefully.
- MCP schema re-registration: if the server's tool list shrinks on reconnect, the executor must *remove* the vanished tools, not keep stale schemas.
- Classifier adversarial testing: add every bypass you find to the test table so it regresses on rediscovery.

### Anti-goals

- Do not add MCP OAuth. Too big for this phase. Deferred.
- Do not add MCP WebSocket transport. SSE covers the streaming case.
- Do not implement ML-based classifier. Heuristics are the entire scope for P3a. A future phase can add ML.
- Do not introduce a new "trust zone" concept beyond the existing `allow/ask/deny`. Stay lean.

### First action

After the user confirms, read the roadmap P3 section, read the eight ground-truth files, write the TDD expansion plan, commit, dispatch P3a.1 (or P3b.1 if starting with Slice B).

Use superpowers and TDD. Work in subagents. Be specific. The classifier is a safety-critical surface — err toward prompting the user.
