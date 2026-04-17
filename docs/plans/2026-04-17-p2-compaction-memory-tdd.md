# P2 — Compaction + Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task below ships as one failing test → minimal impl → passing test → conventional commit. One task per subagent. Verify the repo-wide suite green after every merge-back.

**Goal:** Long AgentLab sessions stop blowing context (automatic compaction + `/uncompact`) and the model learns across sessions (auto-memory extraction + BM25 retrieval into the system prompt).

**Architecture.** Two vertical slices that share zero runtime state:

- **Slice A — Conversation compaction.** When transcript size exceeds `0.8 × capabilities.max_context_tokens`, insert a `SystemCompactBoundaryMessage` and a `ToolUseSummaryMessage` digest; the replaced turns archive to `.agentlab/compact_archive/<session-id>/<start>-<end>.jsonl` for `/uncompact` restore. The cheap forked-model call uses `create_model_client(model=<cheap_for_active_provider>)`.
- **Slice B — Memory extraction + retrieval.** After each completed turn dispatch a cheap-model extraction through `BackgroundTaskRegistry` (AgentLab's existing task surface); on each subsequent turn `find_relevant(user_query, memories)` surfaces top-K under `## Relevant memories` in the system prompt. Store is markdown-with-frontmatter, one file per memory, mirroring the user's own `~/.claude/projects/.../memory/` layout.

**Constraint — P1 is in parallel development.** P1 reshapes `cli/llm/orchestrator.py::run_turn` (streaming dispatch). We MUST NOT touch `orchestrator.py` in this worktree or we will merge-conflict with P1 when it lands. Every P2 piece that requires an `orchestrator.py` edit is parked in Phase 2 (`P2.orch`); Phase 1 ships pure helpers, stores, UI renderers, and slash-command shells that will be wired up in one atomic integration commit after P1 merges to master.

**Tech stack.** Python 3.11, pyyaml (frontmatter), `cli/llm/*` infra (P0.5 capabilities, factory, streaming), existing `BackgroundTaskRegistry` for background dispatch, existing `Transcript` / `SlashContext` surfaces.

**Test runner:** `/Users/andrew/Desktop/agentlab/.venv/bin/python -m pytest` (the worktree's own `.venv` lacks pytest; the parent venv is where we run tests). Invoke pytest foreground — do not self-start background monitors.

---

## Ground-truth findings

Where the canonical P2 handoff diverges from what's actually in the tree on `claude/cc-parity-p2`:

1. **`cli/llm/orchestrator.py`** — confirmed. `LLMOrchestrator.run_turn` is the call site (lines 109–240). The loop appends `TurnMessage` to `self.messages` and returns an `OrchestratorResult`. Compaction would fire in Phase 2 right before the `while True` model-call loop (to ensure the next call sees a compacted transcript) or right after `self.messages.append(TurnMessage(...))` at the end of the turn (symmetrical with where a session write already happens). Memory extraction dispatch belongs at the same post-turn seam where `_fire_session_end_hook` is called (line 226). `_compose_system_prompt` (line 323) is where `relevant_memories` would compose — but for Phase 1 we only extend the pure `build_system_prompt` signature, not the compose path.
2. **`cli/workbench_app/transcript.py`** — `TranscriptEntry` is a frozen dataclass with a `role: TranscriptRole` Literal (`"user" | "assistant" | "system" | "tool" | "error" | "warning" | "meta"`). There is no existing "boundary" role. **Decision:** reuse `"system"` role for the boundary line and tag it via a new `event_name="compact_boundary"` field (already present on `TranscriptEntry` for tool events). This keeps `TranscriptRole` byte-stable. Rendering gets a small branch in `format_entry` that detects the sentinel event name and emits a horizontal-rule preamble.
3. **`cli/workbench_app/conversation_store.py`** — SQLite schema (conversation / message / tool_call). **Decision:** compaction archive is NOT persisted to this SQLite store. JSONL archive under `.agentlab/compact_archive/<session-id>/<start>-<end>.jsonl` is a new parallel surface. The SQLite store's rows are not touched — no migration.
4. **`cli/project_instructions/loader.py` — does not exist.** The handoff's "extend the AGENTLAB.md loader" is incorrect. AGENTLAB.md is generated and printed by `cli/workbench_app/init_scan.py` + the `/memory` slash (`slash.py:320 _handle_memory` → `memory show` Click command). MEMORY.md retrieval bypasses this entirely: it lives next to per-memory files in `<workspace>/.agentlab/memory/` (project) or `~/.agentlab/memory/` (user) and is read by `MemoryStore`, not by a prompt loader. We do **not** extend init_scan to write MEMORY.md.
5. **`cli/workbench_app/system_prompt.py`** — confirmed. `build_system_prompt` is keyword-only with `workspace_name`, `agent_card_path`, `registry`. Adding `relevant_memories: Sequence[Memory] | None = None` is a byte-stable change (default None → no section rendered → identical output).
6. **`cli/llm/providers/factory.py`** — confirmed. `create_model_client` + `resolve_provider` are clean. **Gap:** no "cheapest model for provider family" helper exists. We add `cheap_model_for(model: str) -> str` (pure lookup table: `claude-*` → `claude-haiku-4-5`, `gpt-*`/`o*-*` → `gpt-4o-mini`, `gemini-*` → `gemini-2.5-flash`, `echo` → `echo`). Lives in `cli/llm/compaction.py` alongside the budget primitives.
7. **`cli/llm/provider_capabilities.py`** — confirmed. `max_context_tokens` and `json_mode` are required fields on `ProviderCapabilities` (P0.5 landed).
8. **`cli/tasks/` — does not exist.** The handoff's "TaskStore + TaskExecutor" are aspirational names. The concrete surface is **`cli/workbench_app/background_panel.py::BackgroundTaskRegistry`** with `register(description, *, owner, detail) -> BackgroundTask` and `update(task_id, *, status, detail)`. In Phase 1 we write `extract_memories` as a pure sync function; in Phase 2 `P2.orch` wires the dispatch to this registry (short-lived `threading.Thread` + registry row, matching how subagent jobs are already tracked).
9. **Live memory at `~/.claude/projects/-Users-andrew-Desktop-agentlab/memory/`** — confirmed layout:
   - `MEMORY.md` is a flat bullet index: `- [Title](slug.md) — summary (date)`.
   - Each memory is `<slug>.md` with YAML frontmatter (`name`, `description`, `type`, `originSessionId`) and a free-text markdown body.
   - Types observed: `project`. Claude Code's `memoryTypes.ts` confirms the full taxonomy we mirror: `user`, `feedback`, `project`, `reference`.
10. **`cli/memory/` — does not exist.** Free to create.
11. **`ModelClient.count_tokens` — does not exist.** Handoff anticipated this. Fallback in `CompactionBudget.estimate_tokens`: `len(serialised) // 4` with a `logger.warning` on first use per process; pluggable via a `token_counter` keyword so tests inject an exact counter.

---

## Task sequence

### Phase 1 — Safe-now tasks (no `orchestrator.py` changes)

Dispatch T1 → T3 → T4 (Slice A pure) and T5 → T6 → T7 → T8 → T9 (Slice B pure) as two parallel lanes. T1-T3 and T5-T7 are independent and can all run in parallel; T4 depends on T1 (for the `CompactionBudget` shape), T8 depends on T5 (for the `Memory` dataclass), T9 depends on T5+T7 (for store CRUD + retrieval trace).

#### P2.T1 — Compaction budget + threshold helpers (pure)

**Files.** Create `cli/llm/compaction.py`, `tests/test_compaction_threshold.py`.

**Tests (`tests/test_compaction_threshold.py`).**

```python
def test_under_threshold_returns_false():
    budget = CompactionBudget(max_context_tokens=1000, threshold_ratio=0.8)
    transcript = _make_transcript(total_tokens=500)
    assert should_compact(transcript, budget, token_counter=_exact_counter) is False

def test_over_threshold_returns_true():
    budget = CompactionBudget(max_context_tokens=1000, threshold_ratio=0.8)
    transcript = _make_transcript(total_tokens=900)
    assert should_compact(transcript, budget, token_counter=_exact_counter) is True

def test_min_retained_turns_never_compacted():
    budget = CompactionBudget(max_context_tokens=1000, min_retained_turns=4)
    transcript = _make_transcript(n_turns=4, total_tokens=10_000)
    start, end = choose_compact_range(transcript, budget, token_counter=_exact_counter)
    assert (start, end) == (0, 0)  # sentinel: nothing to compact

def test_idempotent_on_already_compacted():
    # Transcript that already contains a boundary marker → no further compaction.
    transcript = _make_transcript_with_boundary()
    budget = CompactionBudget(max_context_tokens=1000)
    assert should_compact(transcript, budget, token_counter=_exact_counter) is False

def test_cheap_model_lookup_per_provider():
    assert cheap_model_for("claude-sonnet-4-5") == "claude-haiku-4-5"
    assert cheap_model_for("gpt-5") == "gpt-4o-mini"
    assert cheap_model_for("gemini-2.5-pro") == "gemini-2.5-flash"
    assert cheap_model_for("echo") == "echo"
```

**Minimal impl.**

```python
# cli/llm/compaction.py
@dataclass(frozen=True)
class CompactionBudget:
    max_context_tokens: int
    threshold_ratio: float = 0.8
    min_retained_turns: int = 4

TokenCounter = Callable[[Any], int]

def _default_counter(content: Any) -> int:
    # len(str(content)) // 4 — warn once per process.
    ...

def should_compact(transcript: list[TurnMessage], budget: CompactionBudget,
                   *, token_counter: TokenCounter = _default_counter) -> bool: ...

def choose_compact_range(transcript: list[TurnMessage], budget: CompactionBudget,
                         *, token_counter: TokenCounter = _default_counter
                         ) -> tuple[int, int]:
    """Return (start, end) half-open slice of messages to replace with a
    boundary + digest. (0, 0) means nothing to compact."""

def cheap_model_for(model: str) -> str:
    """Pure lookup. Raises ProviderFactoryError on unknown prefixes (via
    resolve_provider())."""

def has_boundary(transcript: list[TurnMessage]) -> bool: ...
```

**No orchestrator changes.** The functions are pure. Boundary detection uses a sentinel in `TurnMessage.content` (see T3).

**Dependencies.** None.

---

#### P2.T2 — Tool-phase digest generator (pure + forked-model client)

**Files.** Create `cli/llm/digests.py`, `tests/test_digests.py`.

**Tests.**

```python
def test_extractive_strategy_big_blob():
    # A tool_result with 5KB of grep output → extractive: first 20 + last 20 lines + "<…N omitted…>"
    turns = _make_tool_phase_with_big_result(result_bytes=5_000)
    digest = digest_tool_phase(turns, model_client=_never_called_client())
    assert "N lines omitted" in digest.text
    assert digest.strategy == "extractive"

def test_abstractive_strategy_chat_heavy():
    turns = _make_tool_phase_with_chatty_results()
    digest = digest_tool_phase(turns, model_client=_fake_model_returning("summary"))
    assert digest.strategy == "abstractive"
    assert digest.text == "summary"

def test_strategy_selector_2kb_cutoff():
    assert _pick_strategy(_result_of_size(1999)) == "abstractive"
    assert _pick_strategy(_result_of_size(2048)) == "extractive"

def test_abstractive_uses_cheap_model_family():
    # Injected model_client asserts it was constructed with cheap_model_for(active).
    ...

def test_digest_has_bounded_output_tokens():
    digest = digest_tool_phase(_big_turns(), model_client=_echoing_client(),
                               max_output_tokens=256)
    assert _approx_tokens(digest.text) <= 256
```

**Minimal impl.**

```python
# cli/llm/digests.py
@dataclass(frozen=True)
class ToolPhaseDigest:
    text: str
    strategy: Literal["extractive", "abstractive"]
    source_turn_count: int

EXTRACTIVE_THRESHOLD_BYTES = 2048

def digest_tool_phase(turns: list[TurnMessage], *, model_client: ModelClient,
                      max_output_tokens: int = 512) -> ToolPhaseDigest: ...

def _pick_strategy(result_bytes: int) -> Literal["extractive", "abstractive"]: ...

def _extractive_summary(turns, *, head=20, tail=20) -> str: ...

def _abstractive_summary(turns, *, model_client, max_output_tokens) -> str:
    # single non-streaming model_client.complete() with a strict JSON schema
    # when capabilities.json_mode else free-text. Prompt is provider-neutral.
```

**No orchestrator changes.** `digest_tool_phase` accepts an injected `ModelClient`. The caller that will live in `orchestrator.py` (P2.orch) builds the cheap client via `create_model_client(model=cheap_model_for(active_model))`.

**Dependencies.** T1 (`cheap_model_for`).

---

#### P2.T3 — Compact archive store (pure I/O)

**Files.** Create `cli/llm/compact_archive.py`, `tests/test_compact_archive.py`.

**Tests.**

```python
def test_write_and_load_round_trip(tmp_path):
    archive = CompactArchive(root=tmp_path, session_id="abc")
    archive.write(start=3, end=17, messages=_sample_messages())
    restored = archive.load(start=3, end=17)
    assert restored == _sample_messages()

def test_list_archives_returns_ranges(tmp_path):
    archive = CompactArchive(root=tmp_path, session_id="abc")
    archive.write(3, 17, _sample_messages())
    archive.write(20, 30, _sample_messages())
    assert archive.ranges() == [(3, 17), (20, 30)]

def test_jsonl_is_append_only_per_line(tmp_path):
    # Each line is one TurnMessage dict so truncation mid-write loses at most one row.
    ...

def test_30_day_retention_marker(tmp_path):
    archive = CompactArchive(root=tmp_path, session_id="abc")
    path = archive.write(3, 17, _sample_messages())
    assert archive.is_expired(path, now=archive.written_at(path) + timedelta(days=29)) is False
    assert archive.is_expired(path, now=archive.written_at(path) + timedelta(days=31)) is True

def test_build_boundary_message_round_trip():
    msg = build_boundary_message(start=3, end=17, digest_text="…")
    assert is_boundary(msg)
    assert boundary_range(msg) == (3, 17)
```

**Minimal impl.**

```python
# cli/llm/compact_archive.py
COMPACT_BOUNDARY_SENTINEL = "__compact_boundary__"

@dataclass
class CompactArchive:
    root: Path           # <workspace>/.agentlab/compact_archive
    session_id: str

    def write(self, start: int, end: int, messages: list[TurnMessage]) -> Path: ...
    def load(self, start: int, end: int) -> list[TurnMessage]: ...
    def ranges(self) -> list[tuple[int, int]]: ...
    def is_expired(self, path: Path, *, now: datetime) -> bool: ...

def build_boundary_message(*, start: int, end: int, digest_text: str) -> TurnMessage:
    """TurnMessage(role="system", content={"kind": COMPACT_BOUNDARY_SENTINEL,
                                            "range": [start, end],
                                            "digest": digest_text})"""

def is_boundary(msg: TurnMessage) -> bool: ...
def boundary_range(msg: TurnMessage) -> tuple[int, int]: ...
```

**No orchestrator changes.** I/O is owned by `CompactArchive`. `build_boundary_message` is the sentinel T1's `has_boundary` checks for.

**Dependencies.** None (uses `TurnMessage` from `cli/llm/types.py`).

---

#### P2.T4 — Transcript boundary UI rendering

**Files.** Modify `cli/workbench_app/transcript.py` (pure helper only — `format_entry` + a new `append_compact_boundary` helper). Create `tests/test_transcript_compaction_ui.py`.

**Tests.**

```python
def test_format_entry_renders_boundary_rule():
    entry = TranscriptEntry(
        role="system",
        content="Compacted 14 turns — /uncompact to restore",
        event_name="compact_boundary",
        data={"range": (3, 17)},
    )
    rendered = format_entry(entry, color=False)
    assert "─" * 10 in rendered                  # horizontal rule preamble
    assert "Compacted 14 turns" in rendered
    assert "/uncompact" in rendered

def test_append_compact_boundary_stores_entry():
    t = Transcript(echo=lambda s: None, color=False)
    entry = t.append_compact_boundary(start=3, end=17, summary="tool phase")
    assert entry.event_name == "compact_boundary"
    assert entry.data["range"] == (3, 17)

def test_status_bar_compacted_indicator_pure_helper():
    entries = [_user_entry(), _boundary_entry()]
    assert transcript_has_boundary(entries) is True
    assert transcript_has_boundary([_user_entry()]) is False
```

**Minimal impl.**

```python
# cli/workbench_app/transcript.py (additions)
def format_entry(entry, *, color=True):
    if entry.role == "system" and entry.event_name == "compact_boundary":
        return _format_compact_boundary(entry, color=color)
    # … existing branches …

def _format_compact_boundary(entry, *, color): ...

class Transcript:
    def append_compact_boundary(self, *, start: int, end: int, summary: str) -> TranscriptEntry: ...

def transcript_has_boundary(entries: Sequence[TranscriptEntry]) -> bool: ...
```

**No orchestrator changes.** All helpers are synchronous on an in-memory transcript — the orchestrator wiring that would actually call `append_compact_boundary` happens in Phase 2.

**Dependencies.** T1 (boundary sentinel shape), T3 (range tuple shape).

---

#### P2.T5 — Memory store + frontmatter schema

**Files.** Create `cli/memory/__init__.py`, `cli/memory/types.py`, `cli/memory/store.py`, `tests/test_memory_store.py`.

**Tests.**

```python
def test_memory_round_trip(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    memory = Memory(
        name="User prefers terse answers",
        type="feedback",
        description="Private communication preference",
        body="Why: user said 'stop summarizing'.\nHow to apply: skip trailing recap.",
        created_at=datetime(2026, 4, 17, tzinfo=timezone.utc),
        source_session_id="sess-1",
    )
    path = store.write(memory)
    restored = store.read(path)
    assert restored == memory

def test_frontmatter_parse_validate(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    path = tmp_path / "bad.md"
    path.write_text("---\nname: X\ntype: garbage\n---\n")
    with pytest.raises(InvalidMemoryError):
        store.read(path)

def test_index_stays_under_200_lines(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    for i in range(300):
        store.write(_memory(name=f"m{i}"))
    index_text = (tmp_path / "MEMORY.md").read_text()
    assert len(index_text.splitlines()) <= 200  # overflow spills to MEMORY.archive.md

def test_update_in_place_by_name(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="same", body="v1"))
    store.write(_memory(name="same", body="v2"))
    assert store.get_by_name("same").body == "v2"
    assert len(store.list()) == 1  # one file, not two

def test_list_sorted_newest_first(tmp_path):
    ...
```

**Minimal impl.**

```python
# cli/memory/types.py
MemoryType = Literal["user", "feedback", "project", "reference"]

@dataclass(frozen=True)
class Memory:
    name: str
    type: MemoryType
    description: str
    body: str
    created_at: datetime
    source_session_id: str | None = None

class InvalidMemoryError(ValueError): ...

# cli/memory/store.py
class MemoryStore:
    def __init__(self, memory_dir: Path): ...
    def write(self, memory: Memory) -> Path: ...        # slug = _slugify(name)
    def read(self, path: Path) -> Memory: ...
    def get_by_name(self, name: str) -> Memory | None: ...
    def list(self) -> list[Memory]: ...
    def delete(self, name: str) -> bool: ...
    def rebuild_index(self) -> None: ...                 # writes MEMORY.md
```

**No orchestrator changes.** Pure filesystem CRUD.

**Dependencies.** None.

---

#### P2.T6 — Memory extractor (pure; dispatch deferred)

**Files.** Create `cli/memory/extractor.py`, `tests/test_memory_extractor.py`.

**Tests.**

```python
def test_extract_returns_memories_from_model_output():
    client = _fake_json_client({"memories": [_mem_dict("foo"), _mem_dict("bar")]})
    out = extract_memories(_turn(), existing_memories=[], model_client=client,
                           session_id="sess-1")
    assert [m.name for m in out] == ["foo", "bar"]

def test_per_turn_cap_is_3():
    client = _fake_json_client({"memories": [_mem_dict(str(i)) for i in range(10)]})
    out = extract_memories(_turn(), existing_memories=[], model_client=client,
                           session_id="sess-1")
    assert len(out) == 3

def test_dedup_against_existing_by_name():
    existing = [_memory(name="foo")]
    client = _fake_json_client({"memories": [_mem_dict("foo"), _mem_dict("bar")]})
    out = extract_memories(_turn(), existing_memories=existing, model_client=client,
                           session_id="sess-1")
    assert [m.name for m in out] == ["bar"]

def test_schema_violation_logged_not_raised(caplog):
    client = _fake_json_client("this is not JSON")
    out = extract_memories(_turn(), existing_memories=[], model_client=client,
                           session_id="sess-1")
    assert out == []
    assert "extractor schema violation" in caplog.text

def test_uses_json_mode_when_provider_supports_it():
    client = _fake_client_with_caps(json_mode=True)
    _ = extract_memories(_turn(), existing_memories=[], model_client=client,
                        session_id="sess-1")
    assert client.last_request_options.get("response_format") == {"type": "json_object"}
```

**Minimal impl.**

```python
# cli/memory/extractor.py
EXTRACTION_PROMPT = """..."""   # provider-neutral, no <thinking> markers

PER_TURN_CAP = 3
PER_SESSION_CAP = 5

def extract_memories(turn: TurnMessage, *, existing_memories: list[Memory],
                     model_client: ModelClient, session_id: str | None,
                     per_turn_cap: int = PER_TURN_CAP) -> list[Memory]:
    """Pure function. Calls model_client.complete() with EXTRACTION_PROMPT,
    parses (strict-JSON on json_mode, lenient otherwise), dedups against
    existing, caps at per_turn_cap, returns list[Memory]. Logs + returns
    [] on any parser error."""
```

**No orchestrator changes.** `extract_memories` is a sync pure call. The background-dispatch wrapper (`dispatch_extraction(orch_state, registry)`) is Phase 2.

**Dependencies.** T5.

---

#### P2.T7 — Memory retrieval (BM25 pure helper)

**Files.** Create `cli/memory/retrieval.py`, `tests/test_memory_retrieval.py`.

**Tests.**

```python
def test_bm25_ranks_exact_name_match_first():
    mems = [_m("alpha"), _m("beta"), _m("gamma")]
    result = find_relevant("beta", mems, k=3)
    assert [m.name for m in result.memories] == ["beta", ...]

def test_recency_tiebreaks_equal_score():
    older = _m("foo", created_at=yesterday)
    newer = _m("foo", created_at=today)
    result = find_relevant("foo", [older, newer], k=1)
    assert result.memories == [newer]

def test_k_zero_returns_nothing():
    assert find_relevant("any", _three_mems(), k=0).memories == []

def test_reasons_trace_includes_score_and_why():
    result = find_relevant("alpha beta", [_m("alpha beta")], k=1)
    assert result.reasons[0].term_hits == {"alpha": 1, "beta": 1}
    assert result.reasons[0].final_score > 0

def test_deterministic_ordering_on_ties():
    # Two identical memories must return in insertion order.
    ...
```

**Minimal impl.**

```python
# cli/memory/retrieval.py
@dataclass(frozen=True)
class RetrievalReason:
    name: str
    term_hits: dict[str, int]
    recency_bonus: float
    final_score: float

@dataclass(frozen=True)
class RetrievalResult:
    memories: list[Memory]
    reasons: list[RetrievalReason]

def find_relevant(query: str, memories: list[Memory], *, k: int = 5,
                  now: datetime | None = None) -> RetrievalResult:
    """BM25 over name + description + body; recency tiebreak; deterministic."""
```

**No orchestrator changes.** Pure. Phase 2 wires it at the pre-model-call seam.

**Dependencies.** T5.

---

#### P2.T8 — `system_prompt.py` accepts `relevant_memories` kwarg

**Files.** Modify `cli/workbench_app/system_prompt.py`. Create `tests/test_system_prompt_memories.py`.

**Tests.**

```python
def test_default_kwarg_preserves_snapshot():
    old = build_system_prompt(workspace_name="ws", agent_card_path=None,
                              registry=_empty_registry())
    new = build_system_prompt(workspace_name="ws", agent_card_path=None,
                              registry=_empty_registry(), relevant_memories=None)
    assert old == new

def test_injects_relevant_memories_section():
    mems = [_m("prefer-terse"), _m("use-uv")]
    out = build_system_prompt(workspace_name="ws", agent_card_path=None,
                              registry=_empty_registry(), relevant_memories=mems)
    assert "## Relevant memories" in out
    assert "- prefer-terse:" in out
    assert "- use-uv:" in out

def test_empty_sequence_renders_no_section():
    out = build_system_prompt(..., relevant_memories=[])
    assert "## Relevant memories" not in out
```

**Existing snapshot invariant.** `tests/test_system_prompt*.py` — verify they still pass byte-stable with the new kwarg defaulted to `None`.

**Minimal impl.**

```python
def build_system_prompt(*, workspace_name, agent_card_path, registry,
                        relevant_memories: Sequence[Memory] | None = None) -> str:
    # … existing body …
    if relevant_memories:
        lines.append("## Relevant memories")
        for m in relevant_memories:
            lines.append(f"- {m.name}: {m.description}")
        lines.append("")
    # injection guard stays last
```

**No orchestrator changes.** The kwarg default is `None`; all existing call sites continue to pass no kwarg.

**Dependencies.** T5.

---

#### P2.T9 — `/uncompact`, `/memory-debug`, `/memory-edit` slash handlers (pure registry)

**Files.** Modify `cli/workbench_app/slash.py` (add three `_BuiltinSpec` entries + three `_handle_*` functions). Modify `cli/workbench_app/commands.py` only if a new field is needed (not expected). Create `tests/test_memory_slash_commands.py`.

**Tests.**

```python
def test_uncompact_reads_archive_and_restores_via_callback(tmp_path):
    # Wire a fake SlashContext with a session + a CompactArchive containing
    # one range. The handler returns a string summary AND calls the injected
    # restore_callback([...messages]). In Phase 1 the restore_callback is a
    # no-op; Phase 2's orchestrator supplies a real one.
    archive = CompactArchive(root=tmp_path, session_id="s1")
    archive.write(3, 17, _sample_messages())
    restored: list[list[TurnMessage]] = []
    ctx = _slash_ctx(session_id="s1", workspace_root=tmp_path.parent,
                     uncompact_callback=restored.append)
    result = _handle_uncompact(ctx)
    assert "restored 14 messages" in result.lower()
    assert len(restored) == 1

def test_uncompact_without_archive_returns_friendly_message(tmp_path):
    ctx = _slash_ctx(session_id="s1", workspace_root=tmp_path)
    result = _handle_uncompact(ctx)
    assert "nothing to uncompact" in result.lower()

def test_memory_debug_shows_injected_memories_with_reasons(tmp_path):
    # Phase 1: handler reads last-retrieval trace from a thread-local set by
    # Phase 2. In Phase 1 with no trace, it prints "no memories injected yet".
    ...

def test_memory_edit_opens_editor_on_resolved_path(tmp_path, monkeypatch):
    # Handler resolves MEMORY.md path via MemoryStore and shells to $EDITOR.
    # Test stubs subprocess.run and asserts argv + cwd.
    ...
```

**Minimal impl.**

```python
# cli/workbench_app/slash.py additions
def _handle_uncompact(ctx: SlashContext, *_: str) -> str: ...
def _handle_memory_debug(ctx: SlashContext, *_: str) -> str: ...
def _handle_memory_edit(ctx: SlashContext, *_: str) -> str: ...

# Added to _BUILTIN_SPECS:
_BuiltinSpec("uncompact",
             "Restore the most recent compaction",
             _handle_uncompact,
             when_to_use="Use when compaction hid a turn you still need."),
_BuiltinSpec("memory-debug",
             "Show which memories were injected this turn and why",
             _handle_memory_debug),
_BuiltinSpec("memory-edit",
             "Open MEMORY.md in $EDITOR",
             _handle_memory_edit,
             argument_hint="[name]"),
```

**`SlashContext` additions (minimal, backward-compatible).** If `SlashContext` lacks a `uncompact_callback` / `memory_last_retrieval` slot today, add them as optional `None` fields. Phase 2's `run_turn` wiring populates them.

**No orchestrator changes.** The slash handlers take callbacks out of `SlashContext`; Phase 2 is where `orchestrator.py` *supplies* those callbacks via `build_workbench_runtime` / wherever `SlashContext` is assembled.

**Dependencies.** T3 (archive reader), T5 (store), T7 (retrieval trace shape).

---

### Phase 2 — Orchestrator integration (deferred; dispatch AFTER P1 merges to master)

#### P2.orch — Wire compaction + extraction + retrieval into `run_turn`

**Files.** Modify `cli/llm/orchestrator.py` — this is the one file we promised not to touch in Phase 1. Modify `cli/workbench_app/orchestrator_runtime.py` to supply the SlashContext callbacks. Modify `cli/settings/schema.py` to add a `Memory` section. Modify `cli/settings/env_bridge.py` to map `AGENTLAB_NO_MEMORY=1` to `memory.enabled = False`. Modify `cli/doctor_sections.py` (or wherever `/doctor` composes) to add the memory telemetry section.

**Dependencies.** All of T1–T9. **P1 merged to master and rebased into this branch.**

**Tasks in dispatch order.**

1. **Rebase onto post-P1 master.** Resolve any conflicts in `run_turn` from P1's streaming changes first. Only then proceed.
2. **Settings schema.** Add `Memory(enabled: bool = True, per_session_cap: int = 5, compaction_threshold_ratio: float = 0.8)` to `Settings`. Env bridge: `AGENTLAB_NO_MEMORY=1 → memory.enabled = False`. Test: `tests/test_settings_memory.py`.
3. **Compaction hook in `run_turn`.** Right after the assistant-turn `TurnMessage` is appended (line 167–169 today), call `should_compact(self.messages, budget, token_counter=_counter_for(self.model))`. If true: `start, end = choose_compact_range(...)`; build the cheap client; `digest = digest_tool_phase(self.messages[start:end], ...)`; `archive.write(start, end, self.messages[start:end])`; replace the slice in `self.messages` with `build_boundary_message(start=start, end=end, digest_text=digest.text)`; `transcript.append_compact_boundary(...)`. Test: `tests/test_compaction_flow.py` drives a long transcript and asserts (a) boundary inserted, (b) archive written, (c) `/uncompact` restores byte-for-byte.
4. **Memory retrieval at pre-model-call seam.** Inside `_run_model_turn` (or in `run_turn` just before it's called), compute `retrieval = find_relevant(user_prompt, store.list(), k=settings.memory.top_k)`; thread `retrieval.memories` into `build_system_prompt` via a new `self.system_prompt_builder` callable that the runtime supplies. Populate `SlashContext.memory_last_retrieval = retrieval` for `/memory-debug`.
5. **Memory extraction dispatch post-turn.** At the post-turn seam (near `_fire_session_end_hook`, line 226), spawn extraction via `BackgroundTaskRegistry.register(description="memory extraction", owner="memory")`; in a `threading.Thread`, call `extract_memories(turn, existing_memories=store.list(), model_client=cheap_client, session_id=...)`, `store.write` each, then `registry.update(task_id, status=COMPLETED)`. Guard with `if settings.memory.enabled`. Test: `tests/test_memory_dispatch.py` — fake registry, fake extractor, assert the background task is registered and completes.
6. **`/uncompact` callback wiring.** In `build_workbench_runtime`, pass a `uncompact_callback` into `SlashContext` that mutates `orchestrator.messages` and re-renders transcript.
7. **`/doctor` section.** Append "Memory: N files at <path>. Extraction errors: M. Sent <total> memories to <provider> last 24h." to `cli/doctor_sections.py`. Test: `tests/test_doctor_memory_section.py`.
8. **Manual dogfood.** Drive a long conversation past threshold on each of the three providers. Confirm: boundary renders; `/uncompact` round-trips; MEMORY.md accumulates reasonable entries; `AGENTLAB_NO_MEMORY=1` disables both paths.

**Commit shape.** One commit per sub-step above, conventional prefix. Final commit: `feat(orchestrator): wire P2 compaction + memory extraction into run_turn`.

---

## Shared test fixtures

Create `tests/conftest_compaction.py` (or a module under `tests/_helpers/`):

- `_make_transcript(n_turns, total_tokens)` — synthesises `TurnMessage` lists with known token counts.
- `_exact_counter(content)` — sums lengths exactly; used as `token_counter` kwarg.
- `_make_transcript_with_boundary()` — includes one `build_boundary_message(...)` entry.
- `_sample_messages()` — canonical 14-message tool phase (mixed text + tool_result blocks).
- `_fake_json_client(payload)` — minimal `ModelClient` that returns JSON; records `last_request_options` for json_mode assertions.
- `_memory(name=..., body=..., created_at=..., type="project")` — one-liner factory.

---

## Invariants

1. `tests/test_system_prompt*.py` must stay byte-stable — new `relevant_memories` kwarg defaults `None`.
2. Compaction is reversible via `/uncompact`. Archive files never auto-deleted within 30 days.
3. Compaction never touches the most recent `min_retained_turns` (default 4).
4. Memory extraction is non-blocking — dispatched via `BackgroundTaskRegistry` + a thread, never inline.
5. `AGENTLAB_NO_MEMORY=1` short-circuits both extraction and retrieval (via `Settings.memory.enabled`).
6. `MEMORY.md` index stays under 200 lines (overflow → `MEMORY.archive.md`).
7. Memory dedup by exact `name` match — update-in-place, one file per memory.
8. **No changes to `cli/llm/orchestrator.py` during Phase 1.** Phase 1 PR touches only: `cli/llm/compaction.py`, `cli/llm/digests.py`, `cli/llm/compact_archive.py`, `cli/memory/**`, `cli/workbench_app/transcript.py`, `cli/workbench_app/system_prompt.py`, `cli/workbench_app/slash.py`, plus `tests/`.
9. Provider-neutral prompts — no `<thinking>` or provider-specific markers in the digest or extraction prompts.
10. Cost transparency — both forked calls (digest + extraction) flow through the same `cost_calculator` path so `/doctor` and the status-bar drawer see them.

---

## Out of scope

- Classifier / auto-approval (P3).
- MCP transports (P3).
- Session JSONL (P4 — already landing in parallel).
- Embeddings / semantic memory search (future upgrade).
- Compressing the MEMORY index into a single file — we keep one-file-per-memory to mirror the user's live system.
- `cli/project_instructions/loader.py` — does not exist; we don't create it. Memory retrieval injects directly through `build_system_prompt`, not through an AGENTLAB.md-style loader.
