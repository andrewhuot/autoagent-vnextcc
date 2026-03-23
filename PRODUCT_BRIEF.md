# AutoAgent VNextCC — Product Brief

## Product Vision
An OpenAI-Evals-grade platform for iterating ADK agent quality. Headless-first (CLI + API), with a polished web console for when you need visual insight. Think: what OpenAI would ship if they built an agent optimization tool for Google ADK.

This is a PRODUCT, not a prototype. It should feel approachable, professional, and ready for customer demos at Google Cloud CX Agent Studio.

## Design Philosophy

### OpenAI Evals Model
Research OpenAI's evals platform (https://platform.openai.com/evals, their docs, blog posts) to understand:
- How they structure eval runs, datasets, and scoring
- Their CLI-first workflow (`openai evals create`, `openai evals run`)
- How the web UI complements the CLI (browse results, compare runs, visualize)
- Their API design patterns
- Their documentation style

### Core Principle: Headless-First, UI-When-Needed
- **90% of usage is CLI/API** — create agents, run evals, trigger optimization, deploy configs
- **10% is web console** — compare optimization runs visually, browse conversation logs, view Pareto tradeoffs, share results with stakeholders
- The web console NEVER blocks workflows — everything it shows can also be done via CLI/API

## User Journeys (CUJs)

### CUJ 1: First-Time Setup
**CLI**: `autoagent init --template customer-support` → scaffolds agent config, eval suite, and config
**App**: Onboarding wizard that does the same thing with a form

### CUJ 2: Run Evaluation
**CLI**: `autoagent eval run --config configs/v003.yaml --suite evals/cases/`
**API**: `POST /api/eval/run` with config + suite reference
**App**: Click "New Eval Run" → select config + suite → watch progress → see results

### CUJ 3: Review Eval Results
**CLI**: `autoagent eval results --run-id abc123` (table output)
**API**: `GET /api/eval/runs/{run_id}`
**App**: Results page with score breakdown, per-case pass/fail, comparison to baseline

### CUJ 4: Run Optimization Cycle
**CLI**: `autoagent optimize --cycles 5 --config configs/v003.yaml`
**API**: `POST /api/optimize/run` with config + parameters
**App**: Click "Optimize" → watch cycles in real-time → see accepted/rejected proposals

### CUJ 5: Compare Configs
**CLI**: `autoagent config diff v003 v005`
**API**: `GET /api/config/diff?a=v003&b=v005`
**App**: Side-by-side YAML diff with highlighted changes + score comparison

### CUJ 6: View Agent Health
**CLI**: `autoagent status`
**API**: `GET /api/health`
**App**: Dashboard with health score, metrics, trends, alerts

### CUJ 7: Deploy Config
**CLI**: `autoagent deploy --config v005 --strategy canary`
**API**: `POST /api/deploy` with config version + strategy
**App**: Deploy page with strategy selector, confirmation, live canary metrics

### CUJ 8: Browse Conversation Logs
**CLI**: `autoagent logs --limit 20 --outcome fail`
**API**: `GET /api/conversations?limit=20&outcome=fail`
**App**: Conversation browser with filters, expandable turns, outcome badges

### CUJ 9: Continuous Loop (Overnight Autoresearch)
**CLI**: `autoagent loop --max-cycles 50 --stop-on-plateau`
**API**: `POST /api/loop/start` with parameters
**App**: Loop monitor showing cycle-by-cycle progress, score trajectory chart

### CUJ 10: Share Results with Stakeholders
**App-only**: Generate shareable report link with eval results, optimization history, and recommendations

## Architecture

### Backend (Python, FastAPI)
Existing VNext backend is the foundation. Enhance:

1. **REST API layer** — comprehensive API covering ALL CUJs above
   - `/api/eval/*` — eval management
   - `/api/optimize/*` — optimization runs
   - `/api/config/*` — config versioning + diff
   - `/api/health` — health metrics
   - `/api/conversations` — conversation logs
   - `/api/deploy/*` — deployment management
   - `/api/loop/*` — continuous loop management
   - OpenAPI/Swagger docs auto-generated

2. **WebSocket** — real-time progress for eval runs, optimization cycles, and loop monitoring

3. **Background tasks** — long-running eval/optimize/loop as async background jobs with progress tracking

### Frontend (Next.js or React + Vite)
Pick the simpler option. Key pages:

1. **Dashboard** (`/`) — health score, key metrics, recent activity, quick actions
2. **Eval Runs** (`/evals`) — list of eval runs, create new, view results
3. **Eval Run Detail** (`/evals/:id`) — scores, per-case results, comparison
4. **Optimize** (`/optimize`) — trigger optimization, view history, cycle-by-cycle detail
5. **Configs** (`/configs`) — version list, view YAML, diff two versions
6. **Conversations** (`/conversations`) — filterable log browser with expandable turns
7. **Deploy** (`/deploy`) — current deployment, canary status, version history
8. **Loop Monitor** (`/loop`) — active loop progress, score trajectory, controls (pause/stop)
9. **Settings** (`/settings`) — agent config, eval suite management, API keys

### Design System
- **Clean, minimal, professional** — NOT flashy. Think Linear, Vercel, OpenAI dashboard
- White/light mode default (with dark mode toggle)
- Font: Inter
- Colors: neutral grays, blue for primary actions, green for success, amber for warning, red for errors
- Dense but readable — data-heavy pages should feel like a developer tool
- Monospace for YAML/config/code blocks
- Subtle animations (page transitions, loading states)
- Responsive but desktop-first
- Empty states with helpful CTAs

### CLI (Click/Typer)
Enhance existing runner.py into a full CLI:
```
autoagent init [--template NAME]        # scaffold new project
autoagent eval run [OPTIONS]            # run eval suite
autoagent eval results [--run-id ID]    # view results
autoagent eval list                     # list recent runs
autoagent optimize [--cycles N]         # run optimization
autoagent config list                   # list config versions
autoagent config diff V1 V2             # diff two configs
autoagent config show [VERSION]         # show config YAML
autoagent deploy [--strategy canary|immediate]
autoagent loop [--max-cycles N] [--stop-on-plateau]
autoagent status                        # health dashboard (CLI)
autoagent logs [--limit N] [--outcome fail|success]
autoagent server                        # start API + web console
```

### Documentation
Create comprehensive docs in `docs/` directory:

1. **README.md** — quick overview, install, 5-minute quickstart
2. **docs/getting-started.md** — detailed setup guide
3. **docs/concepts.md** — how AutoAgent works (the loop, configs, evals, optimization)
4. **docs/cli-reference.md** — every CLI command with examples
5. **docs/api-reference.md** — every API endpoint with request/response examples
6. **docs/app-guide.md** — walkthrough of the web console
7. **docs/architecture.md** — technical architecture, data model, extension points
8. **docs/deployment.md** — deploying to Google Cloud (Cloud Run, BigQuery, etc.)
9. **docs/faq.md** — common questions, troubleshooting

Documentation should be written in the style of OpenAI's platform docs — clear, concise, with code examples. Not academic.

## Quality Bar
- All existing tests must still pass
- New API endpoints must have tests
- Frontend must be polished — use Playwright to screenshot and iterate
- CLI must have --help for every command
- API must have OpenAPI docs at /docs
- Documentation must be complete and accurate
- The whole system must work end-to-end: CLI → API → Engine → Results → UI
- Docker-compose must start everything

## Stretch Goal: CX Agent Studio Integration
Design (but don't fully implement) an integration path for Google Cloud CX Agent Studio:
- How would a customer connect their existing CCAI/CX agent?
- What adapter would be needed?
- Document this in `docs/cx-agent-studio.md`

## Process
1. **Plan first** — create PLAN.md with detailed implementation plan
2. **Build API layer** — comprehensive REST API + WebSocket
3. **Build frontend** — page by page, use Playwright to verify each page
4. **Enhance CLI** — full command set
5. **Write docs** — comprehensive documentation
6. **Polish** — iterate on UI with Playwright screenshots, fix rough edges
7. **Test** — ensure everything works end-to-end
