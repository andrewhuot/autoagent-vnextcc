# Live CLI Golden Path Plan — Claude Opus

## Mission
Test the AgentLab CLI end-to-end in LIVE MODE and make the core CLI user journey materially easier to use.

## Scenario
Build and iterate a **Verizon-like phone-company billing support agent** that helps customers understand charges, plans, fees, and common billing confusion.

## Environment
- **Branch:** `feat/live-cli-golden-path-claude-opus`
- **Python:** 3.12.12
- **API Key:** GOOGLE_API_KEY (Gemini) — confirmed present
- **Provider:** google/gemini-2.5-pro — confirmed ready
- **Mode:** LIVE (confirmed via `agentlab doctor`)

## Golden Path Steps

### Phase 1: Setup
1. Create a new workspace: `agentlab new verizon-billing-agent --template customer-support --mode live`
2. Verify workspace: `agentlab doctor` and `agentlab status`

### Phase 2: Build
3. Build agent via workbench: `agentlab workbench build "Build a Verizon-like phone company billing support agent..."`
4. Show candidate: `agentlab workbench show`

### Phase 3: Iterate
5. Iterate on candidate: `agentlab workbench iterate "Add handling for..."`
6. Save candidate: `agentlab workbench save`

### Phase 4: Eval
7. Run eval: `agentlab eval run`
8. Inspect results: `agentlab eval show latest`

### Phase 5: Optimize
9. Run optimization: `agentlab optimize --cycles 1`

### Phase 6: Deploy
10. Deploy: `agentlab deploy --auto-review --yes`

## Success Criteria
- Each step completes without crashing
- Live LLM calls succeed with Gemini
- The full loop produces a materially improved agent config
- Issues are documented, fixed where possible, and verified
