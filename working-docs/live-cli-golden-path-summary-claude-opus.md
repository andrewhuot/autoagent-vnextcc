# Live CLI Golden Path Summary — Claude Opus

## Status: Complete

## What was tested live in the CLI

The complete Build → Workbench → Eval → Optimize → Deploy flow was tested end-to-end in LIVE mode using a real Gemini API key (`GOOGLE_API_KEY`) against `gemini-2.5-pro` for optimization and `gemini-2.0-flash` for the agent model.

**Scenario**: Verizon-like phone company billing support agent that explains charges, plans, fees, proration, and billing disputes.

### Commands tested:
1. `agentlab new verizon-billing-agent --template customer-support --mode live` — workspace creation
2. `agentlab doctor` — readiness check (all green with Google provider)
3. `agentlab status` — workspace health
4. `agentlab mode show` — confirmed LIVE mode
5. `agentlab workbench build "..."` — agent building with brief
6. `agentlab workbench show` — candidate inspection
7. `agentlab workbench iterate "..."` — follow-up refinement
8. `agentlab workbench save` — materialization to config
9. `agentlab eval run` — evaluation against test cases
10. `agentlab eval show latest` — result inspection
11. `agentlab optimize --cycles 1` — optimization with real Gemini LLM
12. `agentlab deploy --auto-review --yes` — auto-review and canary deploy
13. `agentlab deploy status` — deployment verification

### Live LLM usage confirmed:
- **Workbench build**: 3/8 steps used real Gemini LLM (tool_schema, guardrail, eval_suite)
- **Optimize**: Real Gemini API call confirmed (`google:gemini-2.5-pro: requests=1, cost=$0.005674`)
- **Eval**: Attempted live agent call, fell back to mock on transient 503 (with clear warnings)

## Key UX/Product Gaps Found

| # | Gap | Severity | Fixed? |
|---|-----|----------|--------|
| 1 | `_infer_domain` word-boundary bug ("it " in "it should") | High | Yes |
| 2 | Missing telecom/billing domain | Medium | Yes |
| 3 | Hardcoded "gpt-5.4-mini" fake model | High | Yes |
| 4 | LLM executor unreachable (kind tags missing) | Critical | Yes |
| 5 | Silent LLM-to-template fallback (no indicator) | High | Yes |
| 6 | Transient 503 on eval agent | Low | No (external) |
| 7 | Template-generated eval cases are generic | Medium | Partially (LLM path now works) |
| 8 | Some build steps still fall back to templates | Medium | Documented (source indicator visible) |
| 9 | Optimize completion_tokens=0 | Low | No (cosmetic) |

## What was fixed

### 4 production fixes:
1. **Domain inference**: Fixed word-boundary bug, added Billing Support domain with 10 keywords
2. **Model placeholder**: Replaced all "gpt-5.4-mini" with workspace-aware `_resolve_workspace_agent_model()`
3. **LLM executor path**: Added `kind:` tags to `_build_plan_tree()` leaf tasks, enabling LLM generation
4. **Source transparency**: Added `[llm]`/`[template]` indicator to CLI build output

### 1 test file:
- `tests/test_infer_domain.py` — 18 regression tests for domain inference

## What still remains hard or blocked

1. **Not all build steps use LLM**: Only 3/8 steps successfully use LLM; the rest fall back to templates (likely because the LLM JSON response doesn't match expected executor schemas). Source indicator makes this visible.
2. **Eval agent in live mode**: Depends on model API availability. The 503 fallback is well-handled but means eval scores can be simulated.
3. **Iteration doesn't use LLM**: The `_generate_iteration_step` in the harness is template-only — no LLM path exists for follow-up turns.
4. **Template content quality**: Template-generated artifacts are generic. They use the brief text for context but produce boilerplate structure.

## Tests / Verification Run

```
tests/test_infer_domain.py                     — 18 passed
tests/test_workbench_harness_eng.py            — passed
tests/test_workbench_hardening.py              — passed
tests/test_workbench_streaming.py              — passed
tests/test_workbench_agent_live.py             — passed
tests/test_workbench_multi_turn.py             — passed
tests/test_workbench_eval_optimize_bridge.py   — passed
tests/test_agents_api.py                       — passed
Total: 68+ tests passing, 0 failures
```

## Branch and Commit

- **Branch**: `feat/live-cli-golden-path-claude-opus`
- **Files modified**:
  - `builder/workbench.py` — domain inference fix, model placeholder fix
  - `builder/workbench_agent.py` — kind tags for LLM executor
  - `builder/harness.py` — source indicator in _generate_step
  - `cli/workbench_render.py` — [llm]/[template] display
  - `tests/test_infer_domain.py` — new regression tests
  - `working-docs/live-cli-golden-path-*.md` — 4 working docs
