set -euo pipefail
ROOT="/Users/andrew/Desktop/AutoAgent-VNextCC-Codex-P0"
WORK="$ROOT/.tmp/quickstart-guide-1774814336"
CLI="$ROOT/.venv/bin/autoagent"
cd "$WORK"

"$CLI" build "Build a customer support agent that can help with refunds, shipping questions, and product recommendations" --connector Shopify --output-dir build-output >/tmp/qs-build.out
"$CLI" eval run --dataset "$ROOT/docs/samples/sample_evals.jsonl" --split all --output sample-results.json >/tmp/qs-eval-run.out
"$CLI" eval results --file sample-results.json >/tmp/qs-eval-results.out
"$CLI" eval generate --provider mock --agent-name "Quickstart Guide Agent" --output generated-evals.json >/tmp/qs-eval-generate.out

mkdir -p config-demo
cp "$ROOT"/docs/samples/sample_configs/* config-demo/
"$CLI" config list --configs-dir config-demo >/tmp/qs-config-list.out
"$CLI" config show 1 --configs-dir config-demo >/tmp/qs-config-show.out
"$CLI" config diff 1 2 --configs-dir config-demo >/tmp/qs-config-diff.out

"$CLI" context analyze --trace trace_demo_fail_001 >/tmp/qs-context.out
"$CLI" trace grade trace_demo_fail_001 --db .autoagent/traces.db >/tmp/qs-trace-grade.out
"$CLI" trace graph trace_demo_fail_001 --db .autoagent/traces.db >/tmp/qs-trace-graph.out
"$CLI" trace blame --db .autoagent/traces.db --window 24h --top 5 >/tmp/qs-trace-blame.out

"$CLI" scorer create "accurate, safe, respond in under 3 seconds" --name guide_demo_scorer >/tmp/qs-scorer-create.out
"$CLI" scorer list >/tmp/qs-scorer-list.out
"$CLI" scorer show guide_demo_scorer >/tmp/qs-scorer-show.out
"$CLI" scorer refine guide_demo_scorer "also offer helpful follow-up guidance" >/tmp/qs-scorer-refine.out
"$CLI" scorer test guide_demo_scorer --trace trace_demo_pass_001 --db .autoagent/traces.db >/tmp/qs-scorer-test.out

"$CLI" judges list >/tmp/qs-judges-list.out
"$CLI" judges calibrate --sample 2 >/tmp/qs-judges-calibrate.out
"$CLI" judges drift >/tmp/qs-judges-drift.out

"$CLI" review list >/tmp/qs-review-list.out
"$CLI" review show demochg1 >/tmp/qs-review-show.out
"$CLI" review export demochg1 >/tmp/qs-review-export.out
"$CLI" changes list >/tmp/qs-changes-list.out
"$CLI" changes show demochg1 >/tmp/qs-changes-show.out

"$CLI" autofix suggest >/tmp/qs-autofix-suggest.out
AUTOFIX_ID=$(python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('.autoagent/autofix.db')
row = conn.execute("select proposal_id from proposals order by created_at desc limit 1").fetchone()
print(row[0])
conn.close()
PY
)
"$CLI" autofix apply "$AUTOFIX_ID" >/tmp/qs-autofix-apply.out
"$CLI" autofix history --limit 5 >/tmp/qs-autofix-history.out

"$CLI" skill create --kind build --from-file "$ROOT/docs/samples/sample_build_skill.yaml" >/tmp/qs-skill-create-build.out
"$CLI" skill create --kind runtime --from-file "$ROOT/docs/samples/sample_runtime_skill.yaml" >/tmp/qs-skill-create-runtime.out
"$CLI" skill list --json > skill-list.json
BUILD_SKILL_ID=$(python3 - <<'PY'
import json
with open('skill-list.json', 'r', encoding='utf-8') as handle:
    skills = json.load(handle)
for skill in skills:
    if skill['name'] == 'routing_keyword_expansion':
        print(skill['id'])
        break
PY
)
RUNTIME_SKILL_ID=$(python3 - <<'PY'
import json
with open('skill-list.json', 'r', encoding='utf-8') as handle:
    skills = json.load(handle)
for skill in skills:
    if skill['name'] == 'refund_policy_check':
        print(skill['id'])
        break
PY
)
"$CLI" skill show "$BUILD_SKILL_ID" >/tmp/qs-skill-show.out
"$CLI" skill compose "$BUILD_SKILL_ID" "$RUNTIME_SKILL_ID" --name guide_skillset --output guide-skillset.yaml >/tmp/qs-skill-compose.out

"$CLI" registry add skills guide_registry_skill --file "$ROOT/docs/samples/sample_registry_skill.yaml" >/tmp/qs-registry-add-skill.out
"$CLI" registry add policies guide_support_policy --file "$ROOT/docs/samples/sample_policy.yaml" >/tmp/qs-registry-add-policy.out
"$CLI" registry add tools guide_order_lookup --file "$ROOT/docs/samples/sample_tool_contract.yaml" >/tmp/qs-registry-add-tool.out
"$CLI" registry add handoffs guide_support_to_billing --file "$ROOT/docs/samples/sample_handoff_schema.yaml" >/tmp/qs-registry-add-handoff.out
"$CLI" registry list >/tmp/qs-registry-list.out
"$CLI" registry show skills guide_registry_skill >/tmp/qs-registry-show.out
"$CLI" registry import "$ROOT/docs/samples/sample_registry_import.yaml" >/tmp/qs-registry-import.out
"$CLI" registry diff skills guide_registry_skill 1 1 >/tmp/qs-registry-diff.out

"$CLI" runbook create --name guide_runbook --file "$ROOT/docs/samples/sample_runbook.yaml" >/tmp/qs-runbook-create.out
"$CLI" runbook list >/tmp/qs-runbook-list.out
"$CLI" runbook show guide_runbook >/tmp/qs-runbook-show.out
"$CLI" runbook apply guide_runbook >/tmp/qs-runbook-apply.out

"$CLI" memory show >/tmp/qs-memory-show.out
"$CLI" memory add "Prefer concise refund explanations" --section preference >/tmp/qs-memory-add.out

DATASET_ID=$(("$CLI" dataset create guide_dataset --description "Guide dataset" ) | awk '{print $3}')
"$CLI" dataset list >/tmp/qs-dataset-list.out
"$CLI" dataset stats "$DATASET_ID" >/tmp/qs-dataset-stats.out

"$CLI" outcomes import --source csv --file "$ROOT/docs/samples/sample_outcomes.csv" >/tmp/qs-outcomes-import.out
"$CLI" reward create guide_reward --description "Guide reward" >/tmp/qs-reward-create.out
"$CLI" reward list >/tmp/qs-reward-list.out
"$CLI" reward test guide_reward >/tmp/qs-reward-test.out

"$CLI" rl train --mode verifier --backend openai_rft --dataset "$ROOT/docs/samples/sample_verifier_dataset.jsonl" >/tmp/qs-rl-train.out
POLICY_ID=$(python3 - <<'PY'
import sqlite3, json
conn = sqlite3.connect('.autoagent/policy_registry.db')
row = conn.execute("select data from policies order by rowid desc limit 1").fetchone()
if row:
    print(json.loads(row[0])['policy_id'])
conn.close()
PY
)
"$CLI" rl jobs >/tmp/qs-rl-jobs.out
"$CLI" rl eval "$POLICY_ID" >/tmp/qs-rl-eval.out
"$CLI" rl promote "$POLICY_ID" >/tmp/qs-rl-promote.out
"$CLI" rl canary "$POLICY_ID" >/tmp/qs-rl-canary.out
"$CLI" rl rollback "$POLICY_ID" >/tmp/qs-rl-rollback.out
"$CLI" pref collect --input-text "Help with refunds" --chosen "Please share the order number so I can verify eligibility." --rejected "Refund approved." >/tmp/qs-pref-collect.out
"$CLI" pref export --format generic >/tmp/qs-pref-export.out

"$CLI" curriculum generate --limit 3 --prompts-per-cluster 2 >/tmp/qs-curriculum-generate.out
BATCH_ID=$(python3 - <<'PY'
import json
from pathlib import Path
files = sorted(Path('.autoagent/curriculum').glob('*.json'), reverse=True)
if files:
    print(json.loads(files[0].read_text())['batch_id'])
PY
)
"$CLI" curriculum list >/tmp/qs-curriculum-list.out
"$CLI" curriculum apply "$BATCH_ID" >/tmp/qs-curriculum-apply.out

"$CLI" deploy --config-version 1 --strategy immediate >/tmp/qs-deploy.out
"$CLI" loop --max-cycles 1 --delay 0.1 >/tmp/qs-loop.out
"$CLI" status --json >/tmp/qs-status.out
"$CLI" logs --limit 5 >/tmp/qs-logs.out
"$CLI" doctor >/tmp/qs-doctor.out
"$CLI" quickstart --dir quickstart-demo --agent-name 'Guide Quickstart' --no-open >/tmp/qs-quickstart.out
"$CLI" full-auto --yes --cycles 1 --max-loop-cycles 1 >/tmp/qs-full-auto.out
"$CLI" autonomous --scope dev --yes --cycles 1 --max-loop-cycles 1 >/tmp/qs-autonomous.out

printf 'verification completed\n'
