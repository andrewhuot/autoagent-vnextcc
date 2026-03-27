# Ghostwriter Feature Review & Hardening

## Context
We just implemented 7 competitive features matching Sierra's Ghostwriter product. Read these files first:
- `GHOSTWRITER_FEATURE_MAP.md` — what was implemented and where
- `SIERRA_COMPETITIVE_ANALYSIS.md` — full competitive analysis
- `optimizer/transcript_intelligence.py` — core backend (recently expanded significantly)
- `api/routes/intelligence.py` — new API endpoints
- `web/src/pages/IntelligenceStudio.tsx` — frontend for these features
- `cx_studio/` — our CX Agent Studio integration module
- `assistant/` — conversational builder

## Goals

### 1. Quality & Cohesion Audit
Review every new feature for:
- **Correctness**: Does each feature actually work end-to-end? Are there missing error paths, edge cases, or incomplete implementations?
- **Cohesion**: Do these features feel native to AutoAgent or bolted on? Are naming conventions consistent with the rest of the product?
- **Test coverage**: Are the new tests comprehensive? Add tests for any untested paths.
- **API contract consistency**: Do the new endpoints follow the same patterns as existing ones (error handling, response shapes, validation)?
- **Frontend integration**: Is the IntelligenceStudio page getting too bloated? Should any sections be extracted to sub-components?

### 2. CX Agent Studio Integration
This is critical. The new Ghostwriter-competitive features must integrate with CX Agent Studio:

- **System Integration Templates**: When `build_agent_artifact` generates integration templates (Shopify, Zendesk, Amazon Connect, Salesforce), these should also generate CX Agent Studio webhook/tool configurations. Check `cx_studio/` for the existing integration patterns and ensure:
  - Integration templates can be exported as CX Agent Studio tool definitions
  - The `workspace_access` model maps to CX Agent Studio capabilities (playbooks/flows, tools, generators, datastores)
  - Agent artifacts built from prompts can be deployed TO CX Agent Studio via the existing `cx_studio/importer.py` and `cx_studio/deployer.py`

- **Autonomous Loop → CX Deployment**: When the autonomous pipeline reaches "ship" status, it should support deploying changes to CX Agent Studio (not just our internal canary deployer). Wire the `cx_studio/deployer.py` as an optional deployment target.

- **Knowledge Base → CX Datastore**: When we generate durable knowledge assets, they should be exportable as CX Agent Studio datastores. Check if `cx_studio/` has datastore support; if not, add it.

### 3. Feature Completeness Check
Compare against Sierra's capabilities one more time:

- **Prompt-to-Agent**: Does our artifact output include everything needed to actually configure an agent? (intents, entities, flows/playbooks, webhook configs, fulfillment logic)
- **Multi-modal ingestion**: The whiteboard/audio handling uses synthesized pseudo-conversations — is this robust enough? Should we add better parsing?
- **Deep Research**: Sierra's Explorer produces structured analytical reports with percentage attribution. Verify our `deep_research()` output is equally rigorous.
- **Autonomous Loop**: Sierra's assembly line runs continuously. Our `run_autonomous_cycle` is single-shot. Consider adding a `max_cycles` parameter for multi-iteration optimization.
- **Guardrails**: Are generated guardrails actually enforceable, or just strings? Should they map to CX Agent Studio safety settings?

### 4. Implementation Plan
Create a numbered plan of all changes needed, then execute them in order. For each change:
1. Describe what you're changing and why
2. Make the change
3. Write/update tests
4. Verify tests pass

### 5. After All Changes
1. Run full test suite: `cd tests && python -m pytest -x -q`
2. Fix any failures
3. Commit with message: `feat: harden ghostwriter features — CX Studio integration, quality fixes, completeness improvements`
4. Push to master
