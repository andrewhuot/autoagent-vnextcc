# Platform Features Brief — 7 Features

Read README.md, ARCHITECTURE_OVERVIEW.md, and the full codebase structure before implementing anything. These 7 features must integrate cohesively with the existing product.

## Implementation Order

Plan first. Read the codebase. Understand the existing architecture. Then implement in dependency order.

---

## Feature 1: Simulation Sandbox

Generate realistic synthetic conversations and stress-test agent configs before deploying.

**Backend:**
- `simulator/sandbox.py` — `SimulationSandbox` class
  - `generate_conversations(domain, count, difficulty_distribution)` — generate realistic test conversations using LLM
  - `stress_test(config, conversations)` — run config against generated conversations in isolation
  - `compare(config_a, config_b, conversations)` — A/B comparison on same conversation set
  - Difficulty distribution: 60% normal, 25% edge cases, 15% adversarial
  - Domain-aware generation (uses agent's existing intents, tools, routing to create realistic scenarios)
- `simulator/persona.py` — synthetic user personas (angry customer, confused customer, technical user, multi-intent user, etc.)
- `api/routes/sandbox.py` — REST endpoints
  - `POST /api/sandbox/generate` — generate conversation set
  - `POST /api/sandbox/test` — run stress test
  - `POST /api/sandbox/compare` — A/B compare
  - `GET /api/sandbox/results/{id}` — get results
- CLI: `autoagent sandbox generate --count 500 --domain customer-support`
- CLI: `autoagent sandbox test --config candidate.yaml --conversations sandbox_001`

**Frontend:**
- `web/src/pages/Sandbox.tsx` — sandbox page with:
  - Generate panel (domain, count, difficulty slider)
  - Results grid (pass/fail by category, failure examples)
  - A/B comparison view (side-by-side scores)
  - Conversation browser (click to inspect any generated conversation)

**Tests:** 15+ tests for generation, stress testing, comparison, personas

---

## Feature 2: Knowledge Mining from Successes

Extract patterns from successful conversations and feed them back into the agent.

**Backend:**
- `observer/knowledge_miner.py` — `KnowledgeMiner` class
  - `mine_successes(min_score=0.9)` — scan traces for high-scoring conversations
  - `extract_patterns(conversations)` — identify resolution strategies, tool usage patterns, effective phrasings
  - `generate_knowledge_entries(patterns)` — create structured knowledge entries
  - Each entry: `{pattern, evidence_conversations, confidence, applicable_intents, suggested_application}` 
  - Suggested applications: few-shot example, policy rule, instruction addition, tool ordering
- `observer/knowledge_store.py` — SQLite-backed store for knowledge entries
  - CRUD operations
  - Status: draft → reviewed → applied → retired
  - Track which entries were applied and their impact on scores
- `api/routes/knowledge.py` — REST endpoints
  - `POST /api/knowledge/mine` — trigger mining run
  - `GET /api/knowledge/entries` — list entries with filters
  - `POST /api/knowledge/apply/{id}` — apply entry as mutation
  - `PUT /api/knowledge/review/{id}` — approve/reject entry
- CLI: `autoagent knowledge mine`, `autoagent knowledge list`, `autoagent knowledge apply <id>`

**Frontend:**
- `web/src/pages/Knowledge.tsx` — knowledge page with:
  - Mining trigger button with progress
  - Knowledge entries list (filterable by status, intent, confidence)
  - Entry detail: pattern description, evidence conversations, suggested application
  - "Apply as few-shot" / "Apply as policy" / "Apply as instruction" action buttons
  - Impact tracking (entries that were applied + resulting score changes)

**Tests:** 12+ tests for mining, pattern extraction, knowledge store, application

---

## Feature 3: CI/CD Gate (GitHub Actions)

Make AutoAgent a CI/CD gate — fail the build if agent quality regresses.

**Backend:**
- `cicd/gate.py` — `CICDGate` class
  - `run_gate(config_path, baseline_path=None, fail_threshold=None)` — run eval, compare to baseline, return pass/fail
  - Exit code 0 = pass, exit code 1 = regression detected
  - Output: structured JSON summary (scores, deltas, gate decisions)
  - Supports: hard gate failures, score regression beyond threshold, new safety violations
- CLI enhancement: `autoagent eval run --gate --baseline latest --fail-on-regression`
  - `--gate` flag activates CI/CD mode (structured output, exit codes)
  - `--baseline latest` compares against last passing eval
  - `--fail-on-regression` exits non-zero on any score decrease
  - `--threshold 0.05` allows up to 5% regression
- `api/routes/cicd.py` — webhook endpoint for GitHub Actions callback

**Files:**
- `cicd/github_action.yml` — reusable GitHub Action definition
- `cicd/README.md` — setup guide with examples
- Example workflow: `.github/workflows/agent-quality.yml`

```yaml
# Example GitHub Action
name: Agent Quality Gate
on: [push, pull_request]
jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install autoagent
      - run: autoagent eval run --gate --fail-on-regression --output results.json
      - uses: actions/upload-artifact@v4
        with: { name: eval-results, path: results.json }
```

**Tests:** 8+ tests for gate logic, exit codes, threshold comparison, baseline management

---

## Feature 4: Conversation Replay with "What If"

Replay real historical conversations through a candidate config to project outcomes.

**Backend:**
- `evals/what_if.py` — `WhatIfEngine` class
  - `replay_with_config(conversation_ids, candidate_config)` — replay real conversations through candidate
  - `compare_outcomes(original_results, replay_results)` — side-by-side comparison
  - `project_impact(replay_results, total_conversations)` — extrapolate to full traffic
  - Handle tool calls: stub external tools with recorded responses from original conversation
  - Grade both original and replay with same graders for fair comparison
- `api/routes/what_if.py` — REST endpoints
  - `POST /api/what-if/replay` — start replay job
  - `GET /api/what-if/results/{id}` — get results
  - `POST /api/what-if/project` — project impact to full traffic
- CLI: `autoagent what-if --config candidate.yaml --conversations last-100`

**Frontend:**
- `web/src/pages/WhatIf.tsx` — what-if page with:
  - Config selector (pick candidate)
  - Conversation selector (last N, specific IDs, by category)
  - Side-by-side results (original vs replay outcomes)
  - Impact projection ("If this fix was live last week, 47 more conversations would have succeeded")
  - Individual conversation drill-down (see how each conversation played out differently)

**Tests:** 10+ tests for replay engine, outcome comparison, impact projection, tool stubbing

---

## Feature 5: Multi-Agent Impact Analysis

Understand how changes to one agent affect the entire agent team.

**Backend:**
- `multi_agent/impact_analyzer.py` — `ImpactAnalyzer` class
  - `analyze_dependencies(agent_tree)` — map which agents depend on which
  - `predict_impact(mutation, agent_tree)` — predict downstream effects of a change
  - `cross_agent_eval(mutation, affected_agents)` — eval the mutation against all affected agents
  - `generate_impact_report(results)` — structured report of cross-agent effects
  - Dependency types: routing (orchestrator→specialist), shared tools, shared context, handoff chains
- `multi_agent/agent_tree.py` — agent tree model
  - Parse agent tree from config (orchestrator + specialists + shared components)
  - Track dependencies between agents
  - Identify shared components (tools, policies, knowledge)
- `api/routes/impact.py` — REST endpoints
  - `POST /api/impact/analyze` — analyze impact of proposed change
  - `GET /api/impact/dependencies` — get dependency graph
  - `GET /api/impact/report/{id}` — get impact report
- CLI: `autoagent impact analyze --mutation <id>`, `autoagent impact deps`

**Frontend:**
- `web/src/pages/Impact.tsx` — impact analysis page with:
  - Agent tree visualization (interactive, shows dependencies)
  - Impact prediction panel (which agents affected, predicted score changes)
  - Cross-agent eval results (table of agent × metric scores)
  - "Safe to deploy?" summary with confidence

**Tests:** 10+ tests for dependency analysis, impact prediction, cross-agent eval

---

## Feature 6: Webhook/Event Notifications

Alert users when things happen — don't make them watch dashboards.

**Backend:**
- `notifications/manager.py` — `NotificationManager` class
  - `register_webhook(url, events, filters)` — register a webhook endpoint
  - `register_slack(webhook_url, events, filters)` — Slack-specific integration
  - `register_email(address, events, filters)` — email notifications
  - `send(event_type, payload)` — dispatch to all registered handlers
  - Event types: `health_drop`, `optimization_complete`, `deployment`, `safety_violation`, `daily_summary`, `new_opportunity`, `gate_failure`
  - Filters: severity threshold, agent filter, time window
- `notifications/channels.py` — channel implementations (webhook POST, Slack blocks, email via SMTP)
- `notifications/scheduler.py` — scheduled notifications (daily summary, weekly report)
- `api/routes/notifications.py` — REST endpoints
  - `POST /api/notifications/webhook` — register webhook
  - `POST /api/notifications/slack` — register Slack
  - `POST /api/notifications/email` — register email
  - `GET /api/notifications/subscriptions` — list active subscriptions
  - `DELETE /api/notifications/subscriptions/{id}` — remove subscription
  - `POST /api/notifications/test/{id}` — send test notification
- CLI: `autoagent notify slack --webhook <url> --events health_drop,safety_violation`
- CLI: `autoagent notify email --address <email> --events daily_summary`

**Frontend:**
- `web/src/pages/Notifications.tsx` — notification settings page with:
  - Add webhook/Slack/email forms
  - Event type checkboxes with severity filters
  - Active subscriptions list with test button
  - Notification history log

**Integration with existing code:**
- Hook into `observer/observer.py` — emit events on health changes
- Hook into `optimizer/loop.py` — emit events on optimization completion
- Hook into `optimizer/deployer.py` — emit events on deployment
- Hook into `evals/runner.py` — emit events on gate failures

**Tests:** 10+ tests for webhook delivery, Slack formatting, email, scheduling, event filtering

---

## Feature 7: Collaborative Review

Multiple people can review and approve changes before deployment.

**Backend:**
- `collaboration/review.py` — `ReviewManager` class
  - `request_review(change_id, reviewers)` — create review request
  - `submit_review(change_id, reviewer, decision, comment)` — submit approval/rejection
  - `check_approval(change_id, policy)` — check if approval requirements met
  - Approval policies: `any_one`, `all_reviewers`, `majority`, `specific_role`
  - Review states: pending → in_review → approved → rejected → deployed
- `collaboration/team.py` — team/role management
  - Roles: admin, operator, reviewer, viewer
  - Simple file-based team config (no auth server needed)
- `api/routes/collaboration.py` — REST endpoints
  - `POST /api/reviews/request` — create review request
  - `POST /api/reviews/{id}/submit` — submit review
  - `GET /api/reviews/pending` — list pending reviews
  - `GET /api/reviews/{id}` — get review details with comments
- CLI: `autoagent review request <change-id> --reviewers alice,bob`
- CLI: `autoagent review approve <change-id> --comment "Looks good"`
- CLI: `autoagent review list --pending`

**Frontend:**
- `web/src/pages/Reviews.tsx` — collaborative review page with:
  - Pending reviews list (with reviewer avatars/names)
  - Review detail: change diff, metrics, reviewer comments, approval status
  - Approve/reject buttons with comment field
  - Review history timeline
  - "Ready to deploy" indicator when approval policy is met

**Integration:**
- Hook into `optimizer/deployer.py` — block deployment until approval policy met
- Hook into notifications — notify reviewers when review requested

**Tests:** 10+ tests for review workflow, approval policies, role checking

---

## Execution Rules

1. **Plan first** — read the full codebase, understand the architecture, then plan implementation order
2. **Use sub-agents** (Task tool) aggressively for parallelism
3. **Dependency order**: Notifications first (other features emit events), then Sandbox, Knowledge, CI/CD, What-If, Multi-Agent, Collaborative Review
4. **Run tests after each feature** — `python3 -m pytest tests/ -x -q`
5. **Do NOT break existing tests** — current count is 1,825. Final count must be significantly higher.
6. **Add comprehensive tests** — target 75+ new tests across all 7 features
7. **Commit after each feature** with conventional commit messages
8. **Add all new pages to sidebar nav, App.tsx routes, and Layout.tsx page titles**
9. **Follow existing code patterns** — match the style of existing modules

When completely finished with ALL 7 features, run: openclaw system event --text "Done: 7 platform features — sandbox, knowledge mining, CI/CD gate, what-if replay, multi-agent impact, notifications, collaborative review" --mode now
