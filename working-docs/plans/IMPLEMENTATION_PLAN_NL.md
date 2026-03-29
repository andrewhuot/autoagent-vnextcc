# NL Intelligence Layer — Implementation Plan

## Overview
6 features that make AutoAgent conversational, composable, and accessible from any AI coding tool.

---

## Feature 1: NL Editor (`optimizer/nl_editor.py`)

### Keyword → Surface Mapping Table

| Keywords | Target Surface | Change Type |
|---|---|---|
| billing, refund, payment, invoice | `routing.rules` (billing specialist) | `instruction_edit` |
| safety, guardrail, harmful, violation | `prompts.root` (safety instructions) | `instruction_edit` |
| latency, slow, timeout, fast, speed | `thresholds`, `tools.*.timeout_ms` | `config_change` |
| routing, misroute, wrong agent, transfer | `routing.rules` | `config_change` |
| empathetic, tone, friendly, warm, polite | `prompts.root` (tone adjustment) | `instruction_edit` |
| example, few-shot, sample, demo | `examples` | `example_add` |
| verbose, concise, short, brief, length | `prompts.root` (verbosity) | `instruction_edit` |
| quality, accurate, correct, thorough | `prompts.root` (quality) | `instruction_edit` |
| cost, expensive, cheap, token, budget | `thresholds`, `generation_settings` | `config_change` |

### Interfaces

```python
# optimizer/nl_editor.py

@dataclass
class EditIntent:
    description: str
    target_surfaces: list[str]
    change_type: str  # instruction_edit | example_add | config_change
    constraints: list[str]

@dataclass
class EditResult:
    original_config: dict
    new_config: dict
    change_description: str
    diff_summary: str
    score_before: float
    score_after: float
    accepted: bool

class NLEditor:
    def __init__(self, proposer: Proposer, eval_runner: EvalRunner | None = None):
        ...

    def parse_intent(self, description: str, current_config: dict) -> EditIntent:
        """Keyword-based intent parsing (no LLM needed)."""

    def generate_edit(self, intent: EditIntent, current_config: dict) -> dict:
        """Generate edited config based on intent."""

    def apply_and_eval(self, description: str, current_config: dict,
                       eval_runner: EvalRunner | None = None,
                       deployer: Deployer | None = None) -> EditResult:
        """Full pipeline: parse → generate → eval → present."""

    def to_dict(self, result: EditResult) -> dict:
        """Serialize EditResult for JSON output."""
```

### CLI (`runner.py`)
```python
@cli.command("edit")
@click.argument("description", required=False)
@click.option("--interactive", "-i", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
```

### API (`api/routes/edit.py`)
```python
POST /api/edit  { "description": "...", "dry_run": false }
→ { "intent": {...}, "diff": "...", "score_before": 0.84, "score_after": 0.86, "applied": true }
```

---

## Feature 2: JSON Flags on Existing Commands

### Commands to modify in `runner.py`:
1. `status` — add `--json` flag, output health/config/failures as JSON
2. `explain` — add `--json` flag, output prose + metrics as JSON
3. `replay` — add `--json` flag, output optimization history as JSON array
4. `eval run` — add `--json` flag, output scores as JSON
5. `optimize` — add `--json` flag, output cycle results as JSON
6. `cx status` — add `--json` flag (renamed from adk status pattern)
7. `adk status` — add `--json` flag
8. `skill list` — add `--json` flag
9. `skill recommend` — add `--json` flag
10. `agent-skills analyze` — new CLI command with `--json`

### Pattern:
```python
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def some_command(..., json_output: bool):
    # ... gather data ...
    if json_output:
        click.echo(json.dumps(data, indent=2))
        return
    # ... existing formatted output ...
```

---

## Feature 3: Diagnose Session (`optimizer/diagnose_session.py`)

### Interfaces
```python
@dataclass
class DiagnoseCluster:
    cluster_id: str
    failure_type: str
    count: int
    impact_score: float
    description: str
    example_ids: list[str]
    trend: str

class DiagnoseSession:
    def __init__(self, store, observer, proposer, eval_runner, deployer, nl_editor):
        self.clusters: list[DiagnoseCluster] = []
        self.focused_cluster: DiagnoseCluster | None = None
        self.pending_change: dict | None = None
        self.history: list[dict] = []
        self.session_id: str = uuid.uuid4().hex[:12]

    def start(self) -> str:
        """Run analysis, cluster failures, return formatted summary."""

    def handle_input(self, user_input: str) -> str:
        """Process user message and return response."""

    def _classify_input(self, text: str) -> str:
        """Keyword-based intent classification."""

    def to_dict(self) -> dict:
        """Serialize session state for JSON/API output."""
```

### Input Classification Table
| Keywords | Intent |
|---|---|
| tell me more, details, drill down, cluster N | `drill_down` |
| show examples, show conversations, evidence | `show_examples` |
| fix, fix it, fix this, resolve | `fix` |
| apply, yes, ship it, deploy | `apply` |
| next, what else, other issues | `next` |
| skip, ignore | `skip` |
| summary, status | `summary` |
| quit, exit, done | `quit` |

### CLI
```python
@cli.command("diagnose")
@click.option("--interactive", "-i", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
```

### API
```python
POST /api/diagnose/chat  { "message": "...", "session_id": "..." }
→ { "response": "...", "actions": [...], "clusters": [...], "session_id": "..." }
```

---

## Feature 4: AUTOAGENT.md Auto-Update (`core/project_memory.py`)

### New method on `ProjectMemory`:
```python
def update_with_intelligence(self, report: dict, eval_score: float,
                             recent_changes: list[dict], skill_gaps: list[dict]) -> None:
    """Update AUTOAGENT.md with current agent intelligence.

    Manages content between sentinel markers:
    <!-- BEGIN AUTOAGENT INTELLIGENCE — auto-updated, do not edit -->
    ...
    <!-- END AUTOAGENT INTELLIGENCE -->
    """
```

### Integration points:
- End of `autoagent optimize` cycle (runner.py optimize command)
- End of `autoagent edit` (runner.py edit command)
- When `autoagent diagnose` applies a fix

---

## Feature 5: MCP Server (`mcp_server/`)

### Module structure:
```
mcp_server/
├── __init__.py
├── server.py      # MCP server with stdio_server
├── tools.py       # 12 tool functions
└── types.py       # MCP-specific types
```

### Tool Schemas:
```python
# Status & Health
autoagent_status() -> dict          # health, scores, failures
autoagent_explain() -> str          # plain-English summary

# Diagnosis
autoagent_diagnose() -> dict        # clustered issues with root causes
autoagent_get_failures(failure_family: str, limit: int = 5) -> list[dict]

# Editing
autoagent_suggest_fix(description: str) -> dict    # diff + expected impact
autoagent_edit(description: str, auto_apply: bool = False) -> dict

# Evaluation
autoagent_eval(config_path: str | None = None) -> dict
autoagent_eval_compare(config_a: str, config_b: str) -> dict

# Skills & Gaps
autoagent_skill_gaps() -> list[dict]
autoagent_skill_recommend() -> list[dict]

# History
autoagent_replay(limit: int = 10) -> list[dict]
autoagent_diff(version_a: int, version_b: int) -> str
```

### CLI:
```python
@cli.command("mcp-server")
@click.option("--port", default=None, type=int, help="HTTP/SSE port (default: stdio)")
```

---

## Feature 6: Web Chat Panel (`web/src/components/DiagnosisChat.tsx`)

### Types (`web/src/lib/types.ts`):
```typescript
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  metadata?: {
    type?: 'text' | 'diff' | 'metrics' | 'action';
    diff?: string;
    metrics?: { before: number; after: number };
    actions?: { label: string; action: string }[];
  };
}

interface DiagnoseChatResponse {
  response: string;
  actions: { label: string; action: string }[];
  clusters: any[];
  session_id: string;
}
```

### API hook (`web/src/lib/api.ts`):
```typescript
export function useDiagnoseChat() {
  return useMutation({
    mutationFn: (data: { message: string; session_id?: string }) =>
      fetchApi<DiagnoseChatResponse>('/diagnose/chat', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
  });
}
```

---

## Dependency Layer Updates

Add to `tests/test_dependency_layers.py`:
- `optimizer.nl_editor` → Layer 1
- `optimizer.diagnose_session` → Layer 1
- `mcp_server` → Layer 2

---

## Quality Bar
- `python3 -m pytest tests/ -x -q` — must pass with >1,705 tests
- `cd web && npx tsc --noEmit` — must pass
- `python3 -m pytest tests/test_dependency_layers.py -v` — must pass
- `autoagent edit "fix routing" --dry-run` must work end-to-end
- `autoagent diagnose` must print cluster analysis
