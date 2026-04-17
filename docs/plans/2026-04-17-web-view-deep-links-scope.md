# Web View Deep Links Scope

Date: 2026-04-17

Status: Draft scope

## Executive Summary

AgentLab should keep the Claude-Code-style CLI / Workbench as the primary
builder surface, but make browser links a first-class inspection contract for
objects that are too dense for terminal rendering: eval results, failure cases,
traces, config lineage, optimization attempts, comparisons, and deployment
state.

The right mental model is not "CLI vs web." It is "terminal for action, web for
inspection." The CLI should keep users in flow, run the loop, summarize outcomes,
and print one or two high-value links at the moment a richer view is useful.
The web should become the durable microscope for a specific artifact, not a
parallel product that forces users to restart context.

The recommended first scope is:

1. Make local deep links canonical for eval runs and lineage.
2. Print those links from CLI commands and Workbench slash command summaries.
3. Add a shared link builder / resolver so every surface uses the same entity
   IDs and route contracts.
4. Reuse existing result, trace, config, and lineage stores rather than creating
   a new web-only data model.
5. Defer public share links until the local link model is trustworthy and has
   explicit redaction/auth rules.

## Problem

AgentLab is becoming a CLI / Workbench-first development environment for agent
builders. That is the right primary surface for agent iteration because users
are already in a terminal editing files, running evals, approving changes, and
shipping deployments.

But some AgentLab outputs are visually and cognitively too rich for the terminal:

- Eval runs have case matrices, scorer breakdowns, judge rationale, trace links,
  annotations, and run-to-run diffs.
- Agent config lineage has graph structure: build input -> config version ->
  eval -> optimization attempt -> accepted config -> deploy -> measurement.
- Traces have nested timelines, tool calls, retries, cost, latency, and raw IO.
- Optimization attempts require side-by-side diffs, evidence, regressions, and
  review state.
- Deployments require canary status, rollback history, linked attempt, and
  post-deploy measurement.

Today the repo already has many of these web surfaces, but the product contract
is inconsistent. Some routes deep-link by run ID (`/evals/:id`,
`/results/:runId`), some are stateful list pages (`/configs`), and some CLI
outputs still surface paths or next steps rather than a canonical "open this
exact object" link.

## Recommendation

Build a web-link layer around durable AgentLab entities.

The CLI and Workbench should emit browser links only when a browser is clearly
better than a terminal:

- dense tables
- graphs
- timelines
- annotations
- comparisons
- review decisions
- shareable evidence
- operational status that changes over time

Do not link every line of output. Links should feel like a useful receipt, not a
marketing banner.

## Current AgentLab Context

Local docs and code already support the product direction:

- The core loop is documented as `Build -> Workbench -> Eval -> Compare ->
  Optimize -> Review -> Deploy`.
- The README states that CLI, API, and web console share local workspace state.
- The default CLI entry point is the Workbench, with slash commands for
  `/build`, `/eval`, `/optimize`, `/deploy`, `/skills`, `/tasks`, `/lineage`,
  and `/attempt-diff`.
- Existing React routes include `/evals/:id`, `/results/:runId`, `/compare`,
  `/configs`, `/traces`, `/events`, `/blame`, `/context`, `/workbench`,
  `/optimize`, `/improvements`, and `/deploy`.
- Eval APIs already expose run detail, case detail, structured result detail,
  examples, annotations, diff, and export.
- Trace APIs already expose trace detail, grades, graph, and context analysis.
- The CLI lineage model already exists in `optimizer/improvement_lineage.py` and
  should be the source for web lineage, not a duplicated implementation.

The product should therefore focus on route and link contracts, not building a
separate observability system from scratch.

## External Research

### Summary Of Patterns

Across eval, observability, and deployment tools, the strongest pattern is:

- CLI runs work.
- Terminal prints concise status plus a stable URL.
- Browser opens the high-dimensional inspection view.
- Web view supports filtering, comparison, sharing, and drill-down.
- IDs are durable and usually object-centered: run, trace, experiment, prompt,
  dataset, deployment.

### Competitive Matrix

| Product | Relevant behavior | What AgentLab should learn |
| --- | --- | --- |
| Braintrust | `bt eval` surfaces a terminal link to the experiment results. The UI compares experiments, and log views support trace browsing, sharing, and origin navigation back to prompt or dataset. | Print direct eval/experiment links from CLI. Make trace -> prompt/dataset/config origin navigation a first-class feature. |
| LangSmith | Combines traces, datasets, experiments, evaluation, Studio, and a CLI for querying/managing those objects. | Treat CLI and web as two views over the same durable entities. |
| Phoenix | Supports tracing, prompt versioning, span replay, datasets, experiments, evaluator traces, and experiment failure review with links to associated traces. | Eval failures should always connect to traces and prompt/config versions. |
| W&B Weave | SDK instrumentation captures code, inputs, outputs, and metadata; web tracks traces, evals, feedback, and production monitoring. | Capture enough provenance in every run so the web can answer "why did this happen?" without rerunning. |
| Langfuse | Combines tracing, prompt management, production evals, datasets, experiments, annotation queues, and dashboards. | AgentLab should connect offline evals, production traces, and prompt/config versions instead of treating them as separate views. |
| Promptfoo | `promptfoo view` starts a local browser UI after evals. The viewer supports output detail, grading results, comments, ratings, highlights, and share links. | Strong local-first precedent. AgentLab should support `agentlab open` / `agentlab view` without requiring hosted sync. |
| MLflow | Logs runs, params, metrics, datasets, artifacts, and models, then provides a local or remote tracking UI for search, comparison, visualization, and download. | The mature pattern is local artifacts plus optional server UI. AgentLab should keep local-first durable stores. |
| Vercel CLI | CLI is primary for deploy/logs/project management, with `vercel open`, `vercel inspect`, deployment URLs, and dashboard links. | Use `--open` / `open` commands and deployment-specific links rather than auto-opening browsers unconditionally. |
| Netlify CLI | `netlify deploy` provides deploy and function logs URLs; `--open` opens the project after deploy. | Print operational URLs after deploy and make browser-open opt-in. |
| GitHub CLI | `gh run view --web` opens the selected Actions run in the browser. | Provide a minimal `agentlab open <kind> <id>` command and Workbench shortcut. |
| Anthropic Console Evals | Browser UI supports prompt evals, generated test cases, reruns, side-by-side comparison, grading, and prompt versioning. | Web is best for prompt/eval comparison and test-case authoring, but should remain linked to config history. |
| OpenAI Evals API | Evals and eval runs have API IDs and dashboard-queryable metadata. | AgentLab should include structured metadata on eval/config/attempt entities so links can resolve without file paths. |

Source links:

- [Braintrust evaluation quickstart](https://www.braintrust.dev/docs/evaluation)
- [Braintrust logs and trace sharing](https://www.braintrust.dev/docs/observe/view-logs)
- [LangSmith overview](https://docs.langchain.com/langsmith/home)
- [Phoenix overview](https://arize.com/docs/phoenix)
- [Phoenix experiments](https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/run-experiments)
- [W&B Weave overview](https://docs.wandb.ai/weave/concepts/what-is-weave)
- [Langfuse overview](https://langfuse.com/docs)
- [Promptfoo web viewer](https://www.promptfoo.dev/docs/usage/web-ui/)
- [Promptfoo CLI](https://www.promptfoo.dev/docs/usage/command-line/)
- [MLflow tracking](https://mlflow.org/docs/latest/ml/tracking/)
- [Vercel CLI](https://vercel.com/docs/cli)
- [Netlify CLI deploy](https://cli.netlify.com/commands/deploy/)
- [GitHub CLI gh run view](https://cli.github.com/manual/gh_run_view)
- [Anthropic evaluation tool](https://platform.claude.com/docs/en/test-and-evaluate/eval-tool)
- [OpenAI Evals API reference](https://developers.openai.com/api/reference/resources/evals)

## Product Principles

### 1. CLI Does The Work, Web Explains The Work

The CLI should remain the action surface for building, running evals, optimizing,
reviewing, and deploying. The web should answer the second-order questions:

- Which cases failed?
- Why did they fail?
- What changed between config versions?
- What trace caused this score?
- Which attempt produced this deployment?
- Is the canary better than baseline?

### 2. Every Link Resolves To An Entity, Not A Page State

A good URL should identify a durable object:

- eval run ID
- result run ID
- trace ID
- config version
- attempt ID
- deployment ID
- session ID
- dataset/suite ID

Avoid URLs that depend on transient browser state or raw local file paths.

### 3. Links Should Be Sparse And High-Signal

At command completion, print no more than two links by default:

- primary: the object just created or completed
- secondary: the next best investigation view

Use `--verbose` or `/links` to show all related links.

### 4. Local-First Comes First

The MVP should work entirely with local AgentLab state and a local web server.
Hosted share links are valuable, but they introduce auth, redaction, workspace
sync, and retention questions. Do not make hosted sync a prerequisite for useful
deep links.

### 5. Web Links Must Never Smuggle Secrets

URLs should contain opaque IDs and safe query parameters only. No provider keys,
absolute local paths, raw prompts, case inputs, or PII should appear in the URL.

### 6. Browser Views Should Preserve Terminal Context

Every page opened from CLI should show:

- the command that created the artifact
- workspace/project identity
- config version/path in a safe display form
- timestamp and duration
- runtime mode, model/provider, and mock/live status
- related links back to source entities

### 7. Bidirectional Navigation Matters

The browser should not be a dead end. From an eval result, users should reach:

- config version
- dataset/suite
- failure traces
- optimization attempt
- comparison
- deployment, if it shipped

From lineage, users should jump back to the exact eval/result/attempt/deployment.

## Scope: Where To Add Web Links

### P0: Eval Run Results

This is the highest-value target.

Why:

- Users explicitly expect eval results to have a rich drill-down page.
- Current routes and APIs mostly exist.
- Eval output naturally produces durable IDs.
- Browser tables are much better for filtering failures and inspecting examples.

CLI / Workbench moments:

- `agentlab eval run`
- `/eval`
- Workbench "Eval complete" summary
- Build -> Eval generated-suite completion
- Optimize preflight when it reuses eval evidence

Default terminal output:

```text
Eval complete: run_abc123
Score: 0.74 | 34/42 passed | 8 failed

Open results: http://127.0.0.1:8000/results/run_abc123
Open summary: http://127.0.0.1:8000/evals/run_abc123
```

Recommended web routes:

- Keep `/evals/:runId` for run summary.
- Keep `/results/:runId` for case-level explorer.
- Add redirects from `/evals/runs/:runId` to `/evals/:runId` if a more explicit
  route is desired later.

Required features:

- Run summary header: pass rate, composite score, safety, latency, cost, token
  use, runtime mode.
- Failure-first case table with filters for category, scorer, severity, metric,
  status, and text search.
- Case detail panel: input, expected, output, judge reasoning, scorer values,
  trace link, prompt/config snapshot.
- Compare CTA: select baseline run.
- Optimize CTA: carries `evalRunId` and config identity.
- Export: JSON, CSV, Markdown.

### P0: Lineage Graph

This is the second highest-value target because the user explicitly called out
agent config lineage.

Why:

- Agent builders need auditability across build/eval/optimize/deploy.
- CLI lineage views exist but graph inspection is browser-native.
- The product already has `ImprovementLineageStore`.

CLI / Workbench moments:

- `/lineage <id>`
- `agentlab improve lineage <attempt_id>`
- `agentlab optimize`
- `agentlab deploy --attempt-id <id>`
- Workbench `/tasks` when it lists run/plan IDs
- `agentlab status` for latest active lineage

Recommended web routes:

- `/lineage/:nodeId`
- `/attempts/:attemptId`
- `/attempts/:attemptId/diff`
- `/configs/:version/lineage`

Graph should support these node kinds:

- build brief / build artifact
- config version
- generated eval suite / dataset
- eval run
- failed case cluster
- optimization attempt
- review decision
- deployment / canary
- measurement
- rollback

Minimum graph:

```text
Build brief
  -> Config v014
  -> Eval run run_abc123
  -> Attempt att_def456
  -> Config v015
  -> Canary dep_ghi789
  -> Measurement meas_jkl012
```

Required features:

- Graph plus timeline toggle.
- Node detail side panel.
- Edge labels: "evaluated", "proposed", "accepted", "deployed", "measured",
  "rolled back".
- Link to compare config versions.
- Link to eval result and trace detail.
- Clear badges for live/mock, accepted/rejected, canary/promoted/rolled back.

### P0: Shared Link Builder

This is the enabling technical work.

Without it, every command/page will hand-roll URLs and drift.

Add a shared module that accepts an entity reference and returns canonical
local links.

Suggested data contract:

```json
{
  "kind": "eval_run",
  "id": "run_abc123",
  "title": "Eval run run_abc123",
  "primary_url": "http://127.0.0.1:8000/results/run_abc123",
  "secondary_urls": [
    {
      "label": "Summary",
      "url": "http://127.0.0.1:8000/evals/run_abc123"
    },
    {
      "label": "Lineage",
      "url": "http://127.0.0.1:8000/lineage/run_abc123"
    }
  ],
  "workspace_id": "local",
  "created_at": "2026-04-17T15:30:00Z",
  "available": true,
  "visibility": "local"
}
```

Suggested Python type:

```python
@dataclass(frozen=True)
class EntityRef:
    kind: Literal[
        "eval_run",
        "result_run",
        "trace",
        "config_version",
        "attempt",
        "deployment",
        "session",
        "dataset",
    ]
    id: str
    workspace_id: str | None = None
    title: str | None = None
```

Resolution responsibilities:

- Determine local base URL.
- Prefer FastAPI combined app URL when available.
- Fall back to Vite dev URL only in frontend dev mode.
- Validate that the entity exists before printing "open" links by default.
- Return "server not running" guidance rather than dead links.
- Never embed raw paths or secret-bearing query params.

### P1: Config Version Detail

Why:

- Current `/configs` is useful but list/stateful.
- Agent builders need an exact link to the config that was evaluated, optimized,
  or deployed.

Recommended routes:

- `/configs/:version`
- `/configs/:version/diff?base=v014`
- `/configs/:version/lineage`

Features:

- YAML viewer.
- Diff against prior active/baseline version.
- Source metadata: build, import, optimize, manual edit.
- Eval performance history for this version.
- Deploy status.
- Related attempts and review decisions.

CLI moments:

- `agentlab build`
- `agentlab workbench save`
- `/save`
- `agentlab config import`
- `agentlab optimize`
- `agentlab review apply`

Example:

```text
Saved config: v015
Open config: http://127.0.0.1:8000/configs/v015
Open lineage: http://127.0.0.1:8000/configs/v015/lineage
```

### P1: Trace Detail

Why:

- Traces are the "why" behind eval scores and runtime failures.
- The API already supports trace detail, grades, and graph.

Recommended routes:

- `/traces/:traceId`
- `/traces/:traceId/graph`
- `/traces/:traceId/context`

Features:

- Span timeline.
- Tool calls and outputs.
- Model calls, parameters, latency, token/cost.
- Error and retry visualization.
- Redacted raw input/output.
- Links to eval case, conversation, config version, prompt/instruction version.

CLI moments:

- Eval failed case summary.
- `agentlab trace show <trace_id>`
- Workbench tool-call error.
- Continuous mode alert.

### P1: Optimization Attempt Detail

Why:

- The CLI can summarize an optimization attempt, but review needs side-by-side
  evidence.
- Existing `/attempt-diff` and lineage concepts can map directly to web.

Recommended routes:

- `/attempts/:attemptId`
- `/attempts/:attemptId/diff`
- `/attempts/:attemptId/evidence`

Features:

- Baseline config vs candidate config.
- Eval delta, failed/passed case movements.
- Safety regression warnings.
- Review decision history.
- Accept/reject CTA only if current permissions allow it.
- Link to lineage.

CLI moments:

- `agentlab optimize`
- `/optimize`
- `agentlab improve list`
- `/attempt-diff`
- `agentlab review`

### P1: Compare View

Why:

- Pairwise results are visual by nature.
- Compare should be a decision surface, not just a chart.

Recommended routes:

- `/compare/:comparisonId`
- `/compare?baselineRunId=...&candidateRunId=...`
- `/compare?baseConfig=v014&candidateConfig=v015`

Features:

- Summary: winner, confidence, significant dimensions.
- Case movement table: pass -> fail, fail -> pass, unchanged.
- Scorer distribution.
- Cost/latency delta.
- Safety regression highlight.

CLI moments:

- `agentlab compare`
- post-optimization eval.
- pre-deploy gate.

### P1: Deployment / Canary Detail

Why:

- Deployment state changes over time.
- Operators need one durable page for canary status and rollback evidence.

Recommended routes:

- `/deployments/:deploymentId`
- `/deploy?version=v015` as compatibility.

Features:

- Version, strategy, traffic allocation.
- Canary metrics.
- Linked attempt and eval evidence.
- Promotion/rollback history.
- Environment/integration target.
- Safety gate status.

CLI moments:

- `agentlab deploy`
- `/deploy`
- deploy status polling.
- continuous-mode release attempt.

### P2: Workbench Session Replay

Why:

- Session replay is valuable for audits and collaboration.
- It is more complex because it may contain user prompts, tool IO, filesystem
  paths, and possibly sensitive content.

Recommended routes:

- `/workbench/sessions/:sessionId`
- `/workbench/runs/:runId`

Features:

- Transcript replay.
- Plan/task tree.
- Tool calls.
- Artifacts generated.
- Links to eval/config/attempt/deployment.

Default stance:

- Local-only.
- No public sharing until redaction exists.

### P2: Hosted Share Links

Why:

- Teams will want to send eval results and lineage to teammates.
- Public/hosted links are useful for PR review, support, and customer-facing
  evidence.

Do this only after local links are solid.

Requirements:

- Explicit command: `agentlab share eval run_abc123`.
- Confirmation prompt if content includes prompts, inputs, outputs, traces, or
  annotations.
- Redaction pipeline.
- Authenticated workspace sync.
- TTL and revoke support.
- Per-object visibility: private, team, public.
- Audit log for share creation/open/revoke.

Suggested command:

```text
agentlab share eval run_abc123 --ttl 7d
agentlab share lineage att_def456 --team
agentlab share revoke share_xyz
```

## Where Not To Add Web Links

Do not add default links for:

- every progress event
- every individual tool call
- transient logs with no durable ID
- destructive actions
- provider-key or credential flows
- raw local filesystem paths
- failed commands that did not create an inspectable artifact
- tiny commands where terminal output is sufficient, such as `/cost` with no
  detailed backing data

Use links when the user has a durable artifact or a visual investigation path.

## Terminal UX

### Default Output

At most two links:

```text
Eval complete: run_abc123
Score: 0.74 | 34/42 passed | 8 failed

Open results: http://127.0.0.1:8000/results/run_abc123
Open lineage: http://127.0.0.1:8000/lineage/run_abc123
```

### Verbose Output

For `--verbose` or `/links`:

```text
Links:
  Summary:     http://127.0.0.1:8000/evals/run_abc123
  Results:     http://127.0.0.1:8000/results/run_abc123
  Failures:    http://127.0.0.1:8000/results/run_abc123?outcome=fail
  Lineage:     http://127.0.0.1:8000/lineage/run_abc123
  Compare:     http://127.0.0.1:8000/compare?candidateRunId=run_abc123
  Optimize:    http://127.0.0.1:8000/optimize?evalRunId=run_abc123
```

### Open Commands

Add a small command family:

```text
agentlab open eval <run_id>
agentlab open results <run_id>
agentlab open lineage <id>
agentlab open config <version>
agentlab open trace <trace_id>
agentlab open attempt <attempt_id>
agentlab open deployment <deployment_id>
agentlab open last
```

Workbench slash aliases:

```text
/open eval
/open results
/open lineage
/open last
/links
```

Behavior:

- Opens browser only when user explicitly asks or passes `--open`.
- Otherwise prints URL.
- If local server is not running, offer the exact command to start it.
- JSON output includes links under a `links` key but does not print prose.

### JSON Output Contract

Any command that creates a durable artifact should include links in JSON mode:

```json
{
  "run_id": "run_abc123",
  "status": "completed",
  "score": 0.74,
  "links": {
    "summary": "http://127.0.0.1:8000/evals/run_abc123",
    "results": "http://127.0.0.1:8000/results/run_abc123",
    "lineage": "http://127.0.0.1:8000/lineage/run_abc123"
  }
}
```

## Web View UX Requirements

### Eval Results Page

Top area:

- run ID and status
- pass/fail count
- composite score
- dataset/suite
- config version
- runtime mode
- provider/model
- duration/cost/tokens
- lineage link

Main area:

- failure-first table
- filters for status, category, scorer, severity, search
- case detail drawer
- trace link per case
- annotation panel
- export controls

Actions:

- Compare
- Optimize from this run
- Add failing cases to dataset
- Export

### Lineage Page

Top area:

- selected node ID and type
- graph status summary
- latest score/deploy state if applicable

Main area:

- graph view
- timeline view
- node detail side panel
- related artifact links

Actions:

- open eval
- open config
- open attempt diff
- compare versions
- open deployment

### Config Page

Top area:

- config version
- active/canary/deployed status
- source: build/import/manual/optimize
- created by command/session

Main area:

- YAML
- structured prompt/instruction view
- diff against baseline
- eval performance history
- deployments using this config

Actions:

- activate
- compare
- eval
- view lineage

### Trace Page

Top area:

- trace ID
- root operation
- eval case/conversation/source
- latency/tokens/cost/error status

Main area:

- timeline
- spans
- model calls
- tool calls
- redacted raw IO

Actions:

- promote to eval case
- annotate
- open related eval result
- open config

## Technical Architecture

### Link Builder Module

Create a shared Python module, for example:

```text
core/web_links.py
```

Responsibilities:

- Normalize entity refs.
- Validate entity existence where cheap.
- Build canonical local URLs.
- Build route-relative URLs for frontend use.
- Return link metadata to CLI, API, and Workbench.

The frontend should have a matching TypeScript helper, but the Python link
builder should be the source for command output.

### Link Resolver Endpoint

Add a read-only API:

```text
GET /api/links/resolve?kind=eval_run&id=run_abc123
GET /api/links/recent
```

Use cases:

- `agentlab open last`
- Workbench `/links`
- UI cards that need related links without duplicating route logic
- future hosted share links

### Entity Metadata

Add linkable entity metadata to command results:

```json
{
  "entity": {
    "kind": "eval_run",
    "id": "run_abc123",
    "workspace_id": "local",
    "related": [
      { "kind": "config_version", "id": "v015" },
      { "kind": "dataset", "id": "generated_build" },
      { "kind": "lineage", "id": "run_abc123" }
    ]
  }
}
```

### Lineage API

Add or expose:

```text
GET /api/lineage/{node_id}
GET /api/attempts/{attempt_id}
GET /api/attempts/{attempt_id}/diff
GET /api/config/{version}/lineage
```

The implementation should compose:

- config manifest
- build artifact store
- eval result/history
- improvement lineage DB
- deploy history
- trace links where available

### Backward Compatibility

Keep current routes working:

- `/evals/:id`
- `/results/:runId`
- `/configs`
- `/deploy?version=...`
- `/optimize?evalRunId=...`

Add canonical routes as aliases or redirects rather than breaking existing docs.

### Server Availability

Local link generation must answer:

- Is the combined FastAPI app running?
- Is the Vite dev server running?
- Which URL should be printed?

Recommended priority:

1. `AGENTLAB_WEB_BASE_URL`, if set.
2. Running combined app, usually `http://127.0.0.1:8000`.
3. Running Vite dev server, usually `http://127.0.0.1:5173`.
4. No link printed; show `agentlab server` guidance.

## Security And Privacy

### P0 Rules

- Links are local-only.
- URLs contain IDs, not raw data.
- No absolute paths in URLs.
- No provider credentials or API keys in link payloads.
- Read-only pages may load sensitive content from local backend, but the URL
  itself must not contain sensitive content.
- Do not auto-open browser in CI or non-TTY mode.
- Do not auto-open browser after commands unless `--open` was provided.

### P2 Share Rules

Before hosted sharing:

- Add redaction for prompts, inputs, outputs, traces, and annotations.
- Add per-share visibility.
- Add TTL and revocation.
- Add audit logging.
- Add explicit user confirmation for public links.
- Add workspace-level sharing policy.

## Metrics

Primary:

- Eval result link click/open rate.
- Percentage of completed eval runs with a valid result link.
- Time from eval completion to failure-case inspection.
- Percentage of optimization runs started from a completed eval link.
- Percentage of deployments with traceable config/eval/attempt lineage.

Quality:

- Link resolution success rate.
- Deep-link page load latency.
- Broken/stale link count.
- Server-not-running recovery rate.
- User-reported "where did this come from?" incidents.

Adoption:

- `agentlab open` usage.
- Workbench `/links` usage.
- Lineage page views per optimization/deployment.
- Compare views started from eval result pages.

Safety:

- Public share links created.
- Public share links revoked.
- Redaction warnings shown.
- Sensitive-data-in-URL incidents. Target: zero.

## Rollout Plan

### Phase 0: Route And Entity Inventory

Duration: 2-3 days.

Deliverables:

- Entity registry for linkable objects.
- Current route map.
- CLI output inventory.
- Decision on local base URL detection.
- Decision on canonical route names vs compatibility redirects.

Exit criteria:

- Every P0 entity kind has an ID source and a proposed route.
- No P0 route requires raw file paths in URLs.

### Phase 1: Local Eval Links

Duration: 1 week.

Deliverables:

- Shared link builder for eval/result links.
- CLI links from `agentlab eval run`.
- Workbench links from `/eval`.
- JSON `links` output.
- Basic `agentlab open eval <run_id>` and `agentlab open results <run_id>`.
- Tests for link generation and CLI output.

Exit criteria:

- Completed eval prints a valid local result URL.
- Link opens existing result page for the run.
- JSON mode includes links without breaking existing consumers.

### Phase 2: Lineage Web View

Duration: 1-2 weeks.

Deliverables:

- `/lineage/:nodeId` route.
- `/api/lineage/{node_id}` read endpoint.
- Reuse `ImprovementLineageStore`.
- Graph/timeline UI.
- CLI links from optimize/improve/deploy.
- `agentlab open lineage <id>`.

Exit criteria:

- A real eval -> attempt -> config -> deployment chain resolves in browser.
- Unknown IDs show helpful recovery, not a blank page.
- CLI `/lineage` and web lineage agree on the same chain.

### Phase 3: Config, Trace, Attempt, Deployment Links

Duration: 2-3 weeks.

Deliverables:

- `/configs/:version`
- `/traces/:traceId`
- `/attempts/:attemptId`
- `/deployments/:deploymentId`
- Related links on each page.
- CLI links after build/save/optimize/deploy.

Exit criteria:

- Every major lifecycle command creates or references at least one durable link.
- Web pages can navigate across the full loop without losing context.

### Phase 4: Hosted Sharing

Duration: separate product decision.

Prerequisites:

- Local links stable.
- Redaction model defined.
- Auth model defined.
- Workspace sync or artifact upload model defined.

Deliverables:

- `agentlab share ...`
- Share token model.
- Redaction preview.
- Team/public/private visibility.
- TTL/revoke/audit.

## Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Links rot because local server is not running | Users lose trust quickly | Validate server, print start command, support `agentlab open` fallback. |
| URLs leak local paths or sensitive data | Security incident | Use opaque IDs only; forbid raw prompt/input/path query params. |
| Web becomes a second primary workflow | Product confusion | Keep terminal as action surface; web pages focus on inspection/review. |
| Too many links clutter CLI output | Reduced CLI readability | Default to max two links; put all links behind `/links` or `--verbose`. |
| Lineage model forks between CLI and web | Inconsistent audits | Web must read existing lineage store and config/eval/deploy stores. |
| Hosted sharing ships too early | Privacy/auth complexity | Defer until local links and redaction are proven. |
| Browser pages allow destructive actions by accident | Unsafe operations | Keep deep links read-first; require explicit confirmations and permission checks for mutations. |

## Open Questions

1. Should canonical eval detail be `/evals/:runId` or should AgentLab add
   `/evals/runs/:runId` and redirect old URLs?
2. Should config versions be addressed as `v015`, integer `15`, or both?
3. Should `lineage/:nodeId` accept any node ID, or should route prefixes be
   type-specific (`/attempts/:id/lineage`, `/evals/:id/lineage`)?
4. Should `agentlab open last` use last command artifact, last active session
   artifact, or most recent durable workspace artifact?
5. Should the local web server start automatically when users run
   `agentlab open`, or should it print a start command first?
6. What is the minimum redaction model required before team share links?
7. Does AgentLab need a hosted artifact sync product, or can team sharing start
   with exported static reports?

## Recommended MVP

Ship this first:

1. `core/web_links.py`
2. Eval/result link generation.
3. CLI and Workbench link output for completed eval runs.
4. `agentlab open eval/results/last`.
5. `/lineage/:nodeId` backed by existing lineage store.
6. CLI and Workbench link output for optimize/improve/deploy lineage.
7. `/configs/:version` as an exact config detail page.

That MVP addresses the two user examples directly:

- eval result links
- agent config lineage links

It also establishes the durable pattern for the rest of the loop without making
hosted sharing, dashboards, or a new observability backend prerequisites.
