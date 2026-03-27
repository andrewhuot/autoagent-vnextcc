# Ghostwriter Feature Map (Sierra -> AutoAgent VNextCC)

Date: 2026-03-26

This map was built after auditing:
- `assistant/`
- `core/skills/`
- `agent_skills/`
- `observer/`
- `optimizer/`
- `evals/`
- `simulator/`
- `deployer/`
- `context/`
- `cli/`
- `api/`
- `web/src/pages/` (especially `Assistant.tsx`, `AgentStudio.tsx`, `IntelligenceStudio.tsx`)
- `SIERRA_COMPETITIVE_ANALYSIS.md`

## Sierra Feature Coverage

| # | Sierra Feature | AutoAgent Equivalent | Coverage |
|---|---|---|---|
| 1 | Prompt-to-Agent (zero-to-one) | Prompt artifact generation with intents, journeys, tools, guardrails, auth/escalation outputs | **Covered** (`optimizer/transcript_intelligence.py:build_agent_artifact`, `api/routes/intelligence.py:/build`) |
| 2 | System integration via prompt | Connector-aware integration scaffolding templates (Shopify/Zendesk/Amazon Connect/Salesforce + generic HTTP fallback) | **Implemented in this pass** (`optimizer/transcript_intelligence.py:_build_integration_templates`) |
| 3 | Guardrail definition via prompt | Natural-language prompt converted to business rules + guardrails | **Covered** (`optimizer/transcript_intelligence.py:build_agent_artifact`) |
| 4 | Escalation logic via prompt | Escalation conditions generated from prompt and exposed via artifact/API | **Covered** (`optimizer/transcript_intelligence.py:build_agent_artifact`) |
| 5 | Multi-modal ingestion (SOPs, transcripts, whiteboards, audio, plain English) | File processor + archive ingestion across transcript/document/image/audio paths with synthetic conversation generation for non-chat artifacts | **Implemented in this pass** (`assistant/file_processor.py`, `optimizer/transcript_intelligence.py:_parse_archive`, `_synthesize_artifact_conversations`) |
| 6 | Automated KB generation from artifacts | Durable knowledge asset persisted to disk and linked to reports | **Implemented in this pass** (`optimizer/transcript_intelligence.py:_create_knowledge_asset`, `_persist_knowledge_assets`, `/api/intelligence/knowledge/{asset_id}`) |
| 7 | Auto-generated simulations on each change | Apply-insight now auto-generates simulation tests + sandbox validation bundle | **Implemented in this pass** (`optimizer/transcript_intelligence.py:generate_auto_simulation_bundle`, `api/routes/intelligence.py:/reports/{report_id}/apply`) |
| 8 | Iterative modification via prompt | Conversational and insight-driven modification path into change cards | **Covered / improved** (`assistant/`, `optimizer/transcript_intelligence.py:create_change_card_from_insight`) |
| 9 | Deep research over conversations | Quantified deep research endpoint/report with root-cause ranking and evidence | **Implemented in this pass** (`optimizer/transcript_intelligence.py:deep_research`, `api/routes/intelligence.py:/reports/{report_id}/deep-research`) |
| 10 | Root cause analysis with quantified attribution | Insight generation with counts/shares/evidence and transfer-reason attribution | **Covered** (`observer/`, `optimizer/transcript_intelligence.py:_generate_insights`) |
| 11 | Automated improvement suggestions | Workflow suggestions, suggested tests, drafted change prompts, insight recommendations | **Covered** (`observer/`, `optimizer/transcript_intelligence.py`) |
| 12 | Closed-loop optimization (Analyze -> Improve -> Test -> Ship) | Autonomous cycle API outputting explicit pipeline stage statuses | **Implemented in this pass** (`optimizer/transcript_intelligence.py:run_autonomous_cycle`, `api/routes/intelligence.py:/reports/{report_id}/autonomous-loop`) |
| 13 | Autonomous improvement pipeline | Auto-select top insight, draft change card, simulate in sandbox, optional canary deploy path | **Implemented in this pass** (`optimizer/transcript_intelligence.py:run_autonomous_cycle`) |
| 14 | Sandboxed validation before production | Simulation sandbox stress tests and existing deploy/canary guards | **Covered / integrated deeper** (`simulator/sandbox.py`, `optimizer/transcript_intelligence.py:_run_sandbox_validation`, `deployer/`) |
| 15 | Full workspace access for builder | Artifact now exposes workspace capability map (journeys/integrations/simulations/KB/triage) and web surfaces it | **Implemented in this pass** (`optimizer/transcript_intelligence.py:build_agent_artifact`, `web/src/pages/IntelligenceStudio.tsx`) |

## Key New Surfaces Added

- Backend/API:
  - `GET /api/intelligence/knowledge/{asset_id}`
  - `POST /api/intelligence/reports/{report_id}/deep-research`
  - `POST /api/intelligence/reports/{report_id}/autonomous-loop`
  - `POST /api/intelligence/reports/{report_id}/apply` now returns `auto_simulation`

- Web:
  - Intelligence Studio now supports:
    - Deep research action and results
    - Autonomous loop run and pipeline visualization
    - Durable knowledge asset display
    - Auto-generated simulation bundle display
    - Integration template + workspace access rendering for prompt-built artifacts

## Test Coverage Added For Competitive Gaps

- `tests/test_assistant_file_processor.py`
- `tests/test_transcript_intelligence_service.py`
- Expanded coverage in `tests/test_api_transcript_intelligence.py`

