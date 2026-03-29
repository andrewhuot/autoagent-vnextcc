# Natural Language Intelligence Layer Brief

## Mission
Build 6 features that make AutoAgent conversational, composable, and accessible from any AI coding tool. This is the "intelligence API" layer — every feature below is a different interface to the same underlying optimization engine.

## Current State
- 1,705 tests, master at commit `2bf902e`
- Existing: proposer, change cards, eval runner, blame map, observer, CLI, API, web console
- All features below are ADDITIVE — don't restructure existing code

---

## Feature 1: `autoagent edit "..."` — Natural Language Config Editing

### CLI
```bash
autoagent edit "Make the billing agent more empathetic when handling refund requests"
autoagent edit "Add a step to confirm refund amount before processing"
autoagent edit "Reduce response verbosity for simple FAQ questions"
autoagent edit --interactive    # Multi-turn REPL
```

### Implementation

**Create `optimizer/nl_editor.py`** (~250 lines):
```python
@dataclass
class EditIntent:
    """Parsed intent from natural language edit request."""
    description: str
    target_surfaces: list[str]      # Identified surfaces to modify
    change_type: str                # "instruction_edit", "example_add", "config_change", etc.
    constraints: list[str]          # Inferred constraints ("maintain safety", etc.)

@dataclass  
class EditResult:
    """Result of applying an NL edit."""
    original_config: dict
    new_config: dict
    change_description: str
    diff_summary: str
    score_before: float
    score_after: float
    accepted: bool

class NLEditor:
    """Translates natural language descriptions into config changes."""
    
    def parse_intent(self, description: str, current_config: dict) -> EditIntent:
        """Parse NL description into structured edit intent."""
        # In mock mode: keyword matching against surface names
        # In LLM mode: structured output from proposer
    
    def generate_edit(self, intent: EditIntent, current_config: dict) -> dict:
        """Generate the edited config based on intent."""
    
    def apply_and_eval(self, description: str, current_config: dict, 
                       eval_runner, deployer) -> EditResult:
        """Full pipeline: parse → generate → eval → present."""
```

**Mock mode behavior** (no LLM needed):
- Keyword match: "billing" → surfaces containing "billing"
- Keyword match: "safety" → surfaces containing "safety" or "guardrail"
- Keyword match: "latency"/"slow"/"timeout" → generation_settings, tool timeouts
- Keyword match: "routing"/"misroute" → routing.rules
- Keyword match: "empathetic"/"tone"/"friendly" → instructions (tone adjustment)
- Keyword match: "example"/"few-shot" → examples surface
- Apply the matched mutation type from the skill registry

**CLI in `runner.py`**:
```python
@cli.command("edit")
@click.argument("description", required=False)
@click.option("--interactive", "-i", is_flag=True, help="Multi-turn editing session")
@click.option("--dry-run", is_flag=True, help="Show proposed changes without applying")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
```

**Interactive mode**: A REPL loop using `click.prompt()`:
```
AutoAgent Edit (type 'quit' to exit)
> Make billing responses shorter
  Identified surfaces: instructions.billing_agent, examples.refund_flow
  [shows diff]
  Eval: 0.84 → 0.85 (+0.01)
  Apply? [y/n/refine]: refine
> Also make the tone warmer
  [shows incremental diff]
  Eval: 0.85 → 0.87 (+0.02)  
  Apply? [y/n/refine]: y
  ✓ Applied. Config version: v008
```

### API
```
POST /api/edit    { "description": "...", "dry_run": false }
  → { "intent": {...}, "diff": "...", "score_before": 0.84, "score_after": 0.86, "applied": true }
```

### Tests
- Test intent parsing (keyword → surface mapping)
- Test edit generation (mock mode produces valid config)
- Test interactive session flow

---

## Feature 2: `--json` Flags on All Key Commands

Add `--json` / `-j` flag to these existing commands that outputs structured JSON to stdout:

```bash
autoagent status --json
autoagent explain --json
autoagent replay --json
autoagent eval run --json
autoagent optimize --json
autoagent cx status --json
autoagent adk status --json
autoagent skill list --json
autoagent skill recommend --json
autoagent agent-skills analyze --json
```

Implementation:
- Each command checks `if json_output:` early and prints `json.dumps(data, indent=2)` instead of formatted text
- The data dict should match the API response schema where possible
- This enables piping: `autoagent status --json | jq '.score'`

This is straightforward — just add the flag and a JSON serialization path to each command. Modify runner.py throughout.

---

## Feature 3: `autoagent diagnose --interactive` — Conversational Diagnosis

### Create `optimizer/diagnose_session.py` (~300 lines):

```python
class DiagnoseSession:
    """Interactive diagnosis and fix session."""
    
    def __init__(self, store, observer, proposer, eval_runner, deployer, nl_editor):
        self.clusters = []
        self.focused_cluster = None
        self.pending_change = None
        self.history = []
    
    def start(self) -> str:
        """Run analysis, cluster failures, return formatted summary."""
    
    def handle_input(self, user_input: str) -> str:
        """Process user message and return response."""
        intent = self._classify_input(user_input)
        if intent == "drill_down":
            return self._show_cluster_detail(...)
        elif intent == "show_examples":
            return self._show_conversations(...)
        elif intent == "fix":
            return self._generate_fix(...)
        elif intent == "apply":
            return self._apply_change(...)
        elif intent == "next":
            return self._next_cluster(...)
```

**Input classification** (keyword-based, no LLM):
- "tell me more" / "details" / "drill down" / "cluster N" → show cluster detail
- "show examples" / "show conversations" / "evidence" → retrieve sample conversations
- "fix" / "fix it" / "fix this" / "resolve" → generate proposal via NL editor
- "apply" / "yes" / "ship it" / "deploy" → apply pending change
- "next" / "what else" / "other issues" → move to next cluster
- "skip" / "ignore" → skip current cluster
- "summary" / "status" → show current state
- "quit" / "exit" / "done" → end session

**CLI**:
```python
@cli.command("diagnose")
@click.option("--interactive", "-i", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
```

Non-interactive mode: just prints the cluster analysis (like explain but focused on failures).
Interactive mode: REPL with the DiagnoseSession.

---

## Feature 4: Enhanced AUTOAGENT.md Auto-Update

Modify the existing `core/project_memory.py` to auto-update AUTOAGENT.md with live intelligence:

### Add `update_with_intelligence()` method to ProjectMemory:
```python
def update_with_intelligence(self, report, eval_score, recent_changes, skill_gaps):
    """Update AUTOAGENT.md with current agent intelligence."""
    # Appends/updates these sections:
    # ## Current Health (auto-updated)
    # ## Active Issues (auto-updated)
    # ## Recent Changes (auto-updated)
    # ## Skill Gaps (auto-updated)
    # ## Optimization History (auto-updated)
```

### Call this from:
- End of every `autoagent optimize` cycle
- End of `autoagent quickstart`
- End of `autoagent edit`
- When `autoagent diagnose` applies a fix

### The auto-updated sections should be clearly marked:
```markdown
<!-- BEGIN AUTOAGENT INTELLIGENCE — auto-updated, do not edit -->
## Current Health
Score: 0.87 | Safety: 1.00 | Routing: 94% | Latency: 2.1s
Last updated: 2025-03-25 02:15 UTC

## Active Issues
1. 🟡 Billing routing: 6% miss rate — keywords may need expansion
2. 🟢 Safety: zero violations (resolved in v005)

## Recent Changes  
- v007 (+0.02): Tightened safety guardrails for pricing queries
- v006 (+0.03): Reduced tool timeout from 10s to 5s
- v005 (+0.07): Fixed billing routing keywords

## Skill Gaps
- No warranty lookup tool (8 user requests, 0 handled)
- No Spanish support sub-agent (5 user requests, 0 handled)
<!-- END AUTOAGENT INTELLIGENCE -->
```

The markers ensure auto-update only touches the intelligence section, preserving user-written content above.

---

## Feature 5: MCP Server (`autoagent mcp-server`)

### Create `mcp_server/` module:

```
mcp_server/
├── __init__.py
├── server.py           # MCP server implementation
├── tools.py            # Tool definitions
└── types.py            # MCP-specific types
```

### MCP Tools to Expose:

```python
# 1. Status & Health
@tool
def autoagent_status() -> dict:
    """Get current agent health, scores, and failure summary."""

@tool  
def autoagent_explain() -> str:
    """Get a plain-English summary of the agent's current state."""

# 2. Diagnosis
@tool
def autoagent_diagnose() -> dict:
    """Run failure analysis and return clustered issues with root causes."""

@tool
def autoagent_get_failures(failure_family: str, limit: int = 5) -> list[dict]:
    """Get sample conversations for a specific failure type."""

# 3. Editing
@tool
def autoagent_suggest_fix(description: str) -> dict:
    """Suggest a config fix based on natural language description. Returns diff and expected impact."""

@tool
def autoagent_edit(description: str, auto_apply: bool = False) -> dict:
    """Apply a natural language edit to the agent config. Returns change card with eval results."""

# 4. Evaluation
@tool
def autoagent_eval(config_path: str | None = None) -> dict:
    """Run eval suite and return scores."""

@tool
def autoagent_eval_compare(config_a: str, config_b: str) -> dict:
    """Compare two configs via eval and return winner."""

# 5. Skills & Gaps
@tool
def autoagent_skill_gaps() -> list[dict]:
    """Identify capabilities the agent is missing based on failure analysis."""

@tool
def autoagent_skill_recommend() -> list[dict]:
    """Recommend optimization skills based on current failure patterns."""

# 6. History
@tool  
def autoagent_replay(limit: int = 10) -> list[dict]:
    """Get optimization history showing config evolution."""

@tool
def autoagent_diff(version_a: int, version_b: int) -> str:
    """Get unified diff between two config versions."""
```

### Server Implementation

Use the MCP Python SDK (`mcp` package). The server runs as a stdio process:

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server

app = Server("autoagent")

@app.tool()
async def autoagent_status() -> dict:
    ...
```

### CLI Command:
```bash
autoagent mcp-server                    # Start MCP server (stdio mode)
autoagent mcp-server --port 8081        # Start in HTTP/SSE mode
```

### Claude Code Integration:
Users add to their `.claude/config.json` or project's `.mcp.json`:
```json
{
  "mcpServers": {
    "autoagent": {
      "command": "autoagent",
      "args": ["mcp-server"]
    }
  }
}
```

### Codex Integration:
Users add to `.codex/config.toml`:
```toml
[mcp_servers.autoagent]
command = "autoagent"
args = ["mcp-server"]
```

### Tests
- Test each tool function returns valid structured data
- Test server starts without errors
- Test tool schemas are valid MCP format

---

## Feature 6: Web Chat Panel for Diagnosis

### Create `web/src/components/DiagnosisChat.tsx` (~250 lines):
A chat-style panel that connects to the diagnose API:

- Fixed to the bottom-right of the Dashboard (like an intercom widget)
- Click to expand into a chat panel
- Messages alternate between user and AutoAgent
- AutoAgent messages can contain: text, code blocks (diffs), metric cards, action buttons
- Action buttons: "Apply Fix", "Show Examples", "Next Issue", "Skip"
- When a fix is applied, show a success toast with score improvement

### API Endpoint:
```
POST /api/diagnose/chat
  Body: { "message": "tell me more about cluster 1", "session_id": "..." }
  Response: { "response": "...", "actions": [...], "clusters": [...], "session_id": "..." }
```

The API creates/retrieves a DiagnoseSession and routes the message through `handle_input()`.

### Chat Message Types:
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
```

---

## Implementation Tracks for Sub-Agents

**Track A — NL Editor**: `optimizer/nl_editor.py`, edit CLI command, `/api/edit` endpoint, tests (~400 lines)
**Track B — JSON Flags**: Add `--json` to 10+ existing commands in runner.py, tests (~300 lines modified)  
**Track C — Diagnose Session**: `optimizer/diagnose_session.py`, diagnose CLI command, `/api/diagnose/chat`, tests (~400 lines)
**Track D — AUTOAGENT.md Intelligence**: Modify `core/project_memory.py`, hook into optimize/edit/quickstart, tests (~200 lines)
**Track E — MCP Server**: `mcp_server/server.py`, `mcp_server/tools.py`, CLI command, tests (~500 lines)
**Track F — Web Chat Panel**: `web/src/components/DiagnosisChat.tsx`, Dashboard integration, types/api, tests (~300 lines)

## Dependency Layer Classification
- `optimizer/nl_editor.py` → Layer 1
- `optimizer/diagnose_session.py` → Layer 1
- `mcp_server/` → Layer 2 (surface — it imports from everything)
- Update `tests/test_dependency_layers.py`

## Quality Bar
- `python3 -m pytest tests/ -x -q` — must pass with more tests than 1,705
- `cd web && npx tsc --noEmit` — must pass
- `python3 -m pytest tests/test_dependency_layers.py -v` — must pass
- `autoagent edit "fix routing" --dry-run` must work end-to-end
- `autoagent diagnose` (non-interactive) must print cluster analysis
- MCP server must start and expose tools

## When Done
Commit: `feat: NL intelligence layer — edit, diagnose, MCP server, JSON output, AUTOAGENT.md, chat panel`
Push to master.
Run: `openclaw system event --text "Done: NL intelligence layer — 6 features, MCP server, conversational diagnosis" --mode now`
