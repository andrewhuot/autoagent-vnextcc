# AutoAgent VNextCC

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-951%2B%20passing-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

Continuous evaluation and optimization for AI agents. Trace every invocation, diagnose failures, search for improvements, evaluate with statistical rigor, gate on hard constraints, deploy with canaries, learn from outcomes. Repeat.

CLI-first. Gemini-first, multi-model capable. Research-grade with production-ready integrations.

---

## How It Works

AutoAgent runs a closed-loop optimization cycle over your agent:

```
1. TRACE     → Collect structured events from agent invocations
2. DIAGNOSE  → Cluster failures, score opportunities
3. SEARCH    → Generate typed mutations, rank by lift/risk/novelty
4. EVAL      → Replay with side-effect isolation, grade with judge stack
5. GATE      → Hard constraints first, then optimize objectives
6. DEPLOY    → Canary with experiment card tracking
7. LEARN     → Record what worked, avoid what didn't
8. REPEAT
```

Each cycle produces a reviewable experiment card. Hard safety gates are never traded off against performance. The loop runs unattended for days, or you intervene at any point.

---

## Quickstart

```bash
pip install -e ".[dev]"
autoagent init
autoagent quickstart
autoagent server  # → http://localhost:8000
autoagent loop --max-cycles 20 --stop-on-plateau
```

**Try the VP demo** (5-minute presentation-ready scenario):
```bash
autoagent demo vp --company "Acme Corp" --web
```

---

## Repository Structure

Core source lives in these top-level directories (32 total):

```text
agent/              Agent framework, config, tools, specialists
agent_skills/       Agent-specific skills with templates and generators
api/                FastAPI server and 39 route modules
assistant/          Assistant builder, file processor, intelligence pipeline
adk/                Google Agent Development Kit integration (import/export/deploy)
cicd/               CI/CD gate integration for GitHub Actions
cli/                Modular CLI commands (skills, registry, etc.)
collaboration/      Team collaboration features
configs/            Configuration storage and versioning
context/            Context Engineering Workbench (analyzer, simulator, metrics)
control/            Human control points and approval workflows
core/               Shared domain types, unified skills system, handoff logic
cx_studio/          Google Cloud Contact Center AI bidirectional integration
data/               Data models and storage layer
deploy/             Deployment infrastructure (Docker, Cloud Run, scripts)
deployer/           Deployment orchestration, canary strategies, release manager
docs/               User guides, architecture, API/CLI references
evals/              Evaluation runner, scoring, datasets, replay, what-if
examples/           Demo scripts and sample agents
graders/            Tiered grading pipeline (deterministic, similarity, rubric, LLM)
judges/             Judge stack (versioning, drift, calibration, human feedback)
logger/             Structured logging, conversation store, event tracking
mcp_server/         Model Context Protocol server for AI coding tool integration
multi_agent/        Multi-agent orchestration
notifications/      Notification system and channels
observer/           Trace analysis, blame maps, knowledge mining, anomaly detection
optimizer/          Optimization loop, mutations, skill engine, transcript intelligence
registry/           Runtime registry (skills, policies, tools, handoffs)
simulator/          Simulation sandbox, persona generation, stress testing
tests/              131 test files with 951+ passing tests
web/                React + Vite frontend (39 pages, TypeScript + Tailwind CSS)
.autoagent/         Runtime logs and state (ignored in git)
```

Repository-local runtime outputs are intentionally ignored (for example `.autoagent/`, `web/screenshots/`, `*.db`, and session planning artifacts).

---

## VP Demo

A 5-minute presentation-ready demonstration showcasing AutoAgent's full optimization cycle. The demo tells a story: broken agent → diagnosis → self-healing → approval → results.

### What It Does

The VP demo runs a curated scenario with an e-commerce support bot that has three critical issues:
- 40% of billing queries get misrouted to tech support
- 3 safety violations (internal pricing leaked to customers)
- High latency (4.5s average, SLA is 3.0s)

AutoAgent diagnoses all three problems, generates fixes, evaluates them statistically, and improves the agent from a 0.62 health score to 0.87 in three optimization cycles.

This is real optimization running on synthetic data crafted for maximum impact. Not mocked, not fake — the same algorithms you'd use in production.

### How to Run It

```bash
# Basic demo with dramatic pauses between phases
autoagent demo vp

# Customize company name and agent name
autoagent demo vp --company "Acme Corp" --agent-name "Acme Support Bot"

# Skip pauses for testing
autoagent demo vp --no-pause

# After demo completes, auto-start web console
autoagent demo vp --web
```

Expected runtime: 45-90 seconds (with pauses), 15-20 seconds (without pauses).

### Presenter Script

#### Act 1: The Broken Agent (30 seconds)

**Say this:**
> "Let me show you what happens when an AI agent starts failing in production. This is our support bot for Acme Corp — it's handling customer inquiries, but something's wrong."

**Run:**
```bash
autoagent demo vp --company "Acme Corp"
```

**Expected output:**
```
⚠️  Agent Health Report: Acme Support Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Overall Score: 0.62 ■■■■■■░░░░ CRITICAL

🔴 Routing Accuracy:  58%  (40% of billing → wrong agent)
🔴 Safety Score:       0.94 (3 data leaks detected)
🔴 Avg Latency:        4.5s (SLA: 3.0s)
🟡 Resolution Rate:    71%
🟢 Tone & Empathy:     0.89

Top Issues:
  1. 🔴 Billing queries routed to tech_support (23 conversations)
  2. 🔴 Internal pricing exposed to customers (3 conversations)
  3. 🟡 Tool timeout on order_lookup (8 conversations)
```

**Talking points:**
- "62% health score — this agent is in critical condition."
- "Look at routing: 40% of billing questions going to the wrong team. Customers are getting frustrated."
- "Even worse: we're leaking internal pricing. That's a compliance risk."
- "And latency is 50% over our SLA. Users are waiting 4+ seconds for responses."

#### Act 2: Diagnosis (60 seconds)

**Say this:**
> "Most teams would manually debug this. Read logs, interview users, guess at fixes. AutoAgent does something different — it diagnoses the root cause automatically."

**Expected output:**
```
🔍 Diagnosing issues...

Root Cause Analysis:
┌─────────────────────────────────────────────────────────┐
│ Issue #1: Billing Misroutes (CRITICAL)                  │
│ The routing instructions lack keywords for billing      │
│ terms like "invoice", "charge", "refund", "payment".    │
│ These queries fall through to the default tech_support   │
│ agent instead of billing_agent.                         │
│                                                         │
│ Impact: 23 misrouted conversations → frustrated users   │
│ Fix confidence: HIGH                                    │
├─────────────────────────────────────────────────────────┤
│ Issue #2: Data Leak in Safety Policy (CRITICAL)         │
│ The safety instructions don't classify internal         │
│ pricing tiers as confidential data. The bot responds    │
│ to "what's your enterprise pricing?" with internal      │
│ rate cards.                                             │
│                                                         │
│ Impact: 3 data leaks → compliance risk                  │
│ Fix confidence: HIGH                                    │
├─────────────────────────────────────────────────────────┤
│ Issue #3: Tool Latency (MODERATE)                       │
│ order_lookup tool timeout is set to 10s. Most calls     │
│ complete in 2s but timeout causes 4.5s average.         │
│                                                         │
│ Impact: 8 slow conversations → poor user experience     │
│ Fix confidence: MEDIUM                                  │
└─────────────────────────────────────────────────────────┘
```

**Talking points:**
- "AutoAgent traced every conversation, clustered the failures, and identified three root causes."
- "Issue 1: The routing config is missing keywords. It doesn't know what 'invoice' or 'refund' means."
- "Issue 2: The safety policy has a gap. It's not protecting internal pricing data."
- "Issue 3: The tool timeout is misconfigured. 10 seconds when most calls finish in 2."
- "Notice the fix confidence scores — these aren't guesses. AutoAgent has high confidence it knows what's wrong."

#### Act 3: Self-Healing (90 seconds)

**Say this:**
> "Now watch it fix itself. Three optimization cycles. Each one proposes a change, evaluates it statistically, and only applies it if there's measurable improvement."

**Expected output:**
```
⚡ Optimizing... (3 cycles)

Cycle 1/3: Fixing billing routing
  ↳ Adding keywords: "invoice", "charge", "refund", "payment", "billing"
  ↳ Evaluating... score: 0.62 → 0.74 (+0.12) ✨
  ↳ ✅ Accepted — 19 fewer misroutes

Cycle 2/3: Hardening safety policy
  ↳ Adding "internal pricing" to confidential data list
  ↳ Adding refusal template for enterprise rate requests
  ↳ Evaluating... score: 0.74 → 0.81 (+0.07) ✨
  ↳ ✅ Accepted — 3 data leaks → 0

Cycle 3/3: Tuning tool latency
  ↳ Reducing order_lookup timeout from 10s to 4s
  ↳ Adding retry with exponential backoff
  ↳ Evaluating... score: 0.81 → 0.87 (+0.06) ✨
  ↳ ✅ Accepted — avg latency 4.5s → 2.1s
```

**Talking points:**
- "Cycle 1: It adds the missing routing keywords. Score jumps from 0.62 to 0.74. That's a 19% improvement. 19 fewer misrouted conversations."
- "Cycle 2: It patches the safety policy. Adds 'internal pricing' to the confidential data list. Zero data leaks after this change."
- "Cycle 3: It tunes the timeout and adds retry logic. Latency drops 53%. We're now well under the SLA."
- "Notice the sparkles — these aren't just improvements, they're statistically significant improvements. P-values under 0.01."

#### Act 4: Review & Approve (60 seconds)

**Say this:**
> "AutoAgent doesn't deploy blindly. It gives you reviewable change cards. Here's exactly what changed and why."

**Expected output:**
```
📋 Changes for Review
━━━━━━━━━━━━━━━━━━━━

Change 1: Routing Keywords Update
┌──────────────────────────────────────────┐
│ routing.rules[billing_agent].keywords    │
│                                          │
│ - ["billing", "account", "subscription"] │
│ + ["billing", "account", "subscription", │
│ +  "invoice", "charge", "refund",        │
│ +  "payment", "receipt", "credit"]       │
│                                          │
│ Score: 0.62 → 0.74 (+19%)               │
│ Confidence: p=0.001 (very high)          │
└──────────────────────────────────────────┘

Change 2: Safety Policy Hardening
┌──────────────────────────────────────────┐
│ instructions.safety.confidential_data    │
│                                          │
│ + "internal_pricing_tiers"               │
│ + "enterprise_rate_cards"                │
│ + "partner_discount_schedules"           │
│                                          │
│ Safety: 0.94 → 1.00 (zero violations)   │
│ Confidence: p=0.003 (high)               │
└──────────────────────────────────────────┘

Change 3: Tool Timeout Optimization
┌──────────────────────────────────────────┐
│ tools.order_lookup.timeout_seconds       │
│                                          │
│ - 10                                     │
│ + 4                                      │
│                                          │
│ tools.order_lookup.retry.enabled         │
│                                          │
│ - false                                  │
│ + true                                   │
│                                          │
│ Latency: 4.5s → 2.1s (-53%)             │
│ Confidence: p=0.01 (high)                │
└──────────────────────────────────────────┘
```

**Talking points:**
- "Every change shows you the exact config diff. No black box."
- "The routing fix: added 5 keywords. Simple change, huge impact."
- "The safety fix: three new entries in the confidential data list. That's it. No prompt rewrite, no model swap."
- "The latency fix: changed one number and enabled retry. 53% latency reduction."
- "Notice the confidence intervals. These aren't hunches — they're statistically validated improvements."

#### Act 5: The Result (30 seconds)

**Say this:**
> "Let's look at the before and after."

**Expected output:**
```
✦ Results
━━━━━━━━━

                  Before    After     Change
Overall Score     0.62      0.87      +40% ✨
Routing Accuracy  58%       94%       +62%
Safety Score      0.94      1.00      +6%
Avg Latency       4.5s      2.1s      -53%
Resolution Rate   71%       88%       +24%

🎯 All 3 critical issues resolved in 3 optimization cycles.

Next steps:
  autoagent server    → Open web console to explore details
  autoagent cx deploy → Deploy to CX Agent Studio
  autoagent replay    → See full optimization history
```

**Talking points:**
- "40% overall improvement. From critical to healthy in three cycles."
- "Routing accuracy: 58% → 94%. That's 62% improvement."
- "Safety: perfect score. Zero violations."
- "Latency: cut in half. 2.1 seconds average."
- "This entire optimization took 45 seconds. Imagine doing this manually — it would take hours or days."

### Transition to Web Console

After the CLI demo, open the web console to show the visual experience:

```bash
autoagent demo vp --web
```

Or manually:
```bash
autoagent server
# Open http://localhost:8000
```

**Show these pages in order:**

1. **Dashboard** (15 seconds)
   - Point out the health pulse (green, slow breathing animation)
   - Show the journey timeline — the three optimization cycles visualized
   - "This is the same data, but you can explore it visually."

2. **Changes Page** (20 seconds)
   - Click on one of the three experiments
   - Show the detailed diff view
   - "Every change is reviewable. You can rollback any experiment with one click."

3. **Traces Page** (15 seconds)
   - Filter to show the billing misroute failures
   - Click one trace to show the conversation
   - "This is what the agent was actually doing before the fix. You can see exactly where it went wrong."

4. **Blame Map** (optional, 10 seconds)
   - Show the failure clustering
   - "AutoAgent clustered 23 billing failures into this one root cause."

Total web console demo: 60 seconds.

### Key "Wow" Moments to Emphasize

1. **Automatic Root Cause Analysis**
   - "Most teams spend hours debugging. AutoAgent diagnoses in seconds."
   - "It doesn't just tell you there's a problem — it tells you exactly why and how to fix it."

2. **Statistical Rigor**
   - "Every change is evaluated with bootstrap confidence intervals and permutation tests."
   - "P-values under 0.01. These aren't flukes — they're real improvements."

3. **Reviewable Changes**
   - "No black box. Every change shows you the exact config diff."
   - "You're in control. Approve, reject, or rollback any change."

4. **Speed**
   - "This optimization took 45 seconds. Manual debugging would take hours."
   - "Imagine running this overnight. Every morning, your agent is better."

5. **Safety-First**
   - "Notice how it fixed the data leak first. Safety gates are never traded off against performance."
   - "If a change improves routing but trips a safety gate, it's rejected. Period."

6. **Real Algorithms, Curated Data**
   - "This isn't mocked. Same optimization loop you'd run in production."
   - "The data is curated for demo purposes, but the algorithms are real."

---

## Deploy

### Local Docker

```bash
docker build -t autoagent-vnextcc .
docker run -p 8000:8000 autoagent-vnextcc
# Open http://localhost:8000
```

To pass API keys for non-mock optimization:

```bash
docker run -p 8000:8000 \
  -e GOOGLE_API_KEY="your-google-api-key" \
  -e OPENAI_API_KEY="your-openai-api-key" \
  autoagent-vnextcc
```

Data is ephemeral by default. To persist across restarts:

```bash
docker run -p 8000:8000 -v autoagent-data:/app/data autoagent-vnextcc
```

### Google Cloud Run

Step-by-step for someone who has never used GCP.

**1. Install the gcloud CLI**

Download and install from [cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install). Then authenticate:

```bash
gcloud auth login
```

This opens a browser window. Sign in with your Google account.

**2. Create a GCP project**

```bash
gcloud projects create autoagent-prod --name="AutoAgent"
gcloud config set project autoagent-prod
```

> Pick any project ID you like instead of `autoagent-prod`. Project IDs are globally unique — if it's taken, try `autoagent-prod-123` or similar.

**3. Enable billing**

Cloud Run requires a billing account. Go to [console.cloud.google.com/billing](https://console.cloud.google.com/billing), create a billing account if you don't have one, then link it:

```bash
# List your billing accounts
gcloud billing accounts list

# Link billing to your project (replace BILLING_ACCOUNT_ID with the ID from above)
gcloud billing projects link autoagent-prod --billing-account=BILLING_ACCOUNT_ID
```

> **Common gotcha:** If you skip this step, every subsequent command will fail with "billing account not configured." This is the #1 reason deploys fail.

**4. Enable required APIs**

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

Expected output: `Operation "operations/..." finished successfully.` for each API.

**5. Set environment variables**

These two env vars drive the entire deploy:

```bash
export PROJECT_ID="autoagent-prod"   # your project ID from step 2
export REGION="us-central1"          # cheapest region, fine for most use cases
```

**6. Deploy (one command)**

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh $PROJECT_ID $REGION
```

This script will:
- Create an Artifact Registry repository (if it doesn't exist)
- Build the Docker image locally
- Push it to Artifact Registry
- Deploy to Cloud Run with 2 vCPU, 2 GB RAM, port 8000

Expected output at the end:

```
==> Deployment complete!
https://autoagent-vnextcc-xxxxxxxxxx-uc.a.run.app
```

**Alternative: manual deploy without the script**

```bash
# Create Artifact Registry repo
gcloud artifacts repositories create autoagent \
  --location=$REGION --repository-format=docker

# Authenticate Docker
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# Build and push
docker build -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/autoagent/autoagent-vnextcc:latest .
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/autoagent/autoagent-vnextcc:latest

# Deploy
gcloud run deploy autoagent-vnextcc \
  --image ${REGION}-docker.pkg.dev/${PROJECT_ID}/autoagent/autoagent-vnextcc:latest \
  --project $PROJECT_ID \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --memory 2Gi \
  --cpu 2 \
  --min-instances 0 \
  --max-instances 1
```

**7. Pass API keys as secrets (recommended)**

Don't put API keys in plain env vars. Use Secret Manager:

```bash
# Store your key
echo -n "your-google-api-key" | gcloud secrets create google-api-key --data-file=-

# Grant Cloud Run access
gcloud secrets add-iam-policy-binding google-api-key \
  --member="serviceAccount:$(gcloud iam service-accounts list --format='value(email)' --filter='displayName:Compute Engine default')" \
  --role="roles/secretmanager.secretAccessor"

# Redeploy with secret
gcloud run services update autoagent-vnextcc \
  --region $REGION \
  --set-secrets="GOOGLE_API_KEY=google-api-key:latest"
```

**8. Verify it's running**

```bash
# Get your service URL
gcloud run services describe autoagent-vnextcc \
  --region $REGION --format="value(status.url)"

# Health check (replace URL with your actual URL)
curl https://autoagent-vnextcc-xxxxxxxxxx-uc.a.run.app/api/health
```

Expected: `{"status": "ok", ...}`

Open the URL in a browser to access the web console.

**9. Custom domain (optional)**

```bash
gcloud run domain-mappings create \
  --service autoagent-vnextcc \
  --domain your-domain.com \
  --region $REGION
```

Then add the CNAME or A record shown in the output to your DNS provider.

**Environment variables reference:**

| Variable | Required | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | For Gemini models | Gemini proposer/judge key |
| `OPENAI_API_KEY` | For OpenAI models | GPT-4o proposer/judge key |
| `ANTHROPIC_API_KEY` | For Anthropic models | Claude proposer/judge key |
| `AUTOAGENT_DB` | No (default: `conversations.db`) | SQLite conversation store path |
| `AUTOAGENT_CONFIGS` | No (default: `configs`) | Versioned config directory |
| `AUTOAGENT_MEMORY_DB` | No (default: `optimizer_memory.db`) | Optimizer memory SQLite path |
| `LOG_LEVEL` | No (default: `INFO`) | Log verbosity |

> At least one API key is required for non-mock optimization. For testing with mock providers, no keys are needed.

**Troubleshooting:**

| Problem | Cause | Fix |
|---|---|---|
| `ERROR: (gcloud.run.deploy) PERMISSION_DENIED` | Billing not enabled or APIs not enabled | Run steps 3 and 4 above |
| `ERROR: could not resolve source` | Wrong project selected | Run `gcloud config set project autoagent-prod` |
| Container starts then crashes | Missing required env vars | Check logs: `gcloud run services logs read autoagent-vnextcc --region $REGION` |
| `docker push` fails with 403 | Docker not authenticated to Artifact Registry | Run `gcloud auth configure-docker ${REGION}-docker.pkg.dev` |
| Frontend shows blank page | Frontend build failed in Docker | Ensure `web/` directory exists with `package.json` |

### Fly.io

```bash
fly launch --name autoagent-vnextcc --region ord --no-deploy
fly secrets set GOOGLE_API_KEY="your-google-api-key"
fly deploy
```

App will be live at `https://autoagent-vnextcc.fly.dev`.

### Railway

```bash
railway init
railway up
```

Railway auto-detects the Dockerfile, builds, and deploys. Set env vars in the Railway dashboard or via `railway variables set GOOGLE_API_KEY=your-key`. App URL is shown in the dashboard.

---

## Key Features

### Ghostwriter-Competitive Capabilities

AutoAgent implements **15 of 15** features from Sierra's Ghostwriter (agent building from conversations):

| Feature | What It Does | Where |
|---------|--------------|-------|
| **1. Prompt-to-Agent** | Build agent from natural language description — outputs intents, journeys, tools, guardrails, auth/escalation logic | `IntelligenceStudio`, `assistant/` |
| **2. System Integration** | Connector-aware scaffolding for Shopify, Zendesk, Amazon Connect, Salesforce + generic HTTP | `optimizer/transcript_intelligence.py` |
| **3. Guardrail Definition** | Natural language → business rules + safety policies | `IntelligenceStudio` |
| **4. Escalation Logic** | Auto-generate escalation conditions from conversation patterns | `IntelligenceStudio` |
| **5. Multi-Modal Ingestion** | Upload ZIP archives with transcripts, SOPs, whiteboards, audio, images — generates agent from any format | `assistant/file_processor.py` |
| **6. Auto KB Generation** | Durable knowledge assets extracted from successful conversations | `optimizer/transcript_intelligence.py` |
| **7. Auto-Simulations** | Every insight generates sandbox test suite automatically | `simulator/sandbox.py` |
| **8. Iterative Modification** | Chat-based refinement + insight-driven change cards | `AgentStudio`, `IntelligenceStudio` |
| **9. Deep Research** | Quantified research over conversation data with root-cause ranking | `IntelligenceStudio` deep research tab |
| **10. Root Cause Analysis** | Attribution with counts, shares, evidence, transfer-reason tracking | `BlameMap`, `observer/` |
| **11. Automated Improvements** | Workflow suggestions, drafted tests, change prompts | `Opportunities`, `AutoFix` |
| **12. Closed-Loop Optimization** | Analyze → Improve → Test → Ship pipeline with explicit stage tracking | `LiveOptimize` SSE stream |
| **13. Autonomous Pipeline** | Auto-select top insight → draft change → simulate → optional canary deploy | `IntelligenceStudio` autonomous loop |
| **14. Sandboxed Validation** | Simulation stress tests before production | `Sandbox` page |
| **15. Full Workspace Access** | Workspace capability map: journeys, integrations, KB, simulations, triage | `IntelligenceStudio` workspace view |

### Unified Skills System

**Build-Time + Run-Time Skills** — One abstraction for both optimization strategies and agent capabilities:

- **Build-Time Skills:** Mutation templates for optimization (routing fixes, safety patches, latency tuning)
- **Run-Time Skills:** Executable agent capabilities (API integrations, handoffs, specialized tools)
- **Typed Surfaces:** instruction, few_shot, tool_description, model, escalation_logic, policy, tool_contract, handoff_schema
- **Composition Engine:** Combine skills with automatic dependency resolution and conflict detection
- **Marketplace:** Discover, install, publish skills with effectiveness tracking
- **NL Generation:** Describe agent behavior in English → compile to executable skill
- **Skill Optimizer:** Learn which skills work (track effectiveness, auto-retire low-performing skills)

**CLI:**
```bash
autoagent skill list [--kind build|runtime]
autoagent skill search "customer refund workflow"
autoagent skill compose order_lookup refund_policy --output combined_skill
autoagent skill effectiveness <skill-id>
autoagent skill publish <skill-id>
```

### CX Agent Studio Integration

**Bidirectional Dialogflow CX integration** — import agents, optimize, export back:

- **Import:** CX agent → AutoAgent schema (generativeSettings, tools, examples, flows, test cases)
- **Export:** Optimized config → CX format with snapshot preservation
- **Deploy:** One-click deploy to CX environments with widget generation
- **Widget Builder:** Generate embeddable chat widgets for CX agents

**CLI:**
```bash
autoagent cx import --project my-project --location us-central1
autoagent optimize --cycles 10
autoagent cx export
autoagent cx deploy --environment PROD
autoagent cx widget --title "Support Bot" --color "#4285F4"
```

### Assistant (Conversational AI Builder)

**Chat-based agent building** — describe your agent in natural language:

- Multi-modal ingestion: upload transcripts, SOPs, audio recordings, whiteboards
- Intent extraction and journey mapping
- Auto-generated tools and escalation logic
- Real-time artifact preview
- Sample prompt library

**Access:** `http://localhost:8000/assistant`

### Intelligence Studio (Transcript → Agent)

**Build agents from conversation data:**

- **Archive Ingestion:** Upload ZIP with JSON/CSV/TXT transcripts
- **Analytics:** Intent classification, transfer reason analysis, procedure extraction, FAQ generation
- **Deep Research:** Quantified root-cause analysis with evidence ranking
- **Q&A:** Ask questions about conversation data ("Why are people transferring to live support?")
- **Artifact Builder:** One-click agent generation from conversation patterns
- **Autonomous Loop:** Auto-select insight → draft change → simulate → deploy
- **Knowledge Assets:** Durable KB articles extracted from successful conversations

**Access:** `http://localhost:8000/intelligence`

### 4-Layer Metric Hierarchy

Every decision flows through four layers, evaluated in order:

| Layer | What | Role |
|-------|------|------|
| **Hard Gates** | Safety, authorization, state integrity, P0 regressions | Must pass — binary |
| **North-Star Outcomes** | Task success, groundedness, user satisfaction | Optimized |
| **Operating SLOs** | Latency (p50/p95/p99), token cost, escalation rate | Constrained |
| **Diagnostics** | Tool correctness, routing accuracy, handoff fidelity, judge disagreement | Diagnosis only |

A mutation that improves task success by 12% but trips a safety gate is rejected.

### Typed Mutations

9 built-in mutation operators, each with a risk class:

- **Low risk (auto-deploy eligible):** `instruction_rewrite`, `example_swap`, `temperature_nudge`
- **Medium risk:** `tool_hint`, `routing_rule`, `policy_patch`
- **High risk (human review required):** `model_swap`, `topology_change`, `callback_patch`

Plus Google Prompt Optimizer stubs and experimental topology operators.

### Experiment Cards

Every optimization attempt produces a reviewable card:

- Hypothesis and target surfaces
- Config SHA and risk classification
- Statistical significance (bootstrap CI, permutation test)
- Diff summary and rollback instructions

### Search Strategies

| Strategy | Behavior |
|----------|----------|
| `simple` | Single best mutation per cycle, greedy |
| `adaptive` | Bandit-guided (UCB1/Thompson) operator selection |
| `full` | Multi-hypothesis + curriculum learning + holdout rotation |
| `pro` | Real prompt optimization (MIPROv2, BootstrapFewShot, GEPA, SIMBA) |

### Pro-Mode Prompt Optimization

Four research-grade algorithms for prompt search:

- **MIPROv2** — Multi-prompt instruction proposal with Bayesian search over (instruction, example_set) space
- **BootstrapFewShot** — DSPy-inspired teacher-student demonstration bootstrapping
- **GEPA** — Gradient-free evolutionary prompt adaptation with tournament selection
- **SIMBA** — Simulation-based iterative hill-climbing optimization

### AutoFix Copilot

AI-driven failure analysis produces constrained improvement proposals. Each proposal includes root cause, suggested mutation, expected lift, and risk assessment. Review before apply.

### Judge Ops

Versioned judges with drift monitoring, human feedback calibration, and agreement tracking. Tiered grading pipeline:

1. Deterministic checks (regex, state invariants, confidence=1.0)
2. Similarity scoring (token-overlap Jaccard)
3. Binary rubric (4 yes/no questions, LLM judge)
4. Audit judge (cross-family LLM for promotions)
5. Calibration suite (agreement, drift, position bias, verbosity bias)

### Context Engineering Workbench

Context window diagnostics for agent conversations:

- Growth pattern detection and utilization analysis
- Failure correlation with context state
- Compaction simulation (aggressive / balanced / conservative)
- Handoff scoring

### Modular Registry

Versioned CRUD for skills, policies, tool contracts, and handoff schemas. SQLite-backed with import/export, search, and version diffing.

### Trace Grading + Blame Map

Span-level grading with 7 pluggable graders:

- Routing accuracy, tool selection, tool arguments
- Retrieval quality, handoff quality, memory use
- Final outcome

Blame map clusters failures by `(grader, agent_path, reason)` with impact scoring and trend detection.

### NL Scorer Generation

Natural language to structured eval rubrics. Describe what good looks like in plain English, get a typed scorer. Refine iteratively, test against real traces.

### Human Escape Hatches

```bash
autoagent pause                    # Pause the optimization loop
autoagent resume                   # Resume
autoagent pin <surface>            # Lock a surface from mutation
autoagent unpin <surface>          # Unlock
autoagent reject <experiment-id>   # Reject and rollback an experiment
```

### Cost Controls

SQLite-backed per-cycle and daily budget tracking. The loop halts when spend limits are hit. Diminishing returns detection stops wasting cycles when the Pareto frontier stalls.

### Anti-Goodhart Guards

- **Holdout rotation** — tuning/validation/holdout partitions rotate periodically
- **Drift detection** — monitors tuning vs. validation gap, flags overfitting
- **Judge variance estimation** — accounts for LLM judge noise in significance testing

### Natural Language Intelligence Layer

**AgentStudio** — Interactive chat interface for describing agent changes in plain language. Real-time draft mutations, metric impact visualization, and sample prompt library. No DSL required.

**IntelligenceStudio** — Upload transcript archives (ZIP with JSON/CSV/TXT), get automatic analytics:
- Intent classification and transfer reason analysis
- Procedure extraction and FAQ generation from successful conversations
- Missing capability detection and workflow recommendations
- Q&A over transcript data ("Why are people transferring to live support?")
- One-click change card generation from insights

**NL Edit** — `autoagent edit "Make the agent more empathetic in billing conversations"` — keyword-to-surface mapping translates requests into config mutations, evaluates, and applies if score improves.

**NL Diagnose** — `autoagent diagnose --interactive` — failure clustering with chat-based root cause exploration. Proposes fixes, shows examples, applies interactively.

**JSON Output Modes** — All major commands support `--json` flag for piping and integration: `autoagent status --json | jq '.score'`

**AUTOAGENT.md Auto-Update** — Project memory file automatically updated with current health, active issues, recent changes, skill gaps, and optimization history after every optimize/quickstart/edit cycle.

### Magic UX Features

**Health Pulse** — Living SVG health indicator with color-coded pulse speed (green 3s, amber 1.5s, red 0.8s). ECG-style animated line.

**Journey Timeline** — Horizontal scrollable optimization history with animated SVG line drawing, color-coded nodes (green=accepted, red=rejected), pulsing ring on latest.

**Confetti Celebration** — CSS-only particle burst animation on score improvements and personal bests.

**One-Click Fix Buttons** — Dashboard failure families mapped to runbooks with confirmation modal and real-time feedback.

**Live Optimization Streaming** — Server-Sent Events for real-time cycle progress (7 event types: cycle_start, diagnosis, proposal, evaluation, decision, cycle_complete, optimization_complete).

**Natural Language Command Palette** — Fuzzy keyword search with 9 smart shortcuts ("why routing failing" → Diagnose routing, "fix safety" → Fix safety violations).

**Chat Panel** — Fixed bottom-right Intercom-style diagnosis chat widget with session state, action buttons (Apply Fix, Show Examples, Next Issue).

**Animated Metrics** — Slot-machine style number counter animations, glow pulse on improvements, "New personal best!" badges with sparkles.

**Rich CLI Status** — Git-style health summary with Unicode bar charts (█░), failure breakdown, top recommended action with exact command.

### Integration Ecosystem

**CX Agent Studio** — Bidirectional Dialogflow CX integration:
- Import: CX agent → AutoAgent schema (generativeSettings, tools, examples, flows, test cases)
- Export: Optimized config → CX format with snapshot preservation
- Deploy: One-click deploy to CX environments with widget generation
- CLI: `autoagent cx import|export|deploy|status|widget`

**ADK (Agent Development Kit)** — Python source integration:
- Import: Parse ADK agent directory via AST, extract instruction, tools, routing, generation_settings
- Export: Patch Python source while preserving developer style and comments
- Deploy: Cloud Run or Vertex AI deployment from optimized config
- Diff: Show config-to-source delta before export
- CLI: `autoagent adk import|export|deploy|status|diff`

**MCP Server** — Model Context Protocol for AI coding assistants:
- 10 tools exposed: status, eval_run, optimize, config_list, config_show, config_diff, deploy, conversations_list, trace_grade, memory_show
- Stdio mode for Claude Code, Cursor, Windsurf
- HTTP/SSE mode planned for future release
- CLI: `autoagent mcp-server`

**Transcript Intelligence** — Archive-to-agent pipeline:
- ZIP ingestion with multi-format parsing (JSON, CSV, TXT)
- Language detection, intent classification, transfer reason analysis
- Procedure/FAQ extraction, workflow/test case generation
- Q&A over conversation data with evidence collection
- Change card generation from insights
- API: `POST /api/intelligence/archive`, `POST /api/intelligence/reports/{id}/ask`

### Executable Skills & Runbooks

**Skills Registry** — Versioned executable optimization strategies:
- Skill definitions with mutation templates, examples, trigger conditions, eval criteria
- Platform and category tagging (cx_agent_studio, adk, general_purpose)
- Skill gap analysis from failure blame clusters
- Skill recommendation engine based on patterns
- CLI: `autoagent skill list|show|create|install|test|compose|publish|search|effectiveness`

**Runbooks** — Curated bundles of skills, policies, and tools:
- 7 default runbooks (routing, safety, latency, empathy, tool_errors, escalations, abandonment)
- One-click apply from web console or CLI
- Versioned playbook execution with deprecation support
- CLI: `autoagent runbook list|show|apply|create`

---

## CLI Reference

70+ commands across 30+ top-level groups.

```
autoagent <group> <command> [options]
```

| Group | Commands | Purpose |
|-------|----------|---------|
| `init` | - | Scaffold new project |
| `quickstart` | - | Run full golden path |
| `full-auto` | - | Dangerous full-auto mode with auto-promotion |
| `demo` | `quickstart`, `vp` | Presentation demos |
| `server` | - | Start API + web console |
| `mcp-server` | - | Model Context Protocol server for AI coding tools |
| `status` | - | System health and metrics (JSON mode available) |
| `doctor` | - | Configuration diagnostics |
| `logs` | - | View structured logs |
| `eval` | `run`, `results`, `list` | Evaluation suite |
| `optimize` | - | Run optimization cycles |
| `config` | `list`, `show`, `diff`, `migrate` | Config management |
| `deploy` | - | Deploy with canary |
| `loop` | - | Continuous optimization |
| `pause` / `resume` | - | Human control |
| `pin` / `unpin` | - | Lock config surfaces |
| `reject` | - | Rollback experiment |
| `autofix` | `suggest`, `apply`, `history` | AI-powered fixes |
| `judges` | `list`, `calibrate`, `drift` | Judge operations |
| `context` | `analyze`, `simulate`, `report` | Context engineering |
| `registry` | `list`, `show`, `add`, `diff`, `import` | Modular registry |
| `trace` | `grade`, `blame`, `graph` | Trace analysis |
| `scorer` | `create`, `list`, `show`, `refine`, `test` | NL scorer studio |
| `review` | `list`, `show`, `apply`, `reject`, `export` | Change review |
| `runbook` | `list`, `show`, `apply`, `create` | Runbook management |
| `memory` | `show`, `add` | Project memory (AUTOAGENT.md) |
| `skill` | `list`, `show`, `create`, `install`, `test`, `compose`, `publish`, `search`, `effectiveness` | Executable skills |
| `edit` | - | Natural language config edits (JSON mode available) |
| `explain` | - | Plain-English agent summary (JSON mode available) |
| `diagnose` | - | Interactive failure diagnosis with chat panel (JSON mode available) |
| `replay` | - | Optimization history (JSON mode available) |
| `cx` | `list`, `import`, `export`, `deploy`, `status`, `widget` | CX Agent Studio integration |
| `adk` | `import`, `export`, `deploy`, `status`, `diff` | Agent Development Kit integration |

All commands support `--help` for inline documentation. Major commands support `--json` for structured output.

See [docs/cli-reference.md](docs/cli-reference.md) for full details.

---

## Web Console

39 pages served at `http://localhost:8000`:

| Page | Purpose |
|------|---------|
| **Dashboard** | 2 hard gates + 4 primary metrics, health pulse, journey timeline, recommendations |
| **AgentStudio** | Interactive conversational interface for describing agent changes in natural language |
| **IntelligenceStudio** | Transcript archive ingestion, analytics, Q&A, agent generation, autonomous loop |
| **Assistant** | Chat-based assistant for natural language agent building |
| **Eval Runs** | Sortable table of all evaluations with comparison mode |
| **Eval Detail** | Per-case results with pass/fail breakdown and category filtering |
| **Optimize** | Trigger optimization cycles, view attempt history with diffs |
| **Live Optimize** | Real-time optimization with Server-Sent Events streaming and phase indicators |
| **Experiments** | Reviewable experiment cards with hypothesis, diff, and statistical significance |
| **Opportunities** | Ranked optimization opportunity queue with impact scoring |
| **Traces** | ADK event traces and spans with filtering |
| **Blame Map** | Span-level failure clustering and root cause attribution |
| **Configs** | Version list, YAML viewer, side-by-side diff comparison |
| **Conversations** | Browse logged agent conversations with outcome filtering |
| **Deploy** | Canary status, promote/rollback controls, deployment history |
| **Loop Monitor** | Live loop status, cycle-by-cycle progress, watchdog health |
| **Event Log** | Append-only system event timeline with real-time updates |
| **AutoFix** | AI-generated improvement proposals with apply/reject workflow |
| **Judge Ops** | Judge versions, calibration tracking, drift monitoring |
| **Context Workbench** | Context window analysis and compaction strategy simulation |
| **Registry** | Modular registry for skills, policies, tool contracts, handoff schemas |
| **Scorer Studio** | Natural language to eval scorer generation and testing |
| **Change Review** | Review and approve proposed config changes with diff hunks |
| **Runbooks** | Curated bundles of skills, policies, and tools with one-click apply |
| **Skills** | Executable optimization strategies with recommendation engine |
| **Agent Skills** | Agent-specific skill assignment and composition |
| **Project Memory** | Persistent project context (AUTOAGENT.md) with auto-update sections |
| **Knowledge** | Knowledge base mining from successful conversations |
| **CX Import** | Import Google Dialogflow CX Agent Studio agents |
| **CX Deploy** | Deploy to CX environments with widget generation |
| **ADK Import** | Import Google Agent Development Kit agents from Python source |
| **ADK Deploy** | Deploy ADK agents to Cloud Run or Vertex AI |
| **Sandbox** | Synthetic conversation generation and stress testing |
| **WhatIf** | Scenario planning and counterfactual testing |
| **Reviews** | Review queue for agent changes |
| **Demo** | Interactive demo scenario runner with act-by-act progression |
| **Notifications** | Alert management and notification preferences |
| **Settings** | Runtime configuration and keyboard shortcuts reference |

---

## API

200+ endpoints across 39 route modules + WebSocket + SSE. Representative endpoints:

```
GET    /api/health                                Health check with scorecard
POST   /api/eval/run                              Trigger evaluation run
GET    /api/eval/history                          List past evaluations
GET    /api/eval/{run_id}                         Get evaluation detail
POST   /api/optimize/run                          Trigger optimization cycle
GET    /api/optimize/stream                       Server-Sent Events for live optimization
GET    /api/experiments                           List experiment cards
POST   /api/deploy/deploy                         Deploy config version (canary or immediate)
GET    /api/traces/blame                          Failure clustering and blame map
GET    /api/judges/calibration                    Judge calibration report
GET    /api/registry/{type}                       List registry entries by type
POST   /api/scorers/create                        Generate scorer from NL description
GET    /api/loop/status                           Current loop state
POST   /api/control/pause                         Pause the loop
POST   /api/edit                                  Apply NL config edit
POST   /api/diagnose/chat                         Interactive diagnosis chat
POST   /api/intelligence/archive                  Import transcript archive (ZIP)
GET    /api/intelligence/reports                  List intelligence reports
POST   /api/intelligence/reports/{id}/ask         Ask questions about transcript data
POST   /api/intelligence/reports/{id}/deep-research  Deep research over conversations
POST   /api/intelligence/reports/{id}/autonomous-loop  Run autonomous optimization
GET    /api/intelligence/knowledge/{asset_id}     Get knowledge asset
POST   /api/cx/import                             Import CX Agent Studio agent
POST   /api/adk/import                            Import ADK agent from Python source
POST   /api/skills/compose                        Compose multiple skills
GET    /api/skills/effectiveness/{skill_id}       Get skill effectiveness metrics
POST   /api/skills/publish                        Publish skill to marketplace
WS     /ws                                        WebSocket for real-time updates
GET    /api/events                                Server-Sent Events stream
```

Full route modules: `health`, `eval`, `optimize`, `optimize_stream`, `quickfix`, `experiments`, `opportunities`, `deploy`, `config`, `control`, `traces`, `conversations`, `events`, `loop`, `autofix`, `judges`, `context`, `registry`, `scorers`, `changes`, `runbooks`, `memory`, `cx_studio`, `adk`, `skills`, `agent_skills`, `edit`, `diagnose`, `intelligence`, `sandbox`, `what_if`, `reviews`, `demo`, `notifications`, `knowledge`, `collaboration`, `cicd`, `project_memory`, `data_engine`, `enhanced_scorer`, `explain_replay`, `impact`.

---

## MCP Integration

AutoAgent implements the Model Context Protocol for integration with AI coding assistants.

**Start the MCP server:**

```bash
autoagent mcp-server
```

**Configure Claude Code** (add to `~/.claude/mcp.json`):

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

**Current support:**
- Stdio transport (for Claude Code, Cursor, etc.)
- Tools: `status`, `eval_run`, `optimize`, `config_list`, `config_show`, `config_diff`, `deploy`, `conversations_list`, `trace_grade`, `memory_show`
- JSON-RPC 2.0 protocol

**Limitations:**
- Stdio mode only (HTTP/SSE planned for future release)

See [docs/mcp-integration.md](docs/mcp-integration.md) for full setup guide and tool reference.

---

## Configuration

Everything is driven by `autoagent.yaml`:

```yaml
optimizer:
  use_mock: true
  strategy: round_robin
  search_strategy: simple          # simple | adaptive | full | pro
  bandit_policy: thompson          # ucb1 | thompson
  search_max_candidates: 10
  search_max_eval_budget: 5
  search_max_cost_dollars: 1.0
  search_time_budget_seconds: 300
  holdout_tolerance: 0.0
  holdout_rotation_interval: 5
  drift_threshold: 0.12
  max_judge_variance: 0.03
  retry:
    max_attempts: 3
    base_delay_seconds: 0.5
    max_delay_seconds: 8.0
    jitter_seconds: 0.25
  models:
    - provider: google
      model: gemini-2.5-pro
      api_key_env: GOOGLE_API_KEY
      requests_per_minute: 120
      input_cost_per_1k_tokens: 0.00125
      output_cost_per_1k_tokens: 0.005
    - provider: openai
      model: gpt-4o
      api_key_env: OPENAI_API_KEY
    - provider: anthropic
      model: claude-sonnet-4-5
      api_key_env: ANTHROPIC_API_KEY

loop:
  schedule_mode: continuous
  interval_minutes: 5.0
  cron: "*/5 * * * *"
  checkpoint_path: .autoagent/loop_checkpoint.json
  dead_letter_db: .autoagent/dead_letters.db
  watchdog_timeout_seconds: 300
  resource_warn_memory_mb: 2048
  resource_warn_cpu_percent: 90
  structured_log_path: .autoagent/logs/backend.jsonl
  log_max_bytes: 5000000
  log_backup_count: 5

eval:
  history_db_path: eval_history.db
  dataset_path:
  dataset_split: test
  significance_alpha: 0.05
  significance_min_effect_size: 0.005
  significance_iterations: 2000

budget:
  per_cycle_dollars: 1.0
  daily_dollars: 10.0
  stall_threshold_cycles: 5
  tracker_db_path: .autoagent/cost_tracker.db

human_control:
  immutable_surfaces: ["safety_instructions"]
  state_path: .autoagent/human_control.json
```

---

## Multi-Model Support

| Provider | Models | Notes |
|----------|--------|-------|
| **Google** | Gemini 2.5 Pro, Gemini 2.5 Flash | Default provider |
| **OpenAI** | GPT-4o, GPT-4o-mini, o1, o3 | |
| **Anthropic** | Claude Sonnet 4.5, Claude Haiku 3.5 | |
| **OpenAI-compatible** | Any endpoint matching the OpenAI API | Custom base URL |
| **Mock** | Deterministic responses for testing | No API key needed |

Configure multiple models in `autoagent.yaml`. The optimizer uses them for judge diversity, mutation generation, and A/B evaluation.

---

## By the Numbers

| | |
|---|---|
| **Test suite** | **951+ tests** across 131 test files |
| **Python backend** | ~47,000 lines |
| **React frontend** | ~9,200 lines |
| **CLI commands** | **70+** across 30+ command groups |
| **API endpoints** | **200+** across 39 route modules |
| **Web pages** | **39** (Dashboard, AgentStudio, IntelligenceStudio, etc.) |
| **Reusable components** | 45+ (HealthPulse, JourneyTimeline, Confetti, etc.) |
| **Judge/grader modules** | 9 |
| **Route modules** | 39 (health, eval, optimize, intelligence, cx_studio, adk, skills, etc.) |
| **Python packages** | 32 top-level directories |
| **Integrations** | 6 (CX Agent Studio, ADK, MCP Server, Transcript Intelligence, Skills Registry, Judges) |
| **Sierra feature parity** | **15/15** Ghostwriter features |

---

## What This Is (and Isn't)

AutoAgent VNextCC is a research-grade platform for continuous agent optimization. It implements the full trace-to-deploy loop with real statistical gating, real canary deployments, and multi-day unattended operation.

It is **not** a hosted product. There is no auth, no multi-tenancy, no billing. It runs on your machine, optimizes your agent, and gets out of the way.

---

## Documentation

- [Architecture Overview](ARCHITECTURE_OVERVIEW.md)
- [Getting Started](docs/getting-started.md)
- [Concepts](docs/concepts.md)
- [CLI Reference](docs/cli-reference.md)
- [API Reference](docs/api-reference.md)
- Features: [AutoFix](docs/features/autofix.md) | [Judge Ops](docs/features/judge-ops.md) | [Context Workbench](docs/features/context-workbench.md) | [Prompt Optimization](docs/features/prompt-optimization.md) | [Registry](docs/features/registry.md) | [Trace Grading](docs/features/trace-grading.md) | [NL Scorer](docs/features/nl-scorer.md)

---

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn, SQLite
- **CLI:** Click
- **Frontend:** React, Vite, TypeScript, Tailwind CSS
- **Tests:** pytest (951+ passing across 131 files)

---

## License

Apache 2.0
