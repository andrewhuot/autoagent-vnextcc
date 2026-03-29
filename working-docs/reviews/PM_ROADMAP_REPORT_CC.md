# AutoAgent VNextCC — PM Review: Product Assessment, Competitive Analysis & Roadmap

**Reviewer:** Claude Sonnet 4.6 (Technical PM + Distinguished Engineer)
**Date:** 2026-03-29
**Scope:** Full codebase audit + competitive landscape + 30–50 item prioritized roadmap

---

## Part 1: Product Assessment

### What Is AutoAgent VNextCC?

AutoAgent is a continuous optimization platform for AI agents. The core thesis: instead of manually tuning agent prompts and configs, you point AutoAgent at a running agent, and it closes the loop autonomously — tracing failures, diagnosing root causes, generating typed mutations, running statistically-rigorous evals, gating on hard constraints, and deploying winners. The loop runs for hours or days unattended.

```
TRACE → DIAGNOSE → SEARCH → EVAL → GATE → DEPLOY → LEARN → REPEAT
```

---

### What Actually Works (Real, Substantive Code)

**Verdict: The codebase is real and substantial. This is not a demo wrapper.**

Evidence:
- **2,938 tests passing** (118 seconds runtime, zero failures)
- **Zero import errors** — `python -c "import api.server"` completes cleanly
- **200+ REST endpoints** across 51 route modules, all properly registered in lifespan
- **50+ React/TypeScript pages** with real data wiring (no lorem ipsum)
- **~24,000 lines** across optimizer + evals + core alone

#### Core Optimizer Loop ✅
`optimizer/loop.py` (37.5KB) implements a real `Optimizer` class with:
- **4 search strategies**: `simple` (greedy), `adaptive` (bandit), `full` (multi-hypothesis + curriculum), `pro` (research algorithms)
- **Bandit algorithms**: UCB1 and Thompson sampling via `HybridBanditSelector`
- **Pareto-constrained archive**: `ConstrainedParetoArchive` tracks multi-objective tradeoffs (quality, safety, latency, cost)
- **Human gates**: Pause check, budget check, stall detection — all enforced before any LLM call
- **Immutable surfaces**: Loaded from persistent `HumanControlStore`; optimizer never touches pinned surfaces

#### Statistical Evaluation Engine ✅
`evals/` implements real statistical machinery:
- Clustered bootstrap confidence intervals
- O'Brien-Fleming alpha spending for sequential testing
- Holm-Bonferroni multiple-hypothesis correction
- Minimum sample size enforcement before significance is declared
- Anti-Goodhart guards: holdout rotation, overfitting drift detection, judge variance bounds

#### 9 Typed Mutation Operators ✅
`optimizer/mutations.py` defines `MutationOperator` dataclasses with risk classification (`low/medium/high/critical`), target surface, preconditions, rollback strategy, and an `apply` function. Real implementations, not stubs.

#### Judge Stack ✅
Tiered 4-layer pipeline: deterministic → similarity (Jaccard) → binary rubric (LLM) → audit judge (cross-family LLM). Judge versioning, drift monitoring, human feedback calibration, position/verbosity bias detection.

#### Research-Grade Search Algorithms ✅
`optimizer/prompt_opt/` implements:
- **MIPROv2** — Bayesian search over (instruction, example set) pairs
- **BootstrapFewShot** — Teacher-student demonstration bootstrapping (DSPy-inspired)
- **GEPA** — Gradient-free evolutionary prompt adaptation with tournament selection
- **SIMBA** — Simulation-based iterative hill-climbing

#### Skills System ✅
`core/skills/` (6 files, ~130KB): Unified build-time + run-time skill abstraction with:
- `SkillStore` — SQLite-backed versioned CRUD
- `SkillComposer` — Dependency resolution and conflict detection
- `SkillMarketplace` — Discovery and installation
- `SkillValidator` — Schema + behavioral validation
- Effectiveness tracking (success rate, improvement delta, times applied)

#### Intelligence Studio ✅
`optimizer/transcript_intelligence.py` — Upload ZIP archives of conversation transcripts (JSON, CSV, TXT), get back intent classification, transfer reason analysis, procedure extraction, FAQ generation, and a one-click agent builder. The `TranscriptIntelligenceService` is wired to a full REST API and frontend page.

#### Integrations ✅
- **Google CX Agent Studio**: Bidirectional import/export, `cx_studio/` module with AST-level config parsing
- **Google ADK**: Python source import via AST parsing, style-preserving export, Cloud Run/Vertex AI deployment
- **MCP Server**: 10 tools exposed to AI coding assistants (Claude Code, Cursor, Windsurf)
- **Braintrust**: Exporter in `observer/integrations/braintrust.py` with SDK + HTTP fallback
- **CI/CD Gates**: `cicd/` module with GitHub Actions integration

#### Infrastructure ✅
- **Dead letter queue** — Failed cycles queued for retry, never dropped
- **Loop checkpointing** — Restarts resume from last completed cycle
- **Watchdog** — Configurable timeout kills stuck cycles
- **Cost tracker** — Per-cycle and daily budget enforcement with stall detection
- **Structured logging** — JSON rotation with configurable limits
- **Docker + Cloud Run + Fly.io** deployment paths

---

### What's Limited or Fake

#### Mock Mode Is the Default ⚠️
`Proposer(use_mock=True)` is the default. Without at least one API key in `.env`, every optimization cycle generates deterministic mock proposals. The system correctly advertises this, but a VP doing a live demo without API keys will see fake optimization. The mock is realistic enough for demos but won't impress anyone who looks closely.

#### Eval Runner Has No Real Agent Wired ⚠️
`EvalRunner.__init__` defaults to `agent_fn = mock_agent_response`. Eval scores are simulated until you wire in a real agent function. The server even adds a `mock_mode_messages` warning. **This is the biggest gap for a serious demo**: you can trigger an optimization cycle, but the eval scores don't reflect a real agent.

#### Transcript Intelligence Uses Keyword Matching ⚠️
`optimizer/transcript_intelligence.py` intent classification uses hardcoded keyword lists:
```python
INTENT_KEYWORDS = {
    "order_tracking": ["where is my order", "track my order", ...],
    "cancellation": ["cancel my order", ...],
}
```
This is brittle and obviously non-LLM for anyone reading the code. The NL editor (`nl_editor.py`) is real, but the transcript parsing layer is keyword-based.

#### SQLite Only — No Scale Path ⚠️
Eight SQLite databases. No Postgres option, no connection pooling beyond SQLite WAL mode. Fine for single-user local operation; blocks every enterprise sale.

#### No Authentication or Multi-Tenancy ⚠️
Zero auth middleware on the FastAPI server. No API keys, no OAuth, no user model, no org/workspace separation. This is a single-user local tool dressed up as a platform.

#### No Real-Time Telemetry Ingestion ⚠️
The system optimizes agents but doesn't **receive live telemetry from running agents** via a push SDK or webhook. Traces are stored from evals, not from production agent traffic. The "continuous" in continuous optimization assumes you run evals yourself; it doesn't watch your production traffic in real time.

#### Canary Deployment Is Config-Only ⚠️
`deployer/canary.py` manages config versions and rollout percentages, but there's no traffic-splitting infrastructure. The "canary" writes a config version with a rollout percentage to SQLite — your actual serving infrastructure needs to read that config and implement the split. This is well-designed for integration but incomplete as a standalone capability.

---

### VP Wow Moments

1. **The loop concept itself** — Autonomous, statistically-rigorous, human-interruptible optimization that runs overnight. No competitor has this.
2. **Experiment cards** — Every optimization attempt is a reviewable card with hypothesis, diff, p-value, and one-click rollback. Auditors will love this.
3. **Anti-Goodhart guards** — Holdout rotation, overfitting drift detection, and judge variance bounds. This is PhD-level thinking applied to agent evaluation. Say "we can't Goodhart our own eval set" and watch the room nod.
4. **Research-grade algorithms (MIPROv2, GEPA, SIMBA)** — Nobody else in the space is shipping these in a product UI.
5. **Metric hierarchy** — Hard gates (safety) → North-star outcomes → Operating SLOs → Diagnostics. The story "a mutation that improves success by 12% but trips a safety gate is rejected, no exceptions" lands perfectly.
6. **Blame maps** — Span-level failure clustering with impact scoring tells you *exactly where* the agent goes wrong. Competitors show you that it went wrong.
7. **2,938 tests** — Real test coverage is visible in the codebase. Engineers will notice.

### Things That Would Embarrass Us

1. **Default mock mode** in a live demo without warning. Prep API keys or the "optimization" looks fake.
2. **No auth**. First question from any enterprise buyer: "How do we control who can deploy configs to production?" Answer: "You can't yet."
3. **Keyword-based transcript intelligence** — Opening `transcript_intelligence.py` in a technical review will raise eyebrows.
4. **SQLite** — "What's your Postgres story?" needs a real answer.
5. **No real-time production telemetry** — The value proposition is "optimize your production agent" but the platform doesn't watch production traffic.
6. **The 147KB beginner guide** — Good docs, but its existence signals the product isn't self-evident enough yet.

---

## Part 2: Competitive Landscape

### 1. Braintrust (braintrustdata.com)

**What they do:** LLM evaluation, logging, prompt playground, and experiment tracking for AI teams.

**Key features:**
- Prompt playground with side-by-side comparison
- Dataset versioning with annotation UI
- Experiment tracking with score history
- CI/CD integration (PR comments with eval diffs)
- AI scoring with custom rubrics
- Real-time trace logging SDK
- Collaboration features (comments, shared datasets)

**Pricing:** Free for personal use; team plans from ~$100/month; enterprise custom

**Target audience:** AI product teams doing rapid prompt iteration; mid-market companies building LLM-powered products

**Strengths:**
1. Best-in-class UI/UX — beautiful, fast, intuitive
2. Real SDK push telemetry — traces flow in from production automatically
3. Strong human annotation and labeling workflow

**Weaknesses:**
1. Evaluation only — no autonomous optimization or mutation loop
2. No agent-specific primitives (no routing, handoff, tool use grading)
3. No statistical rigor (no bootstrap CI, no anti-Goodhart guards)

**Features to steal:**
- Real-time SDK-based telemetry push (critical gap for us)
- Annotation/labeling UI for human feedback collection
- PR comment integration with eval score diffs

---

### 2. LangSmith (smith.langchain.com)

**What they do:** Observability, tracing, and evaluation for LangChain applications.

**Key features:**
- Automatic trace capture for LangChain apps
- LLM call inspection with token-level detail
- Dataset management with annotation
- Human feedback collection
- Hub for sharing prompts/chains
- Evaluation runs with custom evaluators

**Pricing:** Free tier (limited traces); Developer $39/month; Plus $299/month; Enterprise custom

**Target audience:** Teams using LangChain/LangGraph; Python-first LLM developers

**Strengths:**
1. Zero-config tracing for LangChain apps — install SDK, get traces
2. Excellent trace waterfall visualization
3. Large community and LangChain ecosystem integration

**Weaknesses:**
1. LangChain-centric — poor experience outside the ecosystem
2. No autonomous optimization; evaluation → human action required
3. No agent-specific graders (routing, tool selection, handoff quality)

**Features to steal:**
- Zero-config framework SDK (LangChain wrapping as model for ADK/CX integration)
- Trace waterfall visualization with token-level drill-down
- Annotation queue for systematic human feedback capture

---

### 3. Arize Phoenix

**What they do:** Open-source LLM observability and evaluation with cloud offering.

**Key features:**
- OpenTelemetry-native tracing
- Embedding clustering and visualization (UMAP/t-SNE)
- Hallucination detection
- Dataset curation from traces
- Evals with custom templates
- Drift detection for prompts and embeddings

**Pricing:** Open source (self-hosted free); Arize cloud plans from ~$150/month

**Target audience:** ML engineers who want open-source observability

**Strengths:**
1. Open source — strong community adoption and trust
2. Embedding visualization reveals semantic drift visually
3. OpenTelemetry native — integrates with any OTel-compatible stack

**Weaknesses:**
1. No optimization loop; purely observational
2. Weaker eval UI compared to Braintrust
3. Embedding-focused — less useful for agent workflows

**Features to steal:**
- Embedding clustering for failure visualization (complement our blame maps)
- OpenTelemetry-compatible trace ingestion (critical for ecosystem compatibility)
- Open-source distribution strategy

---

### 4. Humanloop

**What they do:** LLM ops platform for prompt engineering, evaluation, and fine-tuning.

**Key features:**
- Prompt management with version control
- A/B testing for prompts
- Human feedback collection with annotation UI
- Fine-tuning data preparation and model comparison
- Evaluation pipelines with custom metrics
- Team collaboration features

**Pricing:** Free tier; Growth ~$50/month; Enterprise custom

**Target audience:** Product teams (not just ML engineers); non-technical stakeholders

**Strengths:**
1. Best UX for non-technical users — product managers can run evals
2. Fine-tuning preparation workflow closes the feedback loop
3. Strong team collaboration and commenting

**Weaknesses:**
1. Prompt-centric — weak agent/tool use support
2. No autonomous optimization; all evaluation requires human follow-through
3. No statistical significance testing

**Features to steal:**
- Fine-tuning data preparation workflow (policy optimization path)
- Side-by-side model comparison with human voting
- Non-technical user-facing eval creation (NL scorer is good start, keep pushing)

---

### 5. W&B Weave

**What they do:** LLM tracing, evaluation, and experiment tracking built on top of Weights & Biases.

**Key features:**
- LLM call tracking with W&B experiment runs
- Evaluation pipelines with custom scorers
- Dataset versioning (W&B Artifacts)
- Model registry integration
- Lineage tracking across models, datasets, and runs
- Comparison dashboards

**Pricing:** Free tier (100GB); Team $50/seat/month; Enterprise custom

**Target audience:** Research teams and ML engineers already using W&B

**Strengths:**
1. Deep W&B ecosystem integration — best lineage tracking in the space
2. Strong experiment comparison and visualization
3. Battle-tested at massive research scale

**Weaknesses:**
1. Too complex for most product teams
2. LLM features feel bolted-on to ML experiment tracker
3. No autonomous optimization

**Features to steal:**
- Lineage tracking (config → eval → deployment chain)
- Experiment comparison radar charts for multi-metric views
- Dataset artifact versioning with checksum integrity

---

### 6. Patronus AI

**What they do:** Enterprise AI evaluation with focus on safety, compliance, and red-teaming.

**Key features:**
- Hallucination detection (Lynx model)
- Custom safety and compliance metrics
- Automated red-teaming with adversarial scenarios
- Retrieval quality evaluation
- PII and sensitive content detection
- Enterprise audit logging

**Pricing:** Enterprise only (no public pricing; estimated $50K+/year)

**Target audience:** Large enterprises in regulated industries (finance, healthcare, legal)

**Strengths:**
1. Deepest safety and compliance focus in the space
2. Proprietary hallucination detection model (Lynx)
3. Enterprise-grade audit trails for compliance teams

**Weaknesses:**
1. No optimization — evaluation only
2. High cost and long sales cycles
3. No agent-specific evaluation (tool use, routing, handoffs)

**Features to steal:**
- Red-teaming scenario library with industry-specific templates
- Compliance checklist automation (GDPR, HIPAA, SOC2 probe sets)
- PII detection as a hard gate in the eval pipeline

---

### 7. Sierra AI

**What they do:** AI agent platform for enterprise customer service, with Ghostwriter for conversation design.

**Key features:**
- Agent builder (conversational, low-code)
- Conversation journey design and testing
- Real-time escalation analytics
- Customer satisfaction tracking
- Handoff management to human agents
- Enterprise security and compliance

**Pricing:** Enterprise only; estimated $200K–$500K+ ACV

**Target audience:** Fortune 500 companies with large customer service operations

**Strengths:**
1. Deepest CX domain expertise; used at Sonos, Weight Watchers, etc.
2. Fully managed platform — no engineering required to operate
3. Strong escalation and handoff management

**Weaknesses:**
1. Not a developer tool — can't build custom logic
2. Extremely expensive and slow to deploy
3. No developer API or optimization loop

**Features to steal:**
- Customer satisfaction delta tracking after agent changes
- Escalation analytics by intent category and agent path
- Conversation journey visualization (funnel + drop-off)

---

### 8. Observe.AI

**What they do:** Contact center AI for quality assurance automation, compliance monitoring, and agent coaching.

**Key features:**
- Automated conversation QA scoring
- Compliance monitoring (PCI, HIPAA, TCPA)
- Agent coaching with moment identification
- Sentiment analysis and customer satisfaction prediction
- Screen recording + voice AI
- Performance analytics dashboards

**Pricing:** Enterprise only; per-seat pricing typical of CCaaS ($30–$100/seat/month)

**Target audience:** Contact centers with large human agent populations

**Strengths:**
1. Deep contact center domain knowledge
2. Compliance automation is a real money-saver for regulated industries
3. Human agent coaching + AI agent optimization in one platform

**Weaknesses:**
1. Primarily for human agent QA — AI agent optimization is secondary
2. No developer API or programmable evaluation
3. Voice/telephony-centric; weak on chat/digital

**Features to steal:**
- QA scoring rubric templates for common CX scenarios
- Compliance checklist automation
- Moment identification (find the exact turn where the conversation went wrong)

---

### 9. Parloa

**What they do:** AI conversation platform for enterprise contact centers with strong voice AI capabilities.

**Key features:**
- AI agent builder with low-code designer
- Voice AI (phone/IVR) with natural language
- Omnichannel (voice, chat, email, WhatsApp)
- A/B testing for conversation flows
- Analytics and intent tracking
- Enterprise security (SOC2, GDPR, ISO 27001)

**Pricing:** Enterprise only; estimated €150K–€400K/year

**Target audience:** European enterprise contact centers

**Strengths:**
1. Best-in-class voice AI for contact centers
2. True omnichannel (voice + digital unified)
3. Strong European enterprise security certifications

**Weaknesses:**
1. European-centric (limited US presence)
2. Low-code builder limits what developers can do
3. No statistical evaluation or optimization

**Features to steal:**
- Omnichannel conversation flow unification
- Voice transcript analysis and phonetic search
- A/B test for conversation flows with traffic splitting

---

### 10. Google Vertex AI Agent Builder

**What they do:** Google's managed platform for building, deploying, and evaluating AI agents on Google Cloud.

**Key features:**
- Data store connectors (GCS, BigQuery, websites)
- Grounding with Vertex AI Search
- Multi-agent orchestration
- Evaluation service (built-in metrics)
- CCAI (Dialogflow CX) integration
- Enterprise security and VPC-SC
- Deployment to managed Cloud Run

**Pricing:** Pay-per-use (API calls + storage); evaluation ~$0.01–$0.10/query; agent serving at Cloud Run rates

**Target audience:** Enterprises on GCP building AI agents; existing CCAI customers

**Strengths:**
1. Native GCP integration — IAM, VPC-SC, Cloud Logging, BigQuery
2. Best knowledge base grounding in the space (Vertex AI Search)
3. CX Agent Studio integration (bidirectional, live)

**Weaknesses:**
1. GCP lock-in; requires substantial GCP infrastructure
2. No autonomous optimization loop; evaluation is batch/manual
3. Complex pricing; hidden costs in Cloud Run, Vertex AI calls, storage

**Features to steal:**
- Knowledge base grounding integration (connect to customer's existing docs)
- Enterprise IAM-based access control patterns
- Cloud logging + BigQuery export for analytics at scale

---

### Competitive Summary Table

| Platform | Autonomous Optimization | Agent-Specific Evals | Real-Time Telemetry | Statistical Rigor | Auth/Enterprise | Pricing |
|---|---|---|---|---|---|---|
| **AutoAgent** | ✅ Unique | ✅ Strong | ❌ Gap | ✅ Best-in-class | ❌ Gap | OSS/Self-host |
| Braintrust | ❌ | ⚠️ Partial | ✅ SDK push | ❌ | ✅ | $100+/mo |
| LangSmith | ❌ | ⚠️ LC-only | ✅ SDK push | ❌ | ✅ | $39+/mo |
| Arize Phoenix | ❌ | ⚠️ Partial | ✅ OTel | ⚠️ | ✅ | OSS + $150/mo |
| Humanloop | ❌ | ❌ | ⚠️ | ❌ | ✅ | $50+/mo |
| W&B Weave | ❌ | ❌ | ✅ | ⚠️ | ✅ | $50/seat |
| Patronus AI | ❌ | ⚠️ Safety | ⚠️ | ❌ | ✅ Enterprise | $50K+/yr |
| Sierra AI | ❌ | ⚠️ CX only | ⚠️ | ❌ | ✅ Enterprise | $200K+/yr |
| Observe.AI | ❌ | ⚠️ QA only | ✅ | ❌ | ✅ Enterprise | Per-seat |
| Parloa | ❌ | ❌ | ⚠️ | ❌ | ✅ Enterprise | €150K+/yr |
| Vertex Agent Builder | ❌ | ⚠️ Partial | ✅ GCP | ❌ | ✅ GCP IAM | Pay-per-use |

**AutoAgent's unique moat:** Autonomous optimization loop with statistical rigor. Nobody else has this. Every competitor requires humans to interpret eval results and manually make changes. We close the loop.

---

## Part 3: Prioritized Roadmap (47 Items)

### Priority Legend
- **P0** — Blocks demos, sales, or correctness. Fix immediately.
- **P1** — Required for serious customer deployment. Next sprint/cycle.
- **P2** — Competitive parity, DX improvements, or scale features. Next quarter.

### Effort Legend: S (<1 week) | M (1–3 weeks) | L (1–2 months) | XL (2+ months)

---

### P0 — Critical Blockers

| # | Category | Effort | Impact | Description + Acceptance Criteria |
|---|---|---|---|---|
| 1 | Core | S | 10 | **Wire a real agent function into EvalRunner by default.** Currently `agent_fn = mock_agent_response` means all eval scores are simulated. AC: EvalRunner should call the configured agent when `use_mock=False`; add a flag `--real-agent` to `autoagent eval run`; update server to wire `agent.run()` into the eval runner at startup. |
| 2 | UX | S | 9 | **Surface mock mode prominently in the UI.** Dashboard, Eval Runs, and Live Optimize pages must show a persistent warning banner when `use_mock=True`. AC: Yellow banner "Running in mock mode — add API keys for live optimization" visible on all optimization-adjacent pages; dismissible only after keys are configured. |
| 3 | Core | M | 9 | **Replace keyword-based intent classification with LLM-backed classification.** `transcript_intelligence.py` uses `INTENT_KEYWORDS` hardcoded dict. AC: When LLM is available, classify intent via structured LLM call with JSON output; fall back to keyword matching when in mock mode; add accuracy metric to TranscriptReport. |
| 4 | Enterprise | M | 10 | **Add authentication layer.** Zero auth on any endpoint. AC: Optional auth mode (`AUTH_MODE=bearer/none` env var); bearer token validation middleware; API key management endpoint; docs on how to set it up. |

---

### P1 — Required for Real Deployments

| # | Category | Effort | Impact | Description + Acceptance Criteria |
|---|---|---|---|---|
| 5 | Core | L | 10 | **Real-time production telemetry push SDK.** The platform can't watch production traffic today. AC: Python SDK (`autoagent.trace()`) that pushes span telemetry to the AutoAgent server via HTTP; OpenTelemetry-compatible OTLP endpoint as alternative; traces flow into TraceStore and feed the optimization loop. |
| 6 | Integration | M | 9 | **OpenTelemetry-compatible trace ingestion endpoint.** AC: `POST /api/traces/otlp` accepting OTLP JSON/protobuf; mapping from OTel span attributes to AutoAgent trace schema; documentation on how to instrument LangChain, LlamaIndex, and ADK apps. |
| 7 | Enterprise | L | 10 | **Multi-tenancy: org/workspace isolation.** Single-user local tool today. AC: Workspace model in DB (workspace_id foreign key on all records); per-workspace configs, traces, and experiments; workspace admin and member roles; no cross-workspace data leakage. |
| 8 | Infra | L | 9 | **Postgres support as primary DB.** AC: SQLAlchemy ORM layer replacing direct sqlite3 calls; `DATABASE_URL` env var routing to Postgres or SQLite; migration tool (Alembic); tested on Postgres 15+. |
| 9 | Core | M | 8 | **Real traffic-splitting for canary deployments.** Config versioning exists but no actual traffic split. AC: Integration guide + reference implementation for NGINX, Envoy, and AWS ALB weighted routing; AutoAgent webhook to notify on rollout percent change; canary health check polling to auto-promote or rollback. |
| 10 | Integration | M | 8 | **LangChain / LangGraph SDK integration.** LangSmith's biggest moat. AC: `autoagent.langchain.tracer` drop-in replacement for LangSmith tracer; traces from LangChain apps appear in AutoAgent trace viewer; demo notebook. |
| 11 | Integration | M | 8 | **Webhook support for external alerting.** AC: `POST /api/webhooks` CRUD; configurable events (optimization_complete, eval_failed, gate_tripped, loop_stalled); signed payloads with HMAC-SHA256; integration docs for Slack, PagerDuty, and Opsgenie. |
| 12 | Core | M | 8 | **PII detection as a hard gate.** Patronus does this; we don't. AC: Configurable PII scanner (regex + optional LLM-based); hard gate type `pii_leak`; any proposed mutation that introduces PII patterns is rejected with evidence; configurable sensitivity (names, emails, phone, SSN, credit card). |
| 13 | UX | M | 8 | **Trace waterfall visualization.** We have a traces page but need rich span-level waterfall. AC: Hierarchical span tree view with timing bars; LLM call token counts; tool call args/results expandable; filtering by span type; linked from Blame Map clusters. |
| 14 | DevEx | S | 7 | **Python SDK with `pip install autoagent-sdk`.** AC: Minimal SDK (`autoagent_sdk.trace()`, `autoagent_sdk.eval()`, `autoagent_sdk.optimize()`); pypi package; 5-minute quickstart in README; no FastAPI server required for trace submission. |
| 15 | Docs | S | 7 | **API key setup wizard in the UI.** AC: First-run modal (or Settings page) with API key fields, provider links, and a "Test connection" button that runs a mock LLM call; keys stored in `.env` via `/api/config/env` endpoint; auto-dismisses when first real optimization completes. |
| 16 | Core | M | 8 | **Live conversation monitoring feed.** Ingest agent conversations from production in real time. AC: SSE stream or WebSocket feed at `/api/conversations/stream`; conversations appear in the UI within 5 seconds of being logged; configurable sampling rate. |
| 17 | UX | M | 7 | **Annotation / labeling queue for human feedback.** Braintrust and LangSmith both have this. AC: UI panel showing unlabeled conversations; thumbs up/down + freeform comment; labels stored as preference data; feed into judge calibration. |
| 18 | Integration | M | 7 | **Slack integration for loop status.** AC: Slack webhook config in Settings; daily digest of optimization loop status; alerts on gate trips and significant score changes; `/autoagent optimize` Slack command to trigger a cycle from Slack. |
| 19 | Enterprise | M | 7 | **Audit log for all config deployments.** AC: Immutable append-only event log of all deploy actions (who, when, what, from/to version, rollout percent); accessible via `/api/audit` and exportable as JSONL; surfaced in Settings → Audit Log page. |
| 20 | Core | L | 8 | **Agent framework SDK connectors.** AC: Drop-in integrations for LlamaIndex, CrewAI, AutoGen, and OpenAI Swarm; each connector wraps the agent and emits spans compatible with AutoAgent's trace schema; zero code changes to agent logic required. |

---

### P2 — Competitive/Scale/Polish

| # | Category | Effort | Impact | Description + Acceptance Criteria |
|---|---|---|---|---|
| 21 | UX | M | 7 | **Embedding clustering for failure visualization.** Arize Phoenix does this well. AC: Embed failed trace summaries; visualize clusters in 2D (UMAP); cluster label auto-generated by LLM; color-coded by grader that failed; linked to Blame Map. |
| 22 | Competitive | M | 7 | **Prompt playground with side-by-side comparison.** Braintrust's killer feature. AC: Select two config versions; send the same test prompt to both; see responses side-by-side with score diff; save comparison as eval case. |
| 23 | DevEx | S | 7 | **GitHub Actions workflow template.** AC: Published `autoagent/eval-action@v1`; run evals as CI check on PR; PR comment with score diff vs. main; block merge if score below threshold; YAML template in repo. |
| 24 | Core | L | 8 | **Fine-tuning data export pipeline.** Humanloop does this. AC: Export curated conversation pairs (good/bad) as JSONL for SFT/DPO; format for OpenAI fine-tuning API, Vertex AI SFT, and Anthropic Constitutional AI; one-click export from Intelligence Studio. |
| 25 | Integration | M | 6 | **Datadog / Grafana metrics export.** AC: StatsD/Prometheus metrics for agent health score, eval pass rate, optimization cycle count; export to Datadog via DogStatsD; Grafana dashboard template (JSON) included in repo. |
| 26 | UX | S | 6 | **Keyboard shortcut system.** Already in Settings page scaffold. AC: Global shortcuts for common actions (run eval, trigger optimize, pause loop, open trace); shortcut cheat sheet modal (? key); persist customizations to localStorage. |
| 27 | Core | M | 7 | **Adversarial red-teaming scenario library.** Patronus does this. AC: Built-in scenario templates by industry (e-commerce, financial services, healthcare, HR); each scenario is a set of adversarial eval cases; one-click add to eval suite; community-contributed via PR. |
| 28 | Infra | M | 6 | **Async background job queue (Celery or ARQ).** AC: Replace ad-hoc `TaskManager` thread pool with proper async queue; persistent job state survives server restart; dead letter queue integration; job result webhooks. |
| 29 | Enterprise | L | 7 | **SSO / SAML 2.0 integration.** AC: SAML 2.0 IdP integration (Okta, Azure AD, Google Workspace); just-in-time provisioning; role mapping from IdP groups; tested with at least 2 IdPs. |
| 30 | Competitive | M | 6 | **Customer satisfaction delta tracking.** Sierra's core metric. AC: Map optimization cycles to CSAT/NPS change; show pre/post satisfaction score alongside eval scores; alert when optimization improves eval but degrades satisfaction. |
| 31 | Core | M | 7 | **Compliance probe sets (GDPR, HIPAA, SOC2).** AC: Pre-built eval case sets that probe for compliance-relevant behaviors; configurable by regulation; auto-run as hard gate before any deployment; compliance report PDF export. |
| 32 | DevEx | S | 6 | **`autoagent init --framework` scaffolding.** AC: `--framework langchain|llamaindex|openai|anthropic|adk` generates a starter agent + eval cases + autoagent.yaml configured for that framework; runnable in under 5 minutes. |
| 33 | UX | M | 6 | **Conversation journey funnel visualization.** AC: Show the multi-turn journey from entry intent to resolution; drop-off rate at each turn; escalation rate by intent; filter by date range and agent version; linked from Intelligence Studio. |
| 34 | Core | M | 6 | **Voice transcript analysis.** Parloa and Observe.AI advantage. AC: Accept audio files in IntelligenceStudio (MP3, WAV); transcribe via Whisper or Google STT; same analytics pipeline as text transcripts; phoneme-level search for key phrases. |
| 35 | Integration | S | 6 | **VS Code extension.** AC: Run evals from command palette; view optimization status; trigger a cycle; see experiment card for last change; published to VS Code Marketplace. |
| 36 | Infra | M | 6 | **Multi-region deployment support.** AC: Stateless API server with external Postgres; deployment templates for GCP, AWS, Azure; data residency config (EU/US/APAC); tested with latency targets <200ms per region. |
| 37 | Competitive | L | 7 | **Native A/B traffic splitting.** AC: AutoAgent-managed traffic proxy (or Envoy/NGINX config generator); percentage-based routing to config versions; real-time metrics per variant; auto-promote winner when significance reached; dashboard shows live split. |
| 38 | Core | M | 6 | **Lineage graph: config → eval → deployment.** W&B's strength. AC: Visual DAG showing the provenance of each deployed config (which evals it passed, which mutations produced it, which baseline it improved on); click any node to see details. |
| 39 | UX | S | 5 | **Dark mode.** AC: `prefers-color-scheme` detection + manual toggle in Settings; all 50+ pages styled correctly; system preference persisted to localStorage. |
| 40 | DevEx | M | 6 | **Notebook integration (Jupyter / Colab).** AC: `autoagent_sdk.notebook` module; cell magic `%%autoagent_eval` runs an eval and displays results inline; `%%autoagent_trace` shows a trace waterfall; Google Colab template published. |
| 41 | Enterprise | L | 7 | **SLA monitoring and alerting.** AC: Configurable SLA thresholds per metric (latency p95, error rate, satisfaction score); alerting when SLA is breached; runbook auto-suggestion when SLA breach detected; dashboard widget for SLA health. |
| 42 | Integration | M | 5 | **Zendesk / Salesforce Service Cloud connector.** AC: Pull conversation transcripts from Zendesk/Salesforce via API; map to AutoAgent transcript format; schedule automatic import; tag by ticket category for filtered analysis. |
| 43 | Docs | M | 6 | **Interactive getting-started tour.** AC: In-app guided tour (Shepherd.js or similar) that walks new users through: view a trace → read a blame map → trigger an eval → review an experiment card; completable in <10 minutes with demo data. |
| 44 | Core | L | 7 | **Multi-agent topology optimizer.** Currently mutations touch individual agent configs. AC: Topology mutation can add, remove, or reorder agents in a pipeline; validate with integration eval; risk class = high; rollback to previous topology on regression. |
| 45 | DevEx | S | 5 | **`autoagent doctor` command.** AC: Checks Python version, Node version, API key presence and validity, DB accessibility, server health, venv activation; colored pass/fail output; suggests fixes for each failure. |
| 46 | Competitive | M | 6 | **Knowledge base grounding evaluation.** Vertex AI Agent Builder advantage. AC: Eval mode that measures retrieval accuracy against a knowledge base; measures whether the agent cited the right document; F1 score on retrieved vs. relevant docs; hallucination rate when grounding is available vs. not. |
| 47 | Infra | S | 5 | **Health endpoint with dependency checks.** Current `/api/health` exists but may not check all dependencies. AC: `/api/health/deep` checks DB connectivity, LLM provider reachability, disk space, and memory; returns structured JSON with per-dependency status; used by Docker health check and load balancer probes. |

---

## Roadmap Summary by Theme

| Theme | P0 | P1 | P2 | Total |
|---|---|---|---|---|
| Core (loop, evals, telemetry) | 3 | 7 | 7 | 17 |
| Enterprise (auth, multi-tenancy, compliance) | 1 | 4 | 4 | 9 |
| Integration (SDK, webhooks, connectors) | 0 | 4 | 5 | 9 |
| UX/DevEx | 1 | 3 | 8 | 12 |
| **Total** | **4** | **16** | **27** | **47** |

---

## 90-Day Execution Plan

**Month 1 — Make it real:**
- Ship P0 items: real agent wiring (#1), mock mode warning (#2), LLM-backed transcript classification (#3), auth layer (#4)
- Start: real-time telemetry SDK (#5), OTel endpoint (#6)

**Month 2 — Make it deployable:**
- Ship: OTel ingestion, annotation queue, Postgres support, webhook support, GitHub Actions template
- Start: multi-tenancy, LangChain integration

**Month 3 — Make it sellable:**
- Ship: multi-tenancy, LangChain/LlamaIndex SDKs, Slack integration, audit log, compliance probe sets
- Start: SSO, fine-tuning export, embedding clustering

---

## Key Bets

1. **Real-time telemetry is the unlock** — without push telemetry from production, we're an offline optimizer. This is the gap that makes the "continuous" in continuous optimization real.
2. **Auth + multi-tenancy unlocks enterprise** — every other item on the roadmap is moot without this for paying customers.
3. **LangChain integration is the distribution play** — LangSmith has 100K+ users because of LangChain integration. A drop-in tracer is a trojan horse.
4. **Statistical rigor is the defensible moat** — no competitor has bootstrap CI + anti-Goodhart guards + O'Brien-Fleming. Double down on communicating this.
