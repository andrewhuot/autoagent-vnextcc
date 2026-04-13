# Live CLI Golden Path Issues — Claude Opus

## Issue Log

### ISSUE-001: `_infer_domain` word-boundary bug [FIXED]
- **Severity**: High (breaks domain inference for most briefs)
- **Location**: `builder/workbench.py:423-444`
- **Description**: The check `"it " in lowered` matched "it " as a substring in any brief containing phrases like "it should", "it helps", "it can". A Verizon billing agent brief was misclassified as "IT Helpdesk" because "it should help explain..." contained "it ".
- **Impact**: Wrong agent name, wrong tool names, wrong domain context for the entire build.
- **Fix**: Changed to `re.search(r"\bit\s+(support|helpdesk|help desk|department|team|infrastructure|service)", lowered)` which requires IT-specific context words.
- **Status**: Fixed + regression tests added (18 tests in `tests/test_infer_domain.py`)

### ISSUE-002: Missing telecom/billing domain pattern [FIXED]
- **Severity**: Medium (billing/telecom agents fell through to generic "Agent")
- **Location**: `builder/workbench.py:423-444`
- **Description**: No domain pattern existed for phone company, billing, telecom, wireless, or similar agent briefs. These all mapped to the generic "Agent" domain.
- **Fix**: Added "Billing Support" domain with keywords: billing, phone company, telecom, mobile plan, phone plan, wireless, cell phone, monthly bill, charges, invoice.
- **Status**: Fixed + tested

### ISSUE-003: Hardcoded "gpt-5.4-mini" model placeholder [FIXED]
- **Severity**: High (fake model name shown in all workbench builds)
- **Location**: `builder/workbench.py` (6 occurrences)
- **Description**: The canonical model default was hardcoded to "gpt-5.4-mini" — a non-existent model. This appeared in all workbench builds, config exports, and generated code, regardless of what model was actually configured in the workspace.
- **Fix**: Added `_resolve_workspace_agent_model()` that reads the workspace's active config model and falls back to "gemini-2.0-flash". Replaced all 6 occurrences.
- **Status**: Fixed. All existing tests pass.

### ISSUE-004: LLM executor unreachable in workbench builds [FIXED]
- **Severity**: Critical (LLM was never used for any build step content)
- **Location**: `builder/workbench_agent.py:302-355`, `builder/harness.py:663-730`
- **Description**: The harness `_try_llm_step()` requires a `kind:` tag in each plan task's log to dispatch LLM generation. But `_build_plan_tree()` created tasks without any `kind:` tags, making `_infer_kind_from_leaf()` always return None. The LLM executor path was architecturally complete but completely unreachable.
- **Fix**: Added `kind=` parameter to the `task()` helper in `_build_plan_tree()` and tagged each leaf with the appropriate executor kind: role, instructions, tool_schema, tool_source, guardrail, environment, eval_suite.
- **Status**: Fixed. 3 of 8 build steps now use LLM (tool_schema, guardrail, eval_suite confirmed).

### ISSUE-005: Silent LLM-to-template fallback [FIXED]
- **Severity**: High (no way to know if LLM or template content was used)
- **Location**: `builder/harness.py:631-661`
- **Description**: When `_try_llm_step()` failed or returned None, the harness silently fell back to `_template_execute()`. The user had no indication whether build artifacts were LLM-generated or template-generated. The bare `except Exception: pass` swallowed all errors.
- **Fix**: Added a 4th return value ("source") to `_generate_step()` — either "llm" or "template". Surfaced it in the `task.completed` event data and the CLI renderer now shows `[llm]` or `[template]` after each completed task.
- **Status**: Fixed + verified in final golden path run.

### ISSUE-006: Eval agent provider 503 (transient) [NOT FIXED — external]
- **Severity**: Low (gracefully handled by system)
- **Description**: During eval run, the eval harness tried to call gemini-2.0-flash as the agent model but got `HTTP Error 503: Service Unavailable`. The system correctly fell back to mock agent responses with clear warnings: "MIXED MODE - live fallback to mock".
- **Impact**: Eval scores are simulated when this happens. The optimizer still uses real Gemini for proposals.
- **Status**: External/transient. The fallback behavior is correct and well-communicated.

### ISSUE-007: Generated eval cases are generic [NOT FIXED — template quality]
- **Severity**: Medium
- **Description**: Template-generated eval cases produce generic content like "I need help with request" rather than domain-specific billing test cases. LLM-generated eval cases are better (e.g., "Billing Inquiries" suite with 3 specific cases).
- **Status**: Partially addressed by ISSUE-004 fix (LLM now generates eval cases). Template fallback still produces generic cases.

### ISSUE-008: Some build steps still fall back to templates despite LLM availability
- **Severity**: Medium
- **Description**: After ISSUE-004 fix, 3/8 steps use LLM while 5/8 still use templates. The role, instructions, tool_source, sensitive flows, and environment steps fall back because either the LLM response doesn't parse as expected JSON or the executor schemas don't match.
- **Status**: Documented. The `[template]`/`[llm]` indicator now makes this visible.

### ISSUE-009: Optimize completion_tokens always 0
- **Severity**: Low (cosmetic — cost tracking affected)
- **Description**: The optimizer cost summary shows `completion_tokens=0` even though the LLM clearly generated a response. Likely a tracking bug in how Gemini responses report token usage.
- **Status**: Not fixed — cosmetic issue.
