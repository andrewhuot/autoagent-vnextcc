# Technical PM Review - Competitive Analysis + Roadmap Backlog

Research snapshot date: March 29, 2026

Method:
- Reviewed the required repo context: `README.md`, `docs/platform-overview.md`, `docs/BEGINNER_USER_GUIDE.md`, `docs/architecture.md`, every file in `web/src/pages/*.tsx`, every file in `api/routes/*.py`, `runner.py`, and the `builder/` directory.
- Ran a live route sweep across 45 frontend routes with browser automation and screenshots.
- Cross-checked product claims against implementation details in the UI, API, CLI, and Builder subsystems.
- Researched the 10 requested competitors using official product, pricing, and documentation pages.

Important framing:
- When I say "what we do better," I mean where AutoAgent's product direction or existing architecture is stronger, not where execution maturity is currently superior. On polish and reliability, several competitors are materially ahead.

## Part 1. Product Assessment

### Executive summary

AutoAgent is not a thin mock demo. There is real product substance here, especially in the Builder Workspace, the CLI, the eval/optimize/deploy pipeline, the traces/conversations/configs surfaces, and the Google-oriented CX/ADK import and deploy flows. The codebase has enough real implementation to support a compelling story.

At the same time, the product is not yet the fully coherent "continuous optimization platform" the docs imply. The current reality is a hybrid:
- one strong, real subsystem: Builder Workspace
- one strong, curated story: Demo plus Builder Demo plus Intelligence Studio
- several solid operational surfaces: evals, traces, conversations, configs, deploy, loop, events, notifications, runbooks
- several demo-grade or simulated surfaces: Assistant, Live Optimize, parts of AutoFix, parts of Experiments
- several broken or contract-drifted surfaces: Context Workbench, Registry, Blame Map, Scorer Studio, Reward Studio, Preference Inbox, Policy Candidates, and parts of Change Review
- four explicit shell pages in the main app nav: Knowledge, Reviews, Sandbox, and What-If

My PM verdict is straightforward:
- The product direction is differentiated and worth investing in.
- The fastest path to executive confidence is not adding more new tabs.
- The fastest path is stabilizing the existing surfaces, removing truth gaps, and turning already-written backend capabilities into polished, trustworthy product flows.

### Scorecard

| Dimension | Score | Notes |
| --- | --- | --- |
| Product differentiation | 8/10 | Builder Workspace + closed-loop optimization + Google integration is a distinctive mix. |
| Demo potential | 7/10 | Very strong if tightly scripted through the best routes. |
| Product truthfulness | 5/10 | Docs and UI promise more cohesion and readiness than the current implementation supports. |
| Self-serve onboarding | 4/10 | First-run experience is confusing and inconsistent with docs. |
| Production readiness | 3/10 | Missing enterprise basics and too many broken or simulated surfaces. |
| Platform depth | 7/10 | Backend and CLI breadth are deeper than the front-end currently exposes. |

### What the product claims vs. what it actually does today

| Product claim | What is true today | Assessment |
| --- | --- | --- |
| AutoAgent is a continuous optimization platform for AI agents. | Broadly true in architecture. The codebase supports trace -> diagnose -> eval -> optimize -> deploy -> learn. Some of that loop is real, some is mock-mode or simulated. | Partially true |
| It works out of the box and lands users in a demo-ready dashboard. | `./start.sh` opens `http://localhost:5173`, but `/` routes to Builder Workspace, not `/dashboard`. The README says users land on the dashboard. | False as written |
| The Assistant can build, optimize, and debug agents through natural language. | The Assistant UI renders and streams, but `api/routes/assistant.py` is backed by in-memory sessions and a `MockOrchestrator`. | Mostly demo-grade |
| The Builder Workspace is a serious authoring and approval surface. | True. `builder/store.py`, `builder/projects.py`, `builder/execution.py`, `builder/permissions.py`, `builder/orchestrator.py`, and related services form a real SQLite-backed subsystem. | True |
| The platform has advanced reward, preference, registry, blame, scorer, and policy tooling. | Several of these APIs exist, but multiple pages crash because frontend assumptions do not match backend response shapes. | Mostly half-built |
| Knowledge mining, reviews, sandboxing, and what-if replay are part of the product. | Backend APIs exist for some of these concepts, but the visible pages are still explicit "Coming soon" shells. | Overstated |
| Google ecosystem integration is a core strength. | True. The app and CLI both contain meaningful ADK and CX import/export/deploy flows, and the product leans into A2A and Vertex context. | True |
| The product is ready for broad executive exploration. | Not yet. It can support a good 15-minute demo, but only if route selection is curated. Free exploration exposes blank pages, crash states, shells, and simulated behavior. | Not ready |

### Surface readiness snapshot

Live route sweep summary:
- Total routes tested: 45
- Functional: 31
- Warning state: 10
- Shell pages: 4

What is strongest:
- `/`, `/builder`, `/builder/demo`
- `/demo`, `/dashboard`
- `/evals`, `/configs`, `/conversations`, `/deploy`, `/loop`, `/traces`, `/events`
- `/skills`, `/intelligence`, `/agent-skills`, `/notifications`
- `/cx/import`, `/cx/deploy`, `/adk/import`, `/adk/deploy`

What renders but shows instability:
- `/dashboard` and `/optimize` log chart sizing warnings
- `/changes` renders but the page issues 404s to backend endpoints

What currently crashes or blanks because of contract drift:
- `/context`
- `/registry`
- `/blame`
- `/scorer-studio`
- `/reward-studio`
- `/preference-inbox`
- `/policy-candidates`

What is explicitly a shell:
- `/knowledge`
- `/reviews`
- `/sandbox`
- `/what-if`

### What is real vs. half-built vs. shell

#### Real and demoable today

Builder Workspace:
- The Builder subsystem is the most credible part of the platform.
- It has real persistence, projects, sessions, tasks, proposals, approvals, artifacts, releases, worktrees, sandbox runs, eval bundles, trace bookmarks, permissions, and event streaming primitives.
- It already feels like the seed of a differentiated "agent operating system" rather than a mock dashboard.

Core operational surfaces:
- Evals, configs, deploy, conversations, traces, events, loop monitor, and notifications all have real backend routes and working pages.
- These pages are not all feature-rich, but they do enough to demonstrate real platform behavior.

Google-oriented import/deploy flows:
- CX import/deploy and ADK import/deploy are meaningful and not just decorative.
- `runner.py` deepens this story with CLI commands that support import/export/deploy workflows.

CLI breadth:
- `runner.py` exposes a large command surface: init, build, eval, optimize, config, deploy, explain, diagnose, replay, runbooks, registry, traces, scorers, datasets, outcomes, rewards, preferences, RL, CX, ADK, demo, and more.
- The CLI is ahead of the UI in breadth and indicates there is more product here than the front-end currently surfaces.

#### Half-built, simulated, or fragile

Assistant:
- Functional front-end.
- Simulated backend orchestration.
- In-memory sessions only.
- Strong demo impression, weak production truth.

Live Optimize:
- Good visual idea.
- The SSE endpoint emits explicitly simulated cycle events.
- It sells the right story but is not yet actual live optimization telemetry.

AutoFix and QuickFix:
- The page renders and the flow is plausible.
- The repo still contains explicit placeholder behavior in adjacent fix-generation routes.
- This area needs one real constrained proposal pipeline, not two overlapping half-implementations.

Experiments and advanced ops surfaces:
- Several pages render and tell the right story, but often with mock archives, empty states, or partial backend depth.
- They are credible as roadmap previews, not yet credible as category-defining features.

#### UI shells

These should not be in the main nav in their current state:
- Knowledge
- Reviews
- Sandbox
- What-If

The issue is not just incompleteness. The issue is that these shells sit beside serious surfaces and reduce overall trust immediately.

#### API-first or backend-ahead-of-UI areas

There is hidden value in the repo that is not yet properly productized:
- `api/routes/knowledge.py`
- `api/routes/what_if.py`
- `api/routes/collaboration.py`
- `api/routes/impact.py`
- `api/routes/datasets.py`
- `api/routes/outcomes.py`
- `api/routes/a2a.py`

This is a meaningful PM insight: the platform is not empty. It is under-packaged.

### Value proposition by persona

#### Agent builder

Current value:
- Builder Workspace gives a tangible way to structure work, approvals, tasks, artifacts, and releases.
- Intelligence Studio is a compelling concept for turning transcript intelligence into agent improvements.
- Skills, Agent Skills, CX import, and ADK import point toward a full build pipeline.

Current frustration:
- Too much of the surrounding product is unstable.
- The main landing experience is dense and not beginner-friendly.
- Several advanced pages that should deepen trust currently do the opposite.

Bottom line:
- This persona can see the vision very clearly.
- They will also trip over the gaps fastest.

#### ML engineer / evaluation engineer

Current value:
- Evals, traces, configs, conversations, experiments, scorer concepts, and event logs are the most relevant surfaces.
- The CLI is especially promising for this user.
- Phoenix/Braintrust-style workflows are conceptually present.

Current frustration:
- The most advanced analysis pages are some of the most broken.
- Reward, preference, registry, blame, and scorer workflows are exactly where this user wants rigor, and that is where contract drift is most visible.

Bottom line:
- The persona fit is good.
- The current implementation maturity is not yet good enough.

#### Platform team / AI platform owner

Current value:
- Versioning, deploy, loop, notifications, approvals, permissions, audit-style event logs, and A2A alignment are all directionally strong.
- Google ecosystem alignment is a real strategic differentiator.

Current frustration:
- Missing enterprise basics: auth, SSO, RBAC at product boundary, multi-tenancy, admin controls, retention policy, and clear audit lineage.
- Too many surfaces still read like internal prototypes rather than a governed platform.

Bottom line:
- This persona will like the architecture.
- They will not yet approve the platform for broad internal rollout.

### Onboarding and time to first value

Current onboarding has three problems:
- The docs describe a dashboard-first first-run path, but the app lands on Builder.
- Mock mode is disclosed through a banner, but the banner is inserted into the root flex layout in a way that visibly wastes a large chunk of viewport width on multiple routes.
- The main route drops new users into the densest surface in the product without enough narrative guidance.

Time to first value today:
- 3-5 minutes if you intentionally start on `/demo`, `/builder/demo`, or a curated dashboard flow
- 10-20 minutes if you are technical and happy exploring CLI plus UI
- indeterminate if you are a first-time non-technical user who follows the README literally

Best current first-run experience:
- Start on `Builder Demo`
- Then show `Demo`
- Then show `Intelligence Studio`
- Then show `Builder Workspace`

Worst current first-run experience:
- Start on `/`
- Open random tabs from the left nav
- Hit a shell or blank page before understanding what the product is

### What would make a VP say "wow" in 15 minutes

- The Builder Demo is genuinely strong. It gives a clear act-based narrative from intent to plan to approval to artifact to release.
- The Builder Workspace has a real object model. Projects, sessions, tasks, proposals, approvals, artifacts, and release candidates are much more impressive than a shallow prompt playground.
- Intelligence Studio is the right strategic bet. "Ask what is going wrong in conversations, then convert that into a reviewable agent change" is a board-level story.
- The platform breadth is impressive when curated: demos, evals, traces, configs, deploy, runbooks, skills, ADK, CX, notifications, and Builder make the product feel larger than a single-feature tool.
- Google-native positioning is a meaningful asset. ADK, CX, A2A, and Vertex context create a credible ecosystem angle competitors cannot all match.

### What would make a VP say "this isn't ready" in 15 minutes

- Blank or crashing pages in obvious strategic areas.
- Four "Coming soon" pages in the primary nav.
- Simulated behavior presented too close to real behavior without enough guardrails.
- Docs that say one thing and first-run product behavior that does another.
- A layout bug large enough to visibly compress the product on high-value demo routes.
- No clear product boundary around what is GA, beta, internal, or demo-only.
- Missing enterprise controls that any platform buyer will ask about immediately.

### Overall PM verdict

The right near-term strategy is not "add more features."

The right strategy is:
- fix the truth gap
- stabilize the broken analysis surfaces
- hide or productize the shells
- turn backend substance into polished UI
- then lean hard into the differentiated story: Builder Workspace + Intelligence Studio + closed-loop optimization + Google-native deployment and interop

If we do that, this product can move from "ambitious internal prototype" to "credible category-shaping platform." If we do not, every new feature will just widen the trust gap.

## Part 2. Competitive Landscape

### Overall market read

The market splits into three clear lanes:
- AI engineering platforms: Braintrust, LangSmith, Arize Phoenix, Humanloop, W&B Weave, Patronus
- customer service AI platforms: Sierra, Observe.AI, Parloa
- hyperscaler platform context: Google Vertex AI Agent Builder

AutoAgent sits awkwardly but promisingly across all three:
- it has the observability and eval ambition of the AI engineering tools
- it has the workflow and deployment ambition of customer-service AI platforms
- it has the ecosystem ambition of a Google-native platform extension

That is a differentiated position, but only if the product becomes much more coherent.

### 1. Braintrust

What they do:
- Braintrust is an AI eval and observability platform focused on traces, experiments, scores, prompt iteration, online scoring, and production quality workflows.

Key features:
- strong tracing and trace query capabilities
- production-to-eval workflow
- experiments and datasets
- topics, custom charts, environments, and human review configurations on higher tiers
- AI assistant workflows like Loop for scorer and dataset generation

Pricing model:
- Free: $0/month, 1M spans, 1 GB storage, 10k scores, 14-day retention
- Pro: $249/month plus usage, 5 GB storage, 50k scores, 30-day retention
- Enterprise: custom, with privacy-sensitive deployment options

Target audience:
- AI engineers, AI product teams, and quality/reliability owners who need a shared eval and observability workspace

What they do better than us:
- much more mature observability and eval workflow
- clearer pricing and plan boundaries
- better trace-to-eval-to-monitor cohesion
- better collaboration primitives for review, topics, and charts

What we do better than them:
- stronger Builder Workspace concept with approvals, artifacts, and release objects
- stronger Google CX and ADK story
- more opinionated end-to-end "agent operating system" direction

Features we should steal:
- topics and custom charting
- trace query engine and saved views
- production failures to eval cases conversion
- plan clarity around retention, usage, and enterprise controls

Sources:
- [Home](https://www.braintrust.dev/)
- [Pricing](https://www.braintrust.dev/pricing)
- [Docs](https://www.braintrust.dev/docs)

### 2. LangSmith

What they do:
- LangSmith is LangChain's tracing, evaluation, prompt management, and deployment platform for agent teams.

Key features:
- tracing and observability
- offline and online evaluations
- prompt hub, playground, and canvas
- annotation queues and monitoring alerts
- LangSmith Deployment with durable execution, streaming, and human-in-the-loop primitives

Pricing model:
- Developer: free, 1 seat, 5k base traces/month, then pay-as-you-go
- Plus: $39/seat/month, 10k base traces/month, includes 1 dev-sized deployment
- Enterprise: custom, with hybrid/self-hosted, SSO, RBAC, and support

Target audience:
- developers building agents, especially teams already in the LangChain/LangGraph ecosystem

What they do better than us:
- tighter integration of tracing, evals, prompts, and runtime deployment
- better prompt management and collaboration
- more mature production deployment story
- better documentation and workflow clarity

What we do better than them:
- better Builder-style workspace and approval mental model
- more explicit optimization-loop framing
- stronger Google-oriented migration and deployment opportunity

Features we should steal:
- prompt hub plus commit plus webhook flow
- annotation queues
- online eval workflow directly from observability
- deployment runtime primitives like durable execution and resumable runs

Sources:
- [Pricing](https://www.langchain.com/pricing-langsmith)
- [Evaluation docs](https://docs.langchain.com/langsmith/evaluation)
- [Prompt engineering docs](https://docs.langchain.com/langsmith/prompt-engineering)
- [Deployment docs](https://docs.langchain.com/langsmith/deployment)

### 3. Arize Phoenix

What they do:
- Arize Phoenix is the leading open-source AI observability and evaluation product in this set, with a commercial upsell to Arize AX.

Key features:
- open-source tracing built on OpenTelemetry and OpenInference
- prompt management and prompt playground
- datasets and experiments
- client-side and server-side evaluation
- strong instrumentation ecosystem
- AX layers in online evals, monitors, custom metrics, and enterprise ops

Pricing model:
- Phoenix OSS: free and open source, self-hosted
- AX Free: free, 25k spans/month, 1 user, 7-day retention
- AX Pro: $50/month, up to 3 users, 100k spans/month
- AX Enterprise: custom, SaaS or self-hosted

Target audience:
- AI engineers and ML platform teams who want open standards, self-hosting, or developer-first observability

What they do better than us:
- open-source credibility
- better instrumentation story
- clearer eval taxonomy and trace plumbing
- stronger developer trust because the product is explicit about what is OSS vs enterprise

What we do better than them:
- more opinionated end-to-end product narrative around change proposals, approvals, and release
- stronger builder workflow concept
- more obvious Google CX and ADK connector story

Features we should steal:
- explicit OSS vs enterprise packaging
- OpenTelemetry/OpenInference-first UX
- better prompt playground and experiment workflow
- online eval plus monitors separation as a clean product boundary

Sources:
- [Pricing](https://arize.com/pricing)
- [Phoenix overview](https://arize.com/docs/phoenix)
- [Tracing docs](https://arize.com/docs/phoenix/tracing/concepts-tracing/how-tracing-works)
- [Evaluation docs](https://arize.com/docs/phoenix/evaluation/how-to-evals)

### 4. Humanloop

What they do:
- Humanloop historically offered enterprise prompt management, evaluations, observability, and deployment controls for LLM applications.

Key features:
- prompt and prompt-file management
- evaluations and datasets
- observability
- deployment options for enterprise environments
- strong early focus on safe enterprise AI operations

Pricing model:
- historically enterprise and sales-led
- as of March 29, 2026, the public site is an announcement that Humanloop joined Anthropic, and the docs changelog says the platform was sunset on September 8, 2025

Target audience:
- historically enterprise AI product teams
- today, not a live go-forward competitor in the same way as the others

What they did better than us:
- cleaner prompt and environment management concepts
- stronger product truthfulness around enterprise deployment options
- simpler positioning

What we do better than them:
- AutoAgent is still an actively developed product codebase
- broader Builder and Google integration direction
- more complete vision for closed-loop optimization

Features we should steal:
- prompt registry ergonomics
- environment promotion clarity
- migration and packaging discipline

Sources:
- [Announcement home page](https://humanloop.com/)
- [Docs home](https://humanloop.com/docs)
- [Sunset changelog](https://humanloop.com/docs/changelog/2025/03)
- [Deployment options](https://humanloop.com/docs/reference/deployment-options)

### 5. W&B Weave

What they do:
- Weave is W&B's platform for tracing, scoring, evaluation, cost tracking, playground workflows, and production monitoring for GenAI apps.

Key features:
- tracing and evaluation
- scorers and builtin scorers
- cost estimates and inference integration
- guardrails and monitoring
- trace trees purpose-built for agentic systems
- broader W&B ecosystem benefits like lineage and CI/CD automation

Pricing model:
- Free: $0/month
- Pro: starts at $60/month
- Enterprise: custom
- usage charges apply for tracked hours, storage, Weave ingestion, and inference

Target audience:
- AI developers already using W&B or teams who want GenAI observability inside a larger MLOps platform

What they do better than us:
- broader platform maturity
- trace tree UX
- guardrails and monitoring
- lineage and ecosystem integration
- clearer enterprise packaging

What we do better than them:
- stronger human approval and proposal review direction
- better Google CX and ADK migration angle
- better Builder-style operational workspace concept

Features we should steal:
- trace tree visualization
- scoring primitives that return structured dictionaries and explanations
- integrated cost visibility
- clearer production monitoring language

Sources:
- [Pricing](https://wandb.ai/site/pricing/)
- [Weave overview](https://wandb.ai/site/weave/)
- [Tracing docs](https://docs.wandb.ai/weave/guides/tracking/tracing/)
- [Scorers docs](https://docs.wandb.ai/weave/guides/core-types/scorers)

### 6. Patronus AI

What they do:
- Patronus plays in AI evaluation, security, guardrails, and supervision. The current public identity is mixed: the homepage is now heavily research-oriented, but product pages still describe evaluation, guardrails, datasets, and Percival supervision.

Key features:
- AI evaluation and guardrails
- strong hallucination and safety benchmarking story
- Patronus API with usage-based access
- Percival for agentic supervision over traces and 20+ failure modes
- domain datasets and benchmarks such as FinanceBench and EnterprisePII

Pricing model:
- self-serve API announcement described usage-based pricing and $5 in free credits
- current broader platform pricing is not clearly public and appears sales-led

Target audience:
- AI engineering teams focused on safety, hallucination detection, security, and supervised agent debugging

What they do better than us:
- sharper supervision and failure-mode taxonomy
- stronger benchmark and research credibility
- tighter safety and security brand

What we do better than them:
- broader product surface for building and shipping agents
- stronger UI-based workflow story around Builder and releases
- more concrete Google ecosystem opportunity

Features we should steal:
- Percival-like trace supervision
- benchmark-driven product marketing
- security and guardrail posture tied to named failure modes

Sources:
- [Self-serve API announcement](https://www.patronus.ai/announcements/patronus-ai-launches-industry-first-self-serve-api-for-ai-evaluation-and-guardrails)
- [Percival](https://www.patronus.ai/percival)
- [Customer service solution page](https://www.patronus.ai/customer-service)

### 7. Sierra AI

What they do:
- Sierra is a customer service AI platform with a highly polished enterprise product that spans build, test, optimize, memory, live assist, voice, and outcome-based pricing.

Key features:
- Agent OS positioning
- Agent Studio
- Insights and optimization
- Live Assist for human agents
- omnichannel deployment across chat, SMS, WhatsApp, email, voice, and ChatGPT
- Agent Data Platform for memory and personalization
- outcome-based pricing

Pricing model:
- outcome-based, sales-led
- Sierra publicly states it gets paid when it completes valuable tasks or outcomes

Target audience:
- large enterprise customer support organizations and digital customer experience teams

What they do better than us:
- executive polish
- omnichannel customer-service specialization
- business-outcome framing
- memory and personalization packaging
- clear enterprise readiness

What we do better than them:
- stronger horizontal AI engineering and optimization tooling direction
- more direct visibility into low-level traces, configs, approvals, and optimization mechanics
- better Google AI infrastructure adjacency

Features we should steal:
- outcome-based ROI packaging
- Agent OS narrative discipline
- memory and data platform story
- Live Assist bridge between autonomous and human service

Sources:
- [Home](https://sierra.ai/)
- [Outcome-based pricing](https://sierra.ai/blog/outcome-based-pricing-for-ai-agents)
- [Live Assist](https://sierra.ai/product/live-assist)
- [Agent Data Platform](https://sierra.ai/blog/agent-data-platform)

### 8. Observe.AI

What they do:
- Observe.AI is a contact-center AI platform spanning AI agents, copilots, conversation intelligence, QA, coaching, and enterprise analytics.

Key features:
- VoiceAI Agents and ChatAI Agents
- Agent Copilot, Coaching Copilot, Insights Copilot
- conversation intelligence
- Auto QA and manual QA
- reporting, analytics, integrations, and trust/security packaging

Pricing model:
- packaged but sales-led
- public pricing page lists product bundles like VoiceAI Agents, Real-time AI, Post-interaction AI, Enterprise Advanced, and Enterprise Unlimited
- no simple public self-serve dollar pricing

Target audience:
- enterprise contact centers, especially regulated or high-volume environments

What they do better than us:
- domain focus and contact-center credibility
- QA and coaching workflow maturity
- stronger enterprise packaging
- clearer buyer messaging

What we do better than them:
- deeper agent optimization and engineering tooling direction
- more explicit closed-loop product architecture
- broader potential to serve as a build platform, not just a contact-center optimization layer

Features we should steal:
- QA plus coaching operational loop
- packaging by buyer problem, not just technical feature
- stronger trust/security presentation

Sources:
- [Home](https://www.observe.ai/)
- [Pricing](https://www.observe.ai/pricing)

### 9. Parloa

What they do:
- Parloa is an AI Agent Management Platform for customer service and contact centers, oriented around the full AI agent lifecycle from design to testing to scale to optimization.

Key features:
- design and integrate
- simulations, evaluations, and versioning
- agent composition across chat, messaging, and voice
- insights dashboards, data hub, and conversation store
- integrations with enterprise CX systems

Pricing model:
- sales-led
- no public self-serve pricing

Target audience:
- enterprise customer-service organizations deploying AI agents at scale

What they do better than us:
- tighter customer-service lifecycle packaging
- better integration and channel story
- clearer testing-to-production flow for enterprise CX buyers

What we do better than them:
- more general-purpose AI engineering platform potential
- stronger Builder approvals and artifact model
- better Google AI ecosystem opportunity

Features we should steal:
- AI agent lifecycle framing
- simulation and evaluation as explicit pre-go-live phases
- data hub and conversation store messaging

Sources:
- [Home](https://www.parloa.com/)
- [Platform](https://www.parloa.com/platform/)

### 10. Google Vertex AI Agent Builder

What they do:
- Vertex AI Agent Builder is Google's enterprise platform for building, deploying, tracing, governing, and scaling agents on top of Vertex AI and Agent Engine.

Key features:
- ADK and open framework support
- Model Garden access
- tracing and debugging
- A2A interoperability
- enterprise governance and security
- Agent Engine runtime
- compute, memory, model, and tool-based pricing

Pricing model:
- Agent Engine compute: $0.00994/vCPU-hour
- Agent memory: $0.0105/GiB-hour
- model usage priced separately via Model Garden
- preview features may require sales contact

Target audience:
- enterprise platform teams and developers building agents on Google Cloud

What they do better than us:
- runtime scale
- governance
- integration with Google's broader AI and data platform
- enterprise security, infra, and procurement readiness

What we do better than them:
- more opinionated human review and Builder UX
- more explicit optimization-loop storytelling
- better chance to be a high-level operational layer if positioned as complementary to Vertex rather than competitive with it

Features we should steal:
- governance posture
- runtime and memory concepts
- A2A interop as a first-class product capability
- pricing transparency for the core runtime

Sources:
- [Product page](https://cloud.google.com/products/agent-builder)

### Comparison matrix

| Competitor | Primary lane | Public pricing clarity | Strongest advantage | Main lesson for AutoAgent |
| --- | --- | --- | --- | --- |
| Braintrust | AI eval + observability | High | unified production-to-eval workflow | stabilize traces, evals, and monitors first |
| LangSmith | tracing + eval + prompt + runtime | High | cohesive developer workflow | connect prompts, evals, and deployment into one flow |
| Arize Phoenix | open-source observability | High | open standards and instrumentation trust | package OSS/developer truth cleanly |
| Humanloop | prompt/eval platform, now sunset | Low today | clean prompt and environment management | clarity and packaging matter as much as features |
| W&B Weave | GenAI observability inside MLOps stack | Medium-high | trace trees, scorers, lineage | make trace + scorer UX much stronger |
| Patronus AI | eval + security + supervision | Medium | failure-mode taxonomy and guardrails | sharpen safety and supervision story |
| Sierra | enterprise customer-service AI | Medium | executive polish and outcome-based pricing | package business value, not just platform power |
| Observe.AI | contact-center AI ops | Medium | QA, coaching, and enterprise focus | solve one buyer problem end-to-end |
| Parloa | AI agent platform for contact centers | Low | lifecycle packaging for CX teams | make pre-go-live testing and lifecycle explicit |
| Vertex AI Agent Builder | hyperscaler platform context | High | scale, governance, ecosystem | position as complementary control layer over Google infra |

## Part 3. Prioritized Backlog

Prioritization logic:
- P0 removes trust-destroying gaps, broken surfaces, and product truth issues.
- P1 brings the platform up to competitive minimum and unlocks repeatable team usage.
- P2 deepens differentiation once the foundation is trustworthy.

### Core Platform Gaps

### [P0] Normalize API envelope conventions across the product
**Category:** Core Platform
**Effort:** M
**Impact:** 10
**Competitors who have this:** Braintrust, LangSmith, W&B Weave, Arize Phoenix
**Description:** Standardize request and response shapes so pages stop breaking on wrapped vs. unwrapped payload assumptions. This is the single highest leverage reliability fix across the product.
**Acceptance criteria:**
- All page/API contracts use one documented envelope pattern.
- Contract tests cover every page route that performs API reads or writes.

### [P0] Fix Context Workbench end-to-end
**Category:** Core Platform
**Effort:** M
**Impact:** 9
**Competitors who have this:** LangSmith, Braintrust, Arize Phoenix
**Description:** The current Context Workbench route crashes. This needs to become a credible context-debugging surface because it is central to AI platform trust.
**Acceptance criteria:**
- `/context` renders without React errors on first load.
- Report and simulation actions work against the backend contract and show useful states.

### [P0] Fix Registry page contract and diff experience
**Category:** Core Platform
**Effort:** M
**Impact:** 9
**Competitors who have this:** Humanloop, LangSmith, Braintrust
**Description:** Registry should be the product's system of record for tools, skills, policies, and handoffs. Today the page crashes because the UI expects different shapes than the API returns.
**Acceptance criteria:**
- `/registry` loads list, detail, and diff flows successfully.
- Version diffs are human-readable and consistent across registry types.

### [P0] Fix Blame Map data contract and visualization
**Category:** Core Platform
**Effort:** S
**Impact:** 8
**Competitors who have this:** Braintrust, W&B Weave, Arize Phoenix
**Description:** The Blame Map should be a signature diagnosis surface. Right now the route crashes because the UI expects a raw array instead of the backend cluster envelope.
**Acceptance criteria:**
- `/blame` loads cluster data correctly from `/api/traces/blame`.
- Users can understand trend, severity, and owners without opening developer tools.

### [P0] Fix Scorer Studio create, refine, and test flows
**Category:** Core Platform
**Effort:** M
**Impact:** 9
**Competitors who have this:** W&B Weave, Braintrust, LangSmith
**Description:** Scorer Studio is strategically important for an eval-first platform, but the page is broken by request and response drift. It must support real scorer creation and testing.
**Acceptance criteria:**
- `/scorer-studio` renders and successfully creates, refines, and tests scorers.
- UI field names match backend expectations for `description` and `eval_result`.

### [P0] Fix Reward Studio list, detail, and test flows
**Category:** Core Platform
**Effort:** M
**Impact:** 9
**Competitors who have this:** Braintrust, W&B Weave, Patronus AI
**Description:** Reward design is core to the long-term platform story. The current route crashes because the UI expects raw payloads while the backend returns envelopes.
**Acceptance criteria:**
- `/reward-studio` loads rewards and hard gates without runtime errors.
- Create and test flows read and write the backend contract correctly.

### [P0] Fix Preference Inbox data model and moderation workflow
**Category:** Core Platform
**Effort:** M
**Impact:** 8
**Competitors who have this:** LangSmith, Braintrust, Humanloop
**Description:** Preference collection is a core path toward RL and human feedback loops. The page must correctly consume pair listings, creation responses, and moderation actions.
**Acceptance criteria:**
- `/preference-inbox` renders existing pairs and accepts new submissions.
- Approve and reject actions update visible queue state without manual refresh hacks.

### [P0] Fix Policy Candidates training and promotion flows
**Category:** Core Platform
**Effort:** L
**Impact:** 8
**Competitors who have this:** Vertex AI Agent Builder, Sierra, Parloa
**Description:** Policy candidates are part of the product's differentiation story, but the current page breaks on wrapped backend payloads. This needs to become a real policy lifecycle surface.
**Acceptance criteria:**
- `/policy-candidates` loads jobs, policies, and evaluation reports without crashing.
- Train, evaluate, canary, promote, and rollback actions work end-to-end.

### [P0] Fix Change Review endpoint mismatch
**Category:** Core Platform
**Effort:** S
**Impact:** 8
**Competitors who have this:** Braintrust, LangSmith, Sierra
**Description:** Change Review renders but emits 404s. This is especially dangerous because it makes the product look almost ready while hiding broken review mechanics.
**Acceptance criteria:**
- `/changes` no longer issues 404s on initial load.
- Export, apply, reject, and hunk-level review actions all hit valid endpoints.

### [P0] Replace mock Assistant orchestration with a persisted service
**Category:** Core Platform
**Effort:** L
**Impact:** 10
**Competitors who have this:** LangSmith, Braintrust, Sierra
**Description:** The Assistant should not rely on in-memory sessions and `MockOrchestrator`. It needs real persistence, tool routing, and session recall so it stops acting like a demo layer.
**Acceptance criteria:**
- Assistant history survives refreshes and server restarts.
- Message handling uses a real orchestrator path with observable actions and artifacts.

### [P0] Replace simulated Live Optimize events with real optimizer telemetry
**Category:** Core Platform
**Effort:** M
**Impact:** 8
**Competitors who have this:** Braintrust, LangSmith, W&B Weave
**Description:** The Live Optimize page is a great narrative surface, but it currently streams simulated events. It should be fed by real optimization job state and eval outcomes.
**Acceptance criteria:**
- `/live-optimize` streams actual optimization job progress, not fabricated cycle payloads.
- Users can jump from a live event to the corresponding attempt, experiment, or release object.

### [P0] Unify AutoFix and QuickFix into one real constrained mutation pipeline
**Category:** Core Platform
**Effort:** L
**Impact:** 9
**Competitors who have this:** Braintrust, Sierra, Patronus AI
**Description:** The repo has overlapping fix-generation ideas. Consolidate them into one reviewable proposal system with typed constraints, eval checks, and rollout controls.
**Acceptance criteria:**
- One canonical proposal-generation backend powers all fix suggestion UX.
- Every suggested change carries risk, rationale, evaluation evidence, and next action.

### [P0] Productize shell pages that already have backend support
**Category:** Core Platform
**Effort:** L
**Impact:** 9
**Competitors who have this:** LangSmith, Braintrust, Sierra
**Description:** Knowledge, Reviews, Sandbox, and What-If should either become real product surfaces or leave the nav until ready. The repo already has enough backend groundwork to ship useful v1s.
**Acceptance criteria:**
- Each current shell route is either fully implemented or removed from default nav.
- Implemented routes expose at least one real, repeatable workflow with seeded demo data.

### [P0] Align startup flow, root route, and docs
**Category:** Core Platform
**Effort:** M
**Impact:** 8
**Competitors who have this:** All
**Description:** The README, `start.sh`, and route behavior disagree on where users land and what they should see first. This needs one truthful first-run path.
**Acceptance criteria:**
- README, beginner guide, and app root route all describe the same first-run journey.
- `./start.sh` opens the intended landing experience consistently.

### Competitive Must-Haves

### [P1] Add online evaluation monitors and alerts
**Category:** Competitive
**Effort:** L
**Impact:** 9
**Competitors who have this:** LangSmith, Arize AX, Braintrust, W&B Weave
**Description:** AutoAgent needs a clear production-quality monitoring layer for live traffic, thresholds, regressions, and drift. Today that story is fragmented across traces, events, and dashboards.
**Acceptance criteria:**
- Users can define monitor rules on live quality, safety, latency, and cost metrics.
- Alerts can route to email, Slack, or webhook subscriptions with actionable payloads.

### [P1] Add annotation queues for human feedback
**Category:** Competitive
**Effort:** M
**Impact:** 8
**Competitors who have this:** LangSmith, Braintrust, Humanloop
**Description:** Human review needs a first-class queue, not scattered review affordances. This is foundational for scoring, preference data, and enterprise review workflows.
**Acceptance criteria:**
- Users can create, assign, and complete annotation tasks from traces, evals, and conversations.
- Queue results feed directly into scorers, preferences, or calibration views.

### [P1] Ship a prompt playground with versioning and compare mode
**Category:** Competitive
**Effort:** L
**Impact:** 8
**Competitors who have this:** LangSmith, Arize Phoenix, Braintrust, W&B Weave
**Description:** AutoAgent needs a place to safely test prompt edits, compare outputs, and promote changes into versioned artifacts.
**Acceptance criteria:**
- Users can run side-by-side prompt variants against the same inputs.
- Successful prompt iterations can be committed into versioned configs or registry objects.

### [P1] Build a dataset manager and experiment comparison workspace
**Category:** Competitive
**Effort:** M
**Impact:** 8
**Competitors who have this:** LangSmith, Braintrust, Arize Phoenix, W&B Weave
**Description:** Evals need stronger dataset lifecycle management and experiment comparison. Right now the product has pieces of this, but not a coherent workspace.
**Acceptance criteria:**
- Users can create, import, filter, and reuse datasets from UI and CLI.
- Experiment comparison supports metrics, filters, and exportable summaries.

### [P1] Add saved trace views, topics, and query filters
**Category:** Competitive
**Effort:** M
**Impact:** 7
**Competitors who have this:** Braintrust, W&B Weave, Arize Phoenix
**Description:** Traces are useful today, but the workflow is still too raw. Saved views and topic clustering would make observability much more powerful for repeated operations.
**Acceptance criteria:**
- Users can save trace filters by agent path, error type, tool, score range, or account segment.
- Topic clustering summarizes recurring failure families over time.

### [P1] Add experiment leaderboards and release comparisons
**Category:** Competitive
**Effort:** M
**Impact:** 7
**Competitors who have this:** Braintrust, LangSmith, W&B Weave
**Description:** Teams need a way to compare variants, not just inspect one run at a time. This is essential for making optimization outcomes legible to both engineers and leadership.
**Acceptance criteria:**
- Users can compare experiments and releases side-by-side on quality, safety, latency, and cost.
- Leaderboards can be filtered by dataset, time window, environment, and owner.

### Differentiation Features

### [P1] Build an artifact lineage graph from conversation to release
**Category:** Competitive
**Effort:** L
**Impact:** 9
**Competitors who have this:** W&B Weave, LangSmith, Vertex AI Agent Builder
**Description:** AutoAgent's biggest differentiated opportunity is showing how a production issue becomes a plan, proposal, artifact, eval bundle, approval, and release. No current route tells that story cleanly enough.
**Acceptance criteria:**
- Users can open any release and trace its lineage back to conversations, traces, evals, and approvals.
- The lineage graph is visible in both Builder and release-oriented surfaces.

### [P1] Turn Google-native migration into a first-class hub
**Category:** Competitive
**Effort:** L
**Impact:** 9
**Competitors who have this:** Vertex AI Agent Builder, Sierra, Parloa
**Description:** AutoAgent should lean into CX, ADK, A2A, and Vertex rather than treating them as side tabs. This is the strongest strategic wedge available.
**Acceptance criteria:**
- One hub coordinates CX import, ADK import, deployment targets, snapshots, and rollback status.
- The product clearly explains when AutoAgent complements Vertex vs. when it hands off to Vertex.

### [P1] Add outcome-linked optimization scorecards
**Category:** Competitive
**Effort:** M
**Impact:** 8
**Competitors who have this:** Sierra, Observe.AI, Parloa
**Description:** The platform should connect technical metrics to business outcomes like containment, deflection, resolution, escalations, revenue, or churn risk.
**Acceptance criteria:**
- Users can define north-star business outcomes and map lower-level metrics to them.
- Dashboards show whether recent optimizations improved both technical and business KPIs.

### [P1] Package approval-aware release bundles as a signature workflow
**Category:** Competitive
**Effort:** M
**Impact:** 8
**Competitors who have this:** Sierra, Vertex AI Agent Builder, LangSmith
**Description:** The Builder already has release-adjacent objects. Turn them into a polished workflow with release candidates, manifests, rollback plans, and approver signoff.
**Acceptance criteria:**
- Releases bundle artifacts, eval evidence, approvals, owners, and rollback instructions in one object.
- Approvers can review and sign off without needing to visit multiple pages.

### [P2] Add multi-agent topology analysis and A2A optimization
**Category:** Competitive
**Effort:** XL
**Impact:** 8
**Competitors who have this:** Vertex AI Agent Builder, Sierra, Parloa
**Description:** AutoAgent can become uniquely strong if it optimizes not just one prompt or one agent, but multi-agent systems connected through A2A and tool chains.
**Acceptance criteria:**
- Users can visualize agent handoffs, bottlenecks, and failure propagation across a topology.
- Optimization recommendations can target routing, delegation, and tool boundaries, not just single-agent prompt edits.

### Developer Experience

### [P1] Publish stable API contracts and generate typed clients
**Category:** Developer Experience
**Effort:** M
**Impact:** 9
**Competitors who have this:** LangSmith, Arize Phoenix, Vertex AI Agent Builder
**Description:** Contract drift is hurting both product reliability and developer trust. Stable APIs and generated clients reduce the chance of this recurring.
**Acceptance criteria:**
- OpenAPI is complete and accurate for all public routes.
- Front-end and SDK consumers use generated typed clients instead of ad hoc fetch wrappers.

### [P1] Ship Python and TypeScript SDKs with end-to-end examples
**Category:** Developer Experience
**Effort:** L
**Impact:** 8
**Competitors who have this:** LangSmith, Arize Phoenix, Braintrust, Patronus AI
**Description:** The platform needs a supported way for users to instrument agents, log traces, run evals, and ingest outcomes without reading server internals.
**Acceptance criteria:**
- Python and TypeScript SDKs cover tracing, evals, datasets, and outcomes ingestion.
- The repo includes working sample apps for at least one chat agent and one CX workflow.

### [P1] Add deep links between CLI outputs and web UI objects
**Category:** Developer Experience
**Effort:** S
**Impact:** 7
**Competitors who have this:** Braintrust, LangSmith, W&B Weave
**Description:** The CLI is powerful, but it feels disconnected from the UI. Every major CLI action should point users to the relevant trace, experiment, release, or Builder object.
**Acceptance criteria:**
- Major CLI commands print links to the corresponding web object when the server is running.
- UI pages show the originating CLI command or automation source when relevant.

### [P2] Build a local replay and sandbox kit for debugging
**Category:** Developer Experience
**Effort:** M
**Impact:** 7
**Competitors who have this:** Arize Phoenix, Braintrust, W&B Weave
**Description:** Developers should be able to replay traces locally, attach scorers, and compare variants without re-wiring production services.
**Acceptance criteria:**
- Local replay can run a saved trace against a chosen config or prompt variant.
- Sandbox runs can produce reproducible artifacts and evaluation outputs.

### Enterprise Readiness

### [P0] Add auth, SSO, RBAC, and multi-workspace tenancy
**Category:** Core Platform
**Effort:** XL
**Impact:** 10
**Competitors who have this:** LangSmith, Braintrust, W&B Weave, Vertex AI Agent Builder
**Description:** This is the single biggest enterprise blocker. Platform buyers will not take the product seriously without authentication, workspace boundaries, and role-based access.
**Acceptance criteria:**
- All product access is gated by authentication and workspace membership.
- SSO and role-based permissions control access to traces, configs, approvals, releases, and admin actions.

### [P1] Add immutable audit logs and approval ledger views
**Category:** Core Platform
**Effort:** M
**Impact:** 8
**Competitors who have this:** W&B Weave, Braintrust, Vertex AI Agent Builder
**Description:** Event logs exist, but they are not yet positioned or structured as a true audit system. Promote this into a governed ledger for approvals, overrides, deployments, and rollbacks.
**Acceptance criteria:**
- Every privileged action is captured with actor, timestamp, object, before/after state, and justification.
- Users can filter, export, and investigate approval history from a dedicated view.

### [P1] Add data governance, redaction, and retention controls
**Category:** Core Platform
**Effort:** L
**Impact:** 8
**Competitors who have this:** Braintrust, W&B Weave, Observe.AI, Vertex AI Agent Builder
**Description:** The product handles traces, conversations, and user content. Customers need retention policies, PII redaction, workspace-level masking, and export controls.
**Acceptance criteria:**
- Workspaces can define retention windows and redaction policies for conversations and traces.
- Sensitive fields are masked in UI, exports, and notifications according to policy.

### [P1] Add admin console and SCIM-style user lifecycle management
**Category:** Core Platform
**Effort:** L
**Impact:** 7
**Competitors who have this:** Observe.AI, W&B Weave, Vertex AI Agent Builder
**Description:** Platform teams need a simple admin layer for onboarding, deprovisioning, workspace controls, API keys, and billing-like governance.
**Acceptance criteria:**
- Admin users can manage members, roles, service accounts, and workspace defaults from UI.
- User lifecycle events are auditable and support automated provisioning flows.

### Integration Ecosystem

### [P1] Expand CRM and CCaaS connectors
**Category:** Integration
**Effort:** XL
**Impact:** 9
**Competitors who have this:** Sierra, Observe.AI, Parloa, Vertex AI Agent Builder
**Description:** AutoAgent should move beyond CX and ADK into the real systems customers already use: Zendesk, Salesforce, Intercom, Genesys, Five9, and related stacks.
**Acceptance criteria:**
- At least three major production connectors support import, sync, and outcome ingestion flows.
- Connected systems can be used as trace sources and deployment targets where applicable.

### [P2] Add warehouse and BI export paths
**Category:** Integration
**Effort:** M
**Impact:** 7
**Competitors who have this:** Observe.AI, W&B Weave, Vertex AI Agent Builder
**Description:** Enterprises want AI quality data in their existing analytics stack. AutoAgent should export traces, evals, and business outcomes to BigQuery and common warehouses.
**Acceptance criteria:**
- Users can schedule exports to BigQuery and at least one non-Google warehouse.
- Export schemas are documented, versioned, and stable enough for BI dashboards.

### [P2] Launch a marketplace for skills, scorers, connectors, and policies
**Category:** Integration
**Effort:** L
**Impact:** 7
**Competitors who have this:** LangSmith, Vertex AI Agent Builder, Parloa
**Description:** The repo already hints at marketplace concepts. A curated ecosystem would amplify the Builder and Skills story materially.
**Acceptance criteria:**
- Users can browse, install, version, and review marketplace assets from one surface.
- Marketplace assets declare compatibility, permissions, and provenance.

### UX Polish

### [P0] Add a guided onboarding and demo mode selector
**Category:** UX
**Effort:** M
**Impact:** 9
**Competitors who have this:** Sierra, Observe.AI, Parloa
**Description:** New users should choose between Builder Demo, VP Demo, and Product Exploration instead of being dropped cold into the densest route in the product.
**Acceptance criteria:**
- First-run users see a chooser with clear paths for demo, builder, and operational exploration.
- Each path loads relevant seeded data and context-sensitive tips.

### [P0] Remove or feature-flag unfinished nav items and add recovery states
**Category:** UX
**Effort:** S
**Impact:** 9
**Competitors who have this:** All mature competitors
**Description:** Broken and shell pages should not be one click away in the main nav. When pages do fail, users need graceful recovery instead of blank white screens.
**Acceptance criteria:**
- Shell or beta routes are hidden behind flags or clearly labeled.
- Route-level error boundaries provide recovery guidance and issue identifiers.

### [P1] Fix layout, chart responsiveness, and high-value route polish
**Category:** UX
**Effort:** M
**Impact:** 8
**Competitors who have this:** Sierra, LangSmith, Braintrust
**Description:** The MockModeBanner layout bug and chart sizing warnings are visible polish failures on important routes. Fixing them will have an outsized impact on perceived quality.
**Acceptance criteria:**
- Mock mode messaging does not consume horizontal layout space.
- Dashboard and Optimize charts render cleanly across desktop and laptop breakpoints.

### Documentation

### [P0] Rewrite README and start docs to match the actual product
**Category:** Developer Experience
**Effort:** S
**Impact:** 8
**Competitors who have this:** All
**Description:** The docs currently oversell dashboard-first onboarding and under-explain what is mock, beta, or Builder-first. Truthful docs are a product feature.
**Acceptance criteria:**
- README, beginner guide, and platform overview clearly label mock-mode, beta, and production-ready surfaces.
- First-run instructions match the actual root route and recommended demo path.

### [P1] Add persona-based tutorials and a 15-minute executive demo script
**Category:** Developer Experience
**Effort:** M
**Impact:** 7
**Competitors who have this:** Sierra, LangSmith, Vertex AI Agent Builder
**Description:** The product needs purpose-built docs for agent builders, ML engineers, and platform owners, plus a canned demo route that avoids unstable pages.
**Acceptance criteria:**
- Three persona guides exist with sample workflows and expected outcomes.
- A demo script calls out the exact routes to show and which routes to avoid until stabilized.

### Infrastructure

### [P0] Add UI/API contract tests and route smoke tests to CI
**Category:** Core Platform
**Effort:** M
**Impact:** 10
**Competitors who have this:** Braintrust, LangSmith, W&B Weave
**Description:** The current regression pattern is front-end expectations drifting from backend responses. CI must catch this before routes ship broken.
**Acceptance criteria:**
- CI runs typed contract tests for all page-critical APIs.
- Smoke tests verify that every routed page loads without blank-screen React errors.

### [P1] Harden background jobs, SSE streams, and job telemetry
**Category:** Core Platform
**Effort:** L
**Impact:** 8
**Competitors who have this:** LangSmith, Vertex AI Agent Builder, Sierra
**Description:** The platform increasingly depends on background tasks, long-running jobs, and streaming updates. These need stronger status models, retries, and operator visibility.
**Acceptance criteria:**
- Long-running eval, optimize, deploy, and builder tasks expose durable job state and retryable failure modes.
- SSE and background workers emit structured telemetry for operators and tests.

### [P1] Package managed-demo and self-hosted deployment modes explicitly
**Category:** Core Platform
**Effort:** L
**Impact:** 7
**Competitors who have this:** Arize Phoenix, W&B Weave, Vertex AI Agent Builder
**Description:** The product should clearly distinguish between demo mode, local self-host, and enterprise deployment. This reduces confusion and improves buyer confidence.
**Acceptance criteria:**
- The repo and product define supported deployment modes with setup expectations and limitations.
- Environment-specific configuration, health, and storage dependencies are documented and testable.

## Closing recommendation

The next 90 days should optimize for trust, not breadth.

If I were sequencing this as a PM, I would do it in this order:
1. Remove trust-destroying issues: broken pages, shell pages in nav, docs mismatch, layout bug, contract drift.
2. Turn the strongest story into a great one: Builder Workspace, Builder Demo, Intelligence Studio, and Google migration flows.
3. Reach competitive minimum: monitors, annotation queues, prompt playground, datasets, saved trace views.
4. Then invest in differentiation: artifact lineage, approval-aware release bundles, outcome scorecards, and multi-agent optimization.

That sequence gives AutoAgent the best chance to feel real before it tries to feel expansive.
