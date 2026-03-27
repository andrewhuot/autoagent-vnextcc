# End-to-End Journey Audit (CLI + UI)

## Scope
- Date: 2026-03-27
- Mission: validate and fix the full journey from natural-language agent creation to evaluation, optimization, and CX Agent Studio deployment.

## Prioritized Improvements

### P0 (Implemented)
1. Missing CLI build command
- Added `autoagent build "..."` to generate full artifact coverage including `intents`, `tools`, `guardrails`, `skills`, and `integration_templates`.
- Added handoff file generation:
  - versioned config scaffold in `configs/`
  - generated eval cases in `evals/cases/generated_build.yaml`
  - artifact snapshot in `.autoagent/build_artifact_latest.json`

2. Missing CLI changes namespace
- Added `autoagent changes` group with aliases:
  - `changes list`
  - `changes show <id>`
  - `changes approve <id>`
  - `changes reject <id> [--reason ...]`
  - `changes export <id>`

3. Missing CLI deploy target contract
- Extended `autoagent deploy` with `--target`:
  - `--target autoagent` (existing deploy behavior)
  - `--target cx-studio` (new CX package/export flow)
- Added no-auth package mode for golden path validation:
  - writes `.autoagent/cx_export_vNNN.json`
  - optional preview with `--snapshot`
  - optional push with `--push` and CX credentials/agent metadata

4. Assistant UI/API incompatibility
- Added EventSource-compatible `GET /api/assistant/message` endpoint.
- Added session fallback behavior for:
  - `GET /api/assistant/history`
  - `DELETE /api/assistant/history`
  - `GET /api/assistant/suggestions`
- Added upload compatibility for frontend single-file contract (`file` form field + `url` response) while preserving multi-file support.

5. Autonomous pipeline response compatibility regression
- Restored top-level autonomous-loop response fields expected by current API consumers:
  - `change_card_id`
  - `pass_rate`
  - `ship_status`
- Preserved richer nested structure (`final_cycle`, `all_cycles`, `pipeline`) for newer flows.

### P1 (Implemented)
1. Builder discoverability and naming clarity in UI
- Dashboard now has explicit `Build Agent` CTA.
- Sidebar naming clarified:
  - `Assistant` -> `Assistant Chat`
  - `Agent Studio` -> `Agent Studio Draft`
  - `Intelligence Studio` -> `Build Agent`

2. Confusion reduction across builder surfaces
- Added guidance banners in `Assistant` and `AgentStudio` pointing users to canonical builder (`/intelligence`) for the production journey.

3. Phase-to-phase UI handoff
- Intelligence Studio now includes explicit next-step buttons after artifact generation:
  1. Run Evaluation
  2. Start Optimization
  3. Review Changes
  4. Deploy to CX

4. CX deploy trust flow
- CX Deploy page now supports config + snapshot preview/export before push.
- Shows planned change list and push result for confidence before environment deploy.

5. CX copy consistency
- Updated CX import preview copy to reflect current resource terminology.

## Validation Summary
- Full required suite command passes:
  - `cd tests && PATH="../.venv/bin:$PATH" python -m pytest -x -q`
  - Result: `2506 passed, 20 warnings`.
- CLI golden path command contracts now available and executable:
  - `init` -> `build` -> `eval run` -> `diagnose` -> `loop` -> `deploy --target cx-studio`
- New CLI tests added and passing (`tests/test_cli_commands.py`).
- Existing CLI/CX tests verified passing in this environment.

## Notes
- Frontend TypeScript build has pre-existing repository-level errors unrelated to this change set; journey UI changes were implemented in the relevant pages/components.
