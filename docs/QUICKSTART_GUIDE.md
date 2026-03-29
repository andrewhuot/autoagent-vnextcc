# AutoAgent CLI Quick Start Guide

This guide is a beginner-friendly, copy-pasteable walkthrough of the AutoAgent CLI.
It starts with a safe local demo workspace, then walks through the core command surface:
building, importing, evaluating, tracing, optimizing, AutoFix, skills, registry items,
scoring, config management, deployment, continuous loops, context engineering,
transcript intelligence, and MCP integration.

> **Important**
> - Unless a step says otherwise, commands below were validated locally in this repo.
> - A few commands are live-integration commands that require real Google Cloud credentials.
>   Those are marked **live credentials required** because the repo does not provide an
>   offline mock for them.
> - A few commands are scaffold commands in the current codebase. They do run, but their
>   behavior today is intentionally light-weight. The guide calls those out explicitly.

## Prerequisites & Setup

### 1. Clone the repo and install dependencies

```bash
git clone https://github.com/andrewhuot/autoagent-vnextcc.git
cd autoagent-vnextcc
./setup.sh
./start.sh
```

Expected output:
- `./setup.sh` creates the virtual environment and installs the project.
- `./start.sh` starts the local app stack.

What just happened:
- You cloned AutoAgent, installed the CLI and server dependencies, and started the local services.

Next:
- Export a few helper variables so every later command is short and repeatable.

### 2. Export reusable shell variables

```bash
export AUTOAGENT_REPO="$PWD"
export AUTOAGENT_BIN="$AUTOAGENT_REPO/.venv/bin/autoagent"
export GUIDE_WS="$AUTOAGENT_REPO/.tmp/quickstart-guide-workspace"
```

Expected output:
- No output.

What just happened:
- `AUTOAGENT_BIN` points at the repo-local CLI binary.
- `GUIDE_WS` is a disposable workspace for this guide.

Next:
- Create a clean demo workspace and seed stable sample data.

### 3. Create the demo workspace

```bash
rm -rf "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet init --dir "$GUIDE_WS" --agent-name "Quickstart Guide Agent" --template customer-support
cp "$AUTOAGENT_REPO/docs/samples/mock_autoagent.yaml" "$GUIDE_WS/autoagent.yaml"
cp -R "$AUTOAGENT_REPO/docs/samples/sample_configs" "$GUIDE_WS/config-demo"
python3 "$AUTOAGENT_REPO/docs/samples/seed_demo_state.py" --workspace "$GUIDE_WS" --clean-curriculum
```

Expected output:
- `init` scaffolds `configs/`, `evals/`, `AUTOAGENT.md`, and local data stores.
- `seed_demo_state.py` prints three demo trace IDs, one pending change card, and one pending AutoFix proposal.

What just happened:
- The workspace now has:
  - a safe mock runtime config at `autoagent.yaml`
  - versioned demo configs in `config-demo/`
  - seeded traces for `trace`, `context`, `judges`, and `scorer`
  - a pending review card for `review` / `changes`
  - a pending AutoFix proposal for `autofix`

Next:
- Confirm the CLI can see the workspace state.

### 4. Sanity-check the workspace

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet status --json
"$AUTOAGENT_BIN" --quiet doctor
```

Expected output:
- `status --json` prints a compact machine-readable health summary.
- `doctor` reports local stores, eval cases, and whether mock mode is enabled.

What just happened:
- You verified that AutoAgent can read the workspace and that the guide will run in mock mode unless a chapter says otherwise.

Next:
- Build your first agent from natural language.

## Sample Files Used In This Guide

The guide reuses these checked-in sample files:

| File | Purpose |
|------|---------|
| `docs/samples/sample_agent.yaml` | A sample agent config you can point `eval run` at directly |
| `docs/samples/sample_evals.json` | Sample eval cases in JSON |
| `docs/samples/sample_evals.jsonl` | Sample eval cases in JSONL for dataset-based runs |
| `docs/samples/mock_autoagent.yaml` | A mock-safe runtime config for local CLI walkthroughs |
| `docs/samples/sample_build_skill.yaml` | Build-time skill sample |
| `docs/samples/sample_runtime_skill.yaml` | Run-time skill sample |
| `docs/samples/sample_registry_skill.yaml` | Registry skill sample |
| `docs/samples/sample_policy.yaml` | Registry policy sample |
| `docs/samples/sample_tool_contract.yaml` | Registry tool contract sample |
| `docs/samples/sample_handoff_schema.yaml` | Registry handoff schema sample |
| `docs/samples/sample_runbook.yaml` | Runbook sample |
| `docs/samples/sample_outcomes.csv` | Outcome import sample |
| `docs/samples/sample_preference_dataset.jsonl` | RL preference-training sample |
| `docs/samples/sample_verifier_dataset.jsonl` | Alternate RL/verifier dataset sample |
| `docs/samples/sample_transcripts.json` | Intelligence Studio transcript sample |
| `docs/samples/legacy_autoagent.yaml` | Legacy config sample for `config migrate` |

> **Tip**
> When you see `$AUTOAGENT_REPO/docs/samples/...` in a command, that path already exists in this repo.

## Optional: The Fastest Possible End-to-End Demo

If you want one command before the chapter-by-chapter walkthrough, run:

```bash
"$AUTOAGENT_BIN" --quiet quickstart --agent-name "One Shot Demo" --dir "$AUTOAGENT_REPO/.tmp/quickstart-one-shot" --no-open
```

Expected output:
- AutoAgent initializes a workspace, runs a baseline eval, performs three optimization cycles, and prints a summary.

What just happened:
- `quickstart` is the fastest safe demo path. In the current repo it forces mock mode so the walkthrough works offline.

Next:
- Continue with Chapter 1 for the manual path.

## Chapter 1: Your First Agent (Build)

> **What You Will Learn**
> - How `autoagent build` turns a prompt into a scaffolded agent artifact
> - Where the generated config and build artifact are written
> - How to inspect the generated pieces before you evaluate them

### 1. Build an agent from a prompt

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet build \
  "Build a customer support agent that can help with refunds, shipping questions, and product recommendations" \
  --connector Shopify \
  --output-dir build-output
```

Expected output:
- A new `build-output/` directory with:
  - `.autoagent/build_artifact_latest.json`
  - `configs/v001_built_from_prompt.yaml`
  - `configs/v002_built_from_prompt.yaml`

What just happened:
- AutoAgent converted a natural-language goal into a structured artifact and one or more candidate configs.

Next:
- Inspect the artifact JSON and the generated YAML.

### 2. Inspect the build artifact

```bash
sed -n '1,220p' "$GUIDE_WS/build-output/.autoagent/build_artifact_latest.json"
```

Expected output:
- JSON with keys such as `connectors`, `intents`, `business_rules`, `auth_steps`, `tools`, `guardrails`, and `suggested_tests`.

What just happened:
- You looked at the high-level product intent the builder inferred from your prompt.

Next:
- Inspect the generated config that the runtime will actually use.

### 3. Inspect the generated config

```bash
sed -n '1,220p' "$GUIDE_WS/build-output/configs/v002_built_from_prompt.yaml"
```

Expected output:
- YAML with `routing`, `prompts`, `tools`, `thresholds`, `model`, and `journey_build`.

What just happened:
- You verified how the builder translated the prompt into a concrete config surface.

Next:
- Try the JSON-only variant.

### 4. Build the same prompt as JSON only

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet build \
  "Build a returns and cancellation assistant for an ecommerce store" \
  --connector Shopify \
  --json
```

Expected output:
- A single JSON object printed to stdout instead of a scaffolded output directory.

What just happened:
- `--json` is useful when you want to pipe the artifact into another script or compare builds quickly.

Next:
- Import an existing agent instead of generating one from scratch.

> **Sample prompts you can paste**
>
> ```text
> Build a billing support agent that handles refunds, failed charges, and subscription upgrades.
> Build an order support agent that can track shipments, update addresses, and cancel eligible orders.
> Build a support orchestrator that routes between orders, billing, and product recommendations.
> ```

[What is next: Chapter 2](#chapter-2-import-an-existing-agent)

## Chapter 2: Import an Existing Agent

> **What You Will Learn**
> - How to start from an existing config file
> - How to import a local Google ADK source tree
> - Which CX Agent Studio commands are local-only and which require live credentials

> **Important**
> AutoAgent does **not** have a dedicated `import-config` command for plain YAML.
> The CLI treats a config file as a first-class input to commands like `eval run`,
> or as a versioned config directory for `config list/show/diff`.

### 1. Start from an existing config file

```bash
cp "$AUTOAGENT_REPO/docs/samples/sample_agent.yaml" "$GUIDE_WS/imported_agent.yaml"
sed -n '1,220p' "$GUIDE_WS/imported_agent.yaml"
```

Expected output:
- The sample agent config copied into your workspace and printed to the terminal.

What just happened:
- You prepared an existing config file that later chapters can evaluate directly.

Next:
- Use a versioned config directory so `config` commands can read history.

### 2. Use a versioned config directory

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet config list --configs-dir config-demo
```

Expected output:
- Two versions: `v001` marked active and `v002` marked canary.

What just happened:
- `config-demo/` is a ready-made example of the format `config list/show/diff` expects:
  versioned YAML files plus a manifest.

Next:
- Import a local ADK project.

### 3. Inspect a sample ADK agent

```bash
"$AUTOAGENT_BIN" --quiet adk status "$AUTOAGENT_REPO/tests/fixtures/sample_adk_agent"
```

Expected output:
- The ADK agent name, model, tool count, and sub-agent count.

What just happened:
- `adk status` parses a local ADK source tree without modifying it.

Next:
- Import it into AutoAgent format.

### 4. Import an ADK source tree

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet adk import "$AUTOAGENT_REPO/tests/fixtures/sample_adk_agent" --output adk-import-demo
find "$GUIDE_WS/adk-import-demo" -maxdepth 2 -type f | sort
```

Expected output:
- An imported config such as `support_agent_config.yaml`
- A snapshot directory with the original ADK source files

What just happened:
- AutoAgent created a normalized config plus a source snapshot so later `adk diff` and `adk export` commands have something to compare against.

Next:
- Preview the export path.

### 5. Preview ADK export changes

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet adk diff adk-import-demo/support_agent_config.yaml --snapshot adk-import-demo/support_agent_snapshot
"$AUTOAGENT_BIN" --quiet adk export adk-import-demo/support_agent_config.yaml --snapshot adk-import-demo/support_agent_snapshot --output adk-export-demo --dry-run
```

Expected output:
- `No changes detected.` for the untouched imported config.

What just happened:
- You verified the round-trip path before writing back to source.

Next:
- Look at the CX Agent Studio commands.

### 6. Inspect CX Agent Studio compatibility and generate a widget offline

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet cx compat
"$AUTOAGENT_BIN" --quiet cx widget --project demo-project --agent demo-agent --title "Quickstart Agent" --output cx-widget.html
ls -la "$GUIDE_WS/cx-widget.html"
```

Expected output:
- A compatibility matrix for ADK <-> CX concepts
- A local `cx-widget.html` file

What just happened:
- These two CX commands work entirely offline and are a good first check that the CX integration is installed.

Next:
- Use the live CX commands when you have real GCP credentials.

### 7. Import from CX Agent Studio (**live credentials required**)

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet cx import \
  --project YOUR_GCP_PROJECT \
  --location global \
  --agent YOUR_CX_AGENT_ID \
  --output-dir cx-import-demo \
  --credentials /absolute/path/to/service-account.json
```

Expected output:
- A generated AutoAgent config and a CX snapshot directory.

What just happened:
- This is the supported live import path from Google Cloud CX Agent Studio.

Next:
- Use the companion live commands as needed.

### 8. Other CX commands (**live credentials required**)

```bash
"$AUTOAGENT_BIN" --quiet cx list --project YOUR_GCP_PROJECT --location global --credentials /absolute/path/to/service-account.json
"$AUTOAGENT_BIN" --quiet cx status --project YOUR_GCP_PROJECT --location global --agent YOUR_CX_AGENT_ID --credentials /absolute/path/to/service-account.json
"$AUTOAGENT_BIN" --quiet cx export --project YOUR_GCP_PROJECT --location global --agent YOUR_CX_AGENT_ID --config "$GUIDE_WS/imported_agent.yaml" --snapshot "$GUIDE_WS/cx-import-demo/your_snapshot.json" --credentials /absolute/path/to/service-account.json --dry-run
"$AUTOAGENT_BIN" --quiet cx deploy --project YOUR_GCP_PROJECT --location global --agent YOUR_CX_AGENT_ID --environment production --credentials /absolute/path/to/service-account.json
```

Expected output:
- Agent listing, deployment status, export preview, or a deployment confirmation depending on the command.

What just happened:
- You saw the full CX command surface from the CLI.

Next:
- Run your first evaluation.

[What is next: Chapter 3](#chapter-3-run-your-first-evaluation)

## Chapter 3: Run Your First Evaluation

> **What You Will Learn**
> - How to generate an eval suite
> - How to run evals against a config file or dataset
> - How to read the results and list prior runs

### 1. Generate a synthetic eval suite

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet eval generate --provider mock --agent-name "Quickstart Guide Agent" --output generated-evals.json
sed -n '1,120p' "$GUIDE_WS/generated-evals.json"
```

Expected output:
- A JSON eval suite with generated cases and suggested expectations.

What just happened:
- `eval generate` created a starter eval suite from the current agent context.

Next:
- Run the checked-in sample dataset.

### 2. Run evals against the sample config and sample dataset

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet eval run \
  --config "$AUTOAGENT_REPO/docs/samples/sample_agent.yaml" \
  --dataset "$AUTOAGENT_REPO/docs/samples/sample_evals.jsonl" \
  --split all \
  --output sample-results.json
```

Expected output:
- A results summary and a new `sample-results.json` file.

What just happened:
- You evaluated a concrete config file against a JSONL dataset.

Next:
- Inspect the detailed result file.

### 3. Read the result file

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet eval results --file sample-results.json
```

Expected output:
- Pass count, quality, safety, latency, cost, and composite score
- A short list of failed cases

What just happened:
- `eval results` turned the raw JSON file into a readable score breakdown.

Next:
- List local result files.

### 4. List recent eval runs

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet eval list
```

Expected output:
- Local result files such as `sample-results.json` with timestamps and composite scores.

What just happened:
- `eval list` scans the current directory for local result artifacts. Full central history requires the API server.

Next:
- Compare this to the built-in eval cases in the workspace.

### 5. Run the workspace eval suite

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet eval run --output workspace-results.json
```

Expected output:
- Another results file based on `evals/cases/` in the workspace.

What just happened:
- You exercised the default workspace eval suite instead of an external dataset.

Next:
- Analyze traces and failures.

[What is next: Chapter 4](#chapter-4-analyze-results)

## Chapter 4: Analyze Results

> **What You Will Learn**
> - How to inspect failure clusters and trace structure
> - How to review optimization history and recent logs
> - Which analysis commands are fully implemented today and which are scaffolds

### 1. Inspect the failure blame map

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet trace blame --window 24h --top 3
```

Expected output:
- The top failure clusters with counts, impact, trend, and example trace IDs.

What just happened:
- AutoAgent grouped recent failures into likely root-cause clusters.

Next:
- Grade a single trace.

### 2. Grade one failing trace

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet trace grade trace_demo_fail_001
```

Expected output:
- Span-level grader results such as `tool_selection`, `tool_argument`, `retrieval_quality`, and `final_outcome`.

What just happened:
- You ran the trace grader over one seeded failing trace.

Next:
- Render the same trace as a graph.

### 3. Render a dependency graph for the trace

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet trace graph trace_demo_fail_001
```

Expected output:
- Critical path, bottlenecks, and the full graph JSON.

What just happened:
- You moved from a flat grader report to a span graph that highlights the bottleneck path.

Next:
- See the most recent optimization attempts.

### 4. Show optimization history

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet replay
```

Expected output:
- A git-log-style summary of recent optimization attempts, scores, and descriptions.

What just happened:
- `replay` gives you a compact high-level history before you inspect individual change cards.

Next:
- Inspect conversation logs.

### 5. Show recent logs

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet logs --limit 5
```

Expected output:
- The latest conversation IDs, outcomes, specialists, latencies, and truncated user messages.

What just happened:
- `logs` is the fastest way to skim recent runtime behavior without opening the web console.

Next:
- Optionally try the trace-promotion scaffold.

### 6. Trigger trace promotion (current scaffold behavior)

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet trace promote trace_demo_pass_001
```

Expected output:
- `Promoting trace trace_demo_pass_001 to eval case...`

What just happened:
- In the current repo, `trace promote` is a scaffold command: it acknowledges the promotion request but does not yet materialize an eval case file.

Next:
- Optimize the agent and review changes.

[What is next: Chapter 5](#chapter-5-optimize-your-agent)

## Chapter 5: Optimize Your Agent

> **What You Will Learn**
> - How to run the optimizer
> - How to review a proposed change card
> - How to accept or reject a proposal from the CLI

### 1. Run one optimization cycle

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet optimize --cycles 1
```

Expected output:
- A short optimization plan, one cycle result, and accepted or rejected proposals.

What just happened:
- AutoAgent observed failures, proposed a change, evaluated it, and decided whether to keep it.

Next:
- Reset the deterministic review card so the next commands always have something to inspect.

### 2. Reset the seeded review state

```bash
python3 "$AUTOAGENT_REPO/docs/samples/seed_demo_state.py" --workspace "$GUIDE_WS"
```

Expected output:
- The seed script reprints the trace IDs, the pending change card `demochg1`, and the pending AutoFix proposal `demoaf1`.

What just happened:
- You restored a stable review card so the rest of this chapter is repeatable.

Next:
- List pending cards.

### 3. List pending review cards

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet review list
```

Expected output:
- One pending card with ID `demochg1`.

What just happened:
- `review list` shows the human-review queue generated by optimization or transcript workflows.

Next:
- Open the card.

### 4. Show the full change card

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet review show demochg1
```

Expected output:
- A terminal-rendered change card with:
  - why the change exists
  - the proposed diff
  - before/after metrics
  - confidence, rollout, and rollback details

What just happened:
- You inspected the evidence before making a decision.

Next:
- Export the card as Markdown.

### 5. Export the card

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet review export demochg1 > demochg1.md
sed -n '1,200p' "$GUIDE_WS/demochg1.md"
```

Expected output:
- A Markdown file containing the card.

What just happened:
- You created a shareable artifact for review outside the terminal.

Next:
- Accept the change.

### 6. Apply the change card

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet review apply demochg1
"$AUTOAGENT_BIN" --quiet changes list
```

Expected output:
- `Applied change card demochg1...`
- `No pending change cards.`

What just happened:
- `review apply` accepted the proposal, and `changes list` confirmed the queue is empty.

Next:
- See the alias-based reject flow too.

### 7. Reject the same seeded card with the `changes` alias

```bash
python3 "$AUTOAGENT_REPO/docs/samples/seed_demo_state.py" --workspace "$GUIDE_WS"
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet changes reject demochg1 --reason "Latency tradeoff is too risky for this demo"
"$AUTOAGENT_BIN" --quiet changes list
```

Expected output:
- A rejection confirmation followed by `No pending change cards.`

What just happened:
- `changes` is the alias family for the `review` commands:
  - `changes list`
  - `changes show`
  - `changes approve`
  - `changes reject`
  - `changes export`

Next:
- Use AutoFix proposals.

[What is next: Chapter 6](#chapter-6-autofix)

## Chapter 6: AutoFix

> **What You Will Learn**
> - How to inspect pending AutoFix proposals
> - How to apply a deterministic seeded proposal
> - What the current CLI does and does not persist automatically

### 1. Reset the deterministic AutoFix proposal

```bash
python3 "$AUTOAGENT_REPO/docs/samples/seed_demo_state.py" --workspace "$GUIDE_WS"
```

Expected output:
- The seed script reports `Pending AutoFix proposal: demoaf1`.

What just happened:
- The workspace now contains a stable pending proposal in `.autoagent/autofix.db`.

Next:
- View proposal history.

### 2. Inspect AutoFix history

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet autofix history --limit 5
```

Expected output:
- A table with proposal ID `demoaf1`, mutation `few_shot_edit`, status `pending`, expected lift, and risk.

What just happened:
- `autofix history` is the most reliable way to inspect proposal state.

Next:
- See whether the live suggester has anything new.

### 3. Ask AutoFix to generate suggestions

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet autofix suggest
```

Expected output:
- Either one or more proposals, or `No proposals generated.`

What just happened:
- The suggester is heuristic. In some workspaces it proposes new fixes; in others, there may be nothing new to suggest.

Next:
- Apply the seeded proposal.

### 4. Apply the pending proposal

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet autofix apply demoaf1
"$AUTOAGENT_BIN" --quiet autofix history --limit 5
```

Expected output:
- `Applied: Applied few_shot_edit (proposal demoaf1)`
- The history entry changes from `pending` to `applied`

What just happened:
- The proposal was marked applied and the mutation engine generated a new config in memory.

Next:
- Re-run evals after you materialize the corresponding config change.

> **Warning**
> In the current CLI, `autofix apply` marks the proposal as applied and prints that a new config
> was generated, but it does not write that config to disk for you. Pair it with `edit`,
> `review apply`, or a manual config update before you re-run `eval run`.

[What is next: Chapter 7](#chapter-7-skills--registry)

## Chapter 7: Skills & Registry

> **What You Will Learn**
> - How to create, list, validate, compose, export, and import skills
> - How to create and apply runbooks
> - How to add, list, show, diff, and bulk-import registry items

### 1. Create sample build-time and run-time skills

```bash
cd "$GUIDE_WS"
rm -f .autoagent/skills.db .autoagent/imported-skills.db
"$AUTOAGENT_BIN" --quiet skill create --kind build --from-file "$AUTOAGENT_REPO/docs/samples/sample_build_skill.yaml"
"$AUTOAGENT_BIN" --quiet skill create --kind runtime --from-file "$AUTOAGENT_REPO/docs/samples/sample_runtime_skill.yaml"
"$AUTOAGENT_BIN" --quiet skill list
```

Expected output:
- Two skills:
  - `routing_keyword_expansion` with ID `routing-keyword-expansion`
  - `refund_policy_check` with ID `refund-policy-check`

What just happened:
- You registered both build-time and run-time skills in the local skill store.

Next:
- Inspect and validate them.

### 2. Show and validate the skills

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet skill show routing-keyword-expansion
"$AUTOAGENT_BIN" --quiet skill test routing-keyword-expansion
"$AUTOAGENT_BIN" --quiet skill test refund-policy-check
```

Expected output:
- YAML-like detail for `skill show`
- `Validation passed` for both sample skills

What just happened:
- You verified the schema and portability of the seeded skill examples.

Next:
- Compose them into a skillset.

### 3. Compose a skillset

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet skill compose routing-keyword-expansion refund-policy-check --name "Refund Ops Bundle" --description "Combine routing and runtime guardrails." --output refund_ops_bundle.yaml
ls -la "$GUIDE_WS/refund_ops_bundle.yaml"
```

Expected output:
- A composed YAML file with both skills merged into one skillset.

What just happened:
- `skill compose` created a portable skillset artifact you can review or reuse.

Next:
- Export one skill as `SKILL.md`.

### 4. Export and import `SKILL.md`

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet skill export-md routing-keyword-expansion --output portable-routing.SKILL.md
"$AUTOAGENT_BIN" --quiet skill import-md portable-routing.SKILL.md --db .autoagent/imported-skills.db
ls -la "$GUIDE_WS/portable-routing.SKILL.md" "$GUIDE_WS/.autoagent/imported-skills.db"
```

Expected output:
- A `portable-routing.SKILL.md` file and a second SQLite skill DB populated from it.

What just happened:
- You round-tripped a build skill through the portable `SKILL.md` format.

Next:
- Use the rest of the skill lifecycle commands.

### 5. Other skill lifecycle commands

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet skill search routing --db .autoagent/skills.db
"$AUTOAGENT_BIN" --quiet skill effectiveness routing-keyword-expansion --db .autoagent/skills.db
"$AUTOAGENT_BIN" --quiet skill recommend --db .autoagent/skills.db
"$AUTOAGENT_BIN" --quiet skill review --help
"$AUTOAGENT_BIN" --quiet skill promote --help
"$AUTOAGENT_BIN" --quiet skill archive --help
"$AUTOAGENT_BIN" --quiet skill install --help
"$AUTOAGENT_BIN" --quiet skill publish --help
```

Expected output:
- Search/effectiveness/recommendation output where local state exists
- `--help` output for commands that require marketplace state or draft-review context

What just happened:
- You saw the rest of the skill lifecycle surface without leaving the CLI.

Next:
- Create and apply a runbook.

### 6. Create, list, show, and apply a runbook

```bash
cd "$GUIDE_WS"
rm -f registry.db
"$AUTOAGENT_BIN" --quiet runbook create --name fix-refund-escalation --file "$AUTOAGENT_REPO/docs/samples/sample_runbook.yaml"
"$AUTOAGENT_BIN" --quiet runbook list
"$AUTOAGENT_BIN" --quiet runbook show fix-refund-escalation
"$AUTOAGENT_BIN" --quiet runbook apply fix-refund-escalation
```

Expected output:
- The runbook appears in the registry and can be applied as a bundle.

What just happened:
- A runbook grouped skills, policies, and tools into a reusable package.

Next:
- Work directly with registry items.

### 7. Add and inspect registry items

```bash
cd "$GUIDE_WS"
rm -f registry.db
"$AUTOAGENT_BIN" --quiet registry add skills returns_handling --file "$AUTOAGENT_REPO/docs/samples/sample_registry_skill.yaml"
"$AUTOAGENT_BIN" --quiet registry add skills returns_handling --file "$AUTOAGENT_REPO/docs/samples/sample_registry_skill.yaml"
"$AUTOAGENT_BIN" --quiet registry add policies refund_guardrails --file "$AUTOAGENT_REPO/docs/samples/sample_policy.yaml"
"$AUTOAGENT_BIN" --quiet registry add tools order_lookup --file "$AUTOAGENT_REPO/docs/samples/sample_tool_contract.yaml"
"$AUTOAGENT_BIN" --quiet registry add handoffs support_to_refunds --file "$AUTOAGENT_REPO/docs/samples/sample_handoff_schema.yaml"
"$AUTOAGENT_BIN" --quiet registry list
"$AUTOAGENT_BIN" --quiet registry show skills returns_handling --version 1
"$AUTOAGENT_BIN" --quiet registry show tools order_lookup --version 1
```

Expected output:
- One or more versions of each registry type
- JSON for the selected skill and tool contract

What just happened:
- You populated all four registry types:
  - skills
  - policies
  - tools
  - handoffs

Next:
- Diff and import registry bundles.

### 8. Diff and bulk-import registry items

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet registry diff skills returns_handling 1 2
"$AUTOAGENT_BIN" --quiet registry import "$AUTOAGENT_REPO/docs/samples/sample_registry_import.yaml"
```

Expected output:
- A diff object between v1 and v2
- An import summary with counts by type

What just happened:
- You compared versions and then imported a bundle in one command.

Next:
- Create scorers and inspect judge health.

[What is next: Chapter 8](#chapter-8-scoring--judges)

## Chapter 8: Scoring & Judges

> **What You Will Learn**
> - How to create and refine NL scorers
> - How to test a scorer against a trace
> - How to inspect judge health, calibration, and drift

### 1. Create a scorer from natural language

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet scorer create "The assistant should acknowledge the refund request, avoid unsafe promises, and resolve the task in three turns or fewer." --name refund_quality
```

Expected output:
- A new scorer spec named `refund_quality` with three dimensions.

What just happened:
- AutoAgent compiled a natural-language rubric into a structured scorer spec.

Next:
- List and inspect it.

### 2. List and show scorers

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet scorer list
"$AUTOAGENT_BIN" --quiet scorer show refund_quality
```

Expected output:
- `scorer list` shows available specs and versions
- `scorer show` prints the detailed YAML/JSON structure

What just happened:
- Scorer specs are now persisted under `.autoagent/scorers`.

Next:
- Refine the scorer.

### 3. Refine the scorer

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet scorer refine refund_quality "Also require the response to mention the order number before processing a refund."
```

Expected output:
- `Refined scorer: refund_quality (v2)` and an added dimension.

What just happened:
- Refinement creates a new version of the scorer rather than overwriting the old one in place.

Next:
- Test it on a seeded trace.

### 4. Test the scorer against a trace

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet scorer test refund_quality --trace trace_demo_fail_001
```

Expected output:
- An aggregate score and per-dimension pass/fail breakdown.

What just happened:
- You used a trace as the input object for a rubric-driven scorer.

Next:
- Inspect the judge stack.

### 5. List judges

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet judges list
```

Expected output:
- Active judge IDs, versions, and agreement rates.

What just happened:
- You inspected the current judge surface and its agreement with human feedback.

Next:
- Sample calibration cases.

### 6. Calibrate judges

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet judges calibrate --sample 5
```

Expected output:
- Sample cases showing judge scores, human scores, and gaps.

What just happened:
- `judges calibrate` helps you decide whether the rubric is too lenient or too strict.

Next:
- Check drift.

### 7. Check judge drift

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet judges drift
```

Expected output:
- Either `No drift detected` or a drift warning summary.

What just happened:
- You checked whether the current judge behavior is drifting away from earlier calibration.

Next:
- Manage config versions and natural-language edits.

[What is next: Chapter 9](#chapter-9-config-management)

## Chapter 9: Config Management

> **What You Will Learn**
> - How versioned config directories work
> - How to show, diff, and migrate configs
> - How to use natural-language editing and immutable pins

### 1. List config versions

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet config list --configs-dir config-demo
```

Expected output:
- `v001` as active and `v002` as canary.

What just happened:
- You listed the version history from a manifest-backed config directory.

Next:
- Show one version.

### 2. Show a specific version

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet config show 1 --configs-dir config-demo
```

Expected output:
- The YAML for version 1.

What just happened:
- `config show` renders a saved version directly from disk.

Next:
- Diff two versions.

### 3. Diff two versions

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet config diff 1 2 --configs-dir config-demo
```

Expected output:
- Changed prompts, routing rules, thresholds, and tool timeouts.

What just happened:
- `config diff` gives you a schema-aware summary instead of a raw line diff.

Next:
- Migrate a legacy config.

### 4. Migrate a legacy config to the modern `optimization` section

```bash
cd "$AUTOAGENT_REPO"
"$AUTOAGENT_BIN" --quiet config migrate docs/samples/legacy_autoagent.yaml --output .tmp/legacy_autoagent_migrated.yaml
sed -n '1,220p' "$AUTOAGENT_REPO/.tmp/legacy_autoagent_migrated.yaml"
```

Expected output:
- A migrated YAML file with a new `optimization:` section.

What just happened:
- `config migrate` preserves the old settings and adds the new user-facing optimization shape.

Next:
- Try natural-language editing.

### 5. Propose a natural-language edit

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet edit "Make the root prompt more direct and shorter." --dry-run --configs-dir config-demo
```

Expected output:
- Intent, affected surfaces, a short diff summary, and before/after scores.

What just happened:
- `edit` translated a natural-language request into a config edit proposal.

Next:
- Protect a surface from mutation.

### 6. Pin and unpin a surface

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet pin prompts.root
"$AUTOAGENT_BIN" --quiet unpin prompts.root
```

Expected output:
- Confirmation that `prompts.root` was pinned and then unpinned.

What just happened:
- Pinned surfaces are treated as immutable by optimization flows.

Next:
- Deploy a version.

[What is next: Chapter 10](#chapter-10-deploy)

## Chapter 10: Deploy

> **What You Will Learn**
> - How to canary a version
> - How to monitor the deployed state
> - How to roll back with `reject`

### 1. Deploy a config version as a canary

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet deploy --config-version 2 --configs-dir config-demo --strategy canary
```

Expected output:
- A deployment confirmation such as `Deployed v003 as canary (10% traffic)`.

What just happened:
- AutoAgent promoted the selected config into a canary deployment slot.

Next:
- Check status and logs.

### 2. Monitor deployment health

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet status --configs-dir config-demo --json
"$AUTOAGENT_BIN" --quiet logs --limit 3
"$AUTOAGENT_BIN" --quiet explain --json | python3 -m json.tool | sed -n '1,120p'
```

Expected output:
- A status summary, recent logs, and a plain-English health summary.

What just happened:
- You inspected the deployment using three different lenses:
  - machine-readable status
  - raw logs
  - summarized explanation

Next:
- Roll back if needed.

### 3. Roll back the canary

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet reject demochg1 --configs-dir config-demo
```

Expected output:
- A rollback confirmation such as `Rejected experiment demochg1 and rolled back canary v003.`

What just happened:
- `reject` is the deployment-level rollback escape hatch.

Next:
- Look at release objects and deployment-related integration commands.

### 4. Release commands (current scaffold behavior)

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet release list
"$AUTOAGENT_BIN" --quiet release create --experiment-id demochg1
"$AUTOAGENT_BIN" --quiet release list
```

Expected output:
- `release list` prints the current placeholder state
- `release create` acknowledges the requested experiment ID

What just happened:
- In the current repo, `release` is a scaffold surface: it accepts the command but does not yet persist a release object.

Next:
- Move into the continuous loop.

[What is next: Chapter 11](#chapter-11-continuous-optimization-loop)

## Chapter 11: Continuous Optimization Loop

> **What You Will Learn**
> - How to run the continuous loop
> - How to pause and resume it
> - Which higher-autonomy entry points exist

### 1. Run one loop cycle

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet loop --max-cycles 1 --delay 0.1
```

Expected output:
- One loop cycle with health, optimizer, and canary output.

What just happened:
- AutoAgent ran the continuous loop exactly once, which is the safest way to learn its shape.

Next:
- Pause and resume the controller.

### 2. Pause and resume

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet pause
"$AUTOAGENT_BIN" --quiet resume
```

Expected output:
- `Optimizer paused...`
- `Optimizer resumed.`

What just happened:
- These are the human escape hatches for loop control.

Next:
- Run diagnosis and health checks.

### 3. Diagnose the current failure picture

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet diagnose --json | python3 -m json.tool | sed -n '1,160p'
"$AUTOAGENT_BIN" --quiet doctor
```

Expected output:
- JSON clusters from `diagnose`
- Store/config/API-key checks from `doctor`

What just happened:
- `diagnose` gives you structured failure clusters; `doctor` checks environment and storage.

Next:
- Use the alternative entry points.

### 4. Alternative entry points

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet quickstart --agent-name "Quickstart Alt" --dir "$AUTOAGENT_REPO/.tmp/quickstart-alt" --no-open
"$AUTOAGENT_BIN" --quiet full-auto --cycles 1 --max-loop-cycles 1 --yes
"$AUTOAGENT_BIN" --quiet autonomous --scope dev --cycles 1 --max-loop-cycles 1 --yes
```

Expected output:
- A complete quickstart run
- A one-cycle full-auto run that auto-promotes accepted configs
- A short autonomous-run acknowledgement for the selected scope

What just happened:
- `quickstart` is the safe one-command path.
- `full-auto` is the dangerous mode that skips manual promotion gates, so this guide limits it to one optimize cycle and one loop cycle.
- `autonomous` is the scoped entry point for higher-autonomy operation. In the current repo it is a light wrapper that acknowledges the requested scope and hands off to the autonomous runtime.

Next:
- Dive into context engineering.

[What is next: Chapter 12](#chapter-12-advanced--context-engineering)

## Chapter 12: Advanced - Context Engineering

> **What You Will Learn**
> - How to inspect context usage on one trace
> - How to simulate compaction strategies
> - How to read the aggregate context report

### 1. Analyze one trace

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet context analyze --trace trace_demo_fail_001
```

Expected output:
- Growth pattern, peak utilization, average utilization, compaction count, and recommendations.

What just happened:
- `context analyze` inspected token pressure for a single trace.

Next:
- Simulate compaction.

### 2. Simulate a compaction strategy

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet context simulate --strategy balanced
"$AUTOAGENT_BIN" --quiet context simulate --strategy aggressive
```

Expected output:
- Strategy names, trigger thresholds, retention settings, and a note that full simulation needs trace data through the API.

What just happened:
- You compared the built-in compaction profiles.

Next:
- Check the aggregate report.

### 3. Show the aggregate context report

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet context report
```

Expected output:
- Aggregate context health metrics or placeholders when there is not enough stored context data yet.

What just happened:
- `context report` gives you a higher-level view than per-trace analysis.

Next:
- Use transcript intelligence from the CLI.

[What is next: Chapter 13](#chapter-13-advanced--intelligence-studio-cli)

## Chapter 13: Advanced - Intelligence Studio (CLI)

> **What You Will Learn**
> - How to upload transcript data from the CLI
> - How to inspect the resulting report
> - How to generate an agent config from transcript evidence

> **Important**
> There is no first-class `autoagent intelligence ...` CLI group in this repo today.
> The supported CLI-driven path is to call the local API server from your terminal with `curl`.

### 1. Start the local server in a separate terminal

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet server --host 127.0.0.1 --port 8010
```

Expected output:
- Startup lines showing:
  - API docs at `http://localhost:8010/docs`
  - web console at `http://localhost:8010`

What just happened:
- You started the local API so CLI tools such as `curl` can talk to Intelligence Studio endpoints.

Next:
- In a second terminal, smoke-test the server.

### 2. Check the health endpoint

```bash
curl -s http://127.0.0.1:8010/api/health | python3 -m json.tool
```

Expected output:
- Health metrics, anomalies, failure buckets, and a `needs_optimization` boolean.

What just happened:
- You confirmed the server is alive and reading the workspace state.

Next:
- Upload the sample transcript archive.

### 3. Upload transcript data from the CLI

```bash
cd "$AUTOAGENT_REPO"
export ARCHIVE_BASE64="$(python3 - <<'PY'
import base64
from pathlib import Path
path = Path('docs/samples/sample_transcripts.json')
print(base64.b64encode(path.read_bytes()).decode('ascii'))
PY
)"
export ARCHIVE_RESPONSE="$(curl -s http://127.0.0.1:8010/api/intelligence/archive \
  -H 'Content-Type: application/json' \
  -d "{\"archive_name\":\"sample_transcripts.json\",\"archive_base64\":\"$ARCHIVE_BASE64\"}")"
printf '%s\n' "$ARCHIVE_RESPONSE" | python3 -m json.tool
export REPORT_ID="$(printf '%s\n' "$ARCHIVE_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["report_id"])')"
echo "$REPORT_ID"
```

Expected output:
- A transcript report JSON object
- A short `REPORT_ID` value such as `456c8d4a`

What just happened:
- You uploaded the transcript sample and captured the generated report ID for follow-up calls.

Next:
- Inspect the report.

### 4. Fetch the report details

```bash
curl -s "http://127.0.0.1:8010/api/intelligence/reports/$REPORT_ID" | python3 -m json.tool | sed -n '1,200p'
```

Expected output:
- Missing intents, FAQ entries, workflow suggestions, suggested tests, and mined insights.

What just happened:
- Intelligence Studio summarized the transcript archive into structured product and ops insights.

Next:
- Generate an agent config from those transcripts.

### 5. Generate an agent from the transcript report

```bash
curl -s http://127.0.0.1:8010/api/intelligence/generate-agent \
  -H 'Content-Type: application/json' \
  -d "{\"prompt\":\"Build a refund support agent from these transcripts\",\"transcript_report_id\":\"$REPORT_ID\"}" \
  | python3 -m json.tool | sed -n '1,220p'
```

Expected output:
- A generated config object with `system_prompt`, `tools`, `routing_rules`, `policies`, and `eval_criteria`.

What just happened:
- You used transcript-derived evidence to bootstrap a new agent design from the CLI.

Next:
- Start the MCP server and connect editor agents to AutoAgent.

[What is next: Chapter 14](#chapter-14-mcp-server)

## Chapter 14: MCP Server

> **What You Will Learn**
> - How to start the AutoAgent MCP server
> - How to smoke-test it over HTTP
> - How to connect Claude Code, Codex, and Cursor

### 1. Start the MCP server in HTTP mode

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet mcp-server --host 127.0.0.1 --port 8123
```

Expected output:
- The process stays attached and serves the MCP endpoint at `http://127.0.0.1:8123/mcp`.

What just happened:
- You launched the streamable-HTTP MCP transport. This is convenient for debugging and for clients that prefer URL-based MCP registration.

Next:
- In a second terminal, list the exposed tools.

### 2. Smoke-test the MCP endpoint

```bash
curl -s http://127.0.0.1:8123/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -m json.tool | sed -n '1,160p'
```

Expected output:
- A JSON-RPC response with tools such as:
  - `autoagent_status`
  - `autoagent_explain`
  - `autoagent_diagnose`
  - `autoagent_edit`
  - `autoagent_eval`

What just happened:
- You verified that the MCP server is exporting the AutoAgent tool catalog correctly.

Next:
- Add the server to your editor or coding agent.

### 3. Connect Claude Code

```bash
cd "$AUTOAGENT_REPO"
cat > .mcp.json <<'EOF'
{
  "mcpServers": {
    "autoagent": {
      "command": "autoagent",
      "args": ["mcp-server"]
    }
  }
}
EOF
cat .mcp.json
```

Expected output:
- A project-local `.mcp.json` file.

What just happened:
- You created the standard Claude Code project-scoped MCP config.

Next:
- Add the same server to Codex.

### 4. Connect Codex

```bash
mkdir -p "$HOME/.codex"
cat > "$HOME/.codex/config.toml" <<'EOF'
[mcp_servers.autoagent]
command = "autoagent"
args = ["mcp-server"]
EOF
cat "$HOME/.codex/config.toml"
```

Expected output:
- A `~/.codex/config.toml` file with the AutoAgent MCP entry.

What just happened:
- You configured Codex to launch AutoAgent over stdio.

Next:
- Add the same server to Cursor.

### 5. Connect Cursor

```bash
mkdir -p "$AUTOAGENT_REPO/.cursor"
cat > "$AUTOAGENT_REPO/.cursor/mcp.json" <<'EOF'
{
  "mcpServers": {
    "autoagent": {
      "command": "autoagent",
      "args": ["mcp-server"]
    }
  }
}
EOF
cat "$AUTOAGENT_REPO/.cursor/mcp.json"
```

Expected output:
- A project-local Cursor MCP config file.

What just happened:
- Cursor can now launch AutoAgent as a project-local MCP tool provider.

Next:
- Review the remaining command families in the appendices.

[What is next: Appendix A](#appendix-a-additional-core-commands)

## Appendix A: Additional Core Commands

This appendix covers the command families that are important but sit outside the main 14-chapter narrative.

### A.1 Dataset commands

#### 1. Create a dataset and capture its ID

```bash
cd "$GUIDE_WS"
export DATASET_OUTPUT="$("$AUTOAGENT_BIN" --quiet dataset create docs-dataset --description 'Dataset for docs')"
printf '%s\n' "$DATASET_OUTPUT"
export DATASET_ID="$(printf '%s\n' "$DATASET_OUTPUT" | sed -E 's/Dataset created: ([^ ]+) .*/\1/')"
echo "$DATASET_ID"
```

Expected output:
- A generated dataset ID such as `2e78848a34b344d8`.

What just happened:
- `dataset create` returns a generated dataset ID, so capturing it in a shell variable is the easiest copy-pasteable pattern.

Next:
- List datasets and inspect stats.

#### 2. List datasets and show stats

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet dataset list
"$AUTOAGENT_BIN" --quiet dataset stats "$DATASET_ID"
```

Expected output:
- `dataset list` prints dataset names and current versions
- `dataset stats` prints YAML with row counts, splits, and quality metrics

What just happened:
- You used the generated dataset ID for the stats lookup.

### A.2 Outcome import

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet outcomes import --source csv --file "$AUTOAGENT_REPO/docs/samples/sample_outcomes.csv"
```

Expected output:
- `Imported 2 outcomes from CSV`

What just happened:
- You loaded business outcome records into the local outcome store.

### A.3 Reward definitions

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet reward create refund_resolution --kind verifiable --scope runtime --source deterministic_checker --weight 1.0 --description "Reward successful refund resolution"
"$AUTOAGENT_BIN" --quiet reward list
"$AUTOAGENT_BIN" --quiet reward test refund_resolution --trace trace_demo_pass_001
```

Expected output:
- Reward creation output, the current reward list, and a reward test summary.

What just happened:
- You defined and inspected a reward function that can later feed optimization or RL workflows.

### A.4 Preference collection

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet pref collect --input-text "Customer asked for a refund" --chosen "I can help with that. Please share your order number." --rejected "Refund approved without verification." --source docs
"$AUTOAGENT_BIN" --quiet pref export --format generic
```

Expected output:
- `pref collect` echoes the pair you just submitted
- `pref export` currently prints the export format and then explains that no persisted pairs are available yet

What just happened:
- In the current repo, `pref collect` is a front-door command and `pref export` is a scaffold that does not yet read a persistent CLI-side store.

### A.5 RL / policy optimization

#### 1. Build a dataset and train a policy

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet rl dataset --mode preference --limit 5
"$AUTOAGENT_BIN" --quiet rl train --mode preference --backend openai_dpo --dataset "$AUTOAGENT_REPO/docs/samples/sample_preference_dataset.jsonl"
"$AUTOAGENT_BIN" --quiet rl jobs
```

Expected output:
- A dataset path, a completed mock training job, and a job list entry.

What just happened:
- The current RL training path creates a local policy artifact and records the job in `policy_opt.db`.

Next:
- Capture the generated policy ID and use the rest of the RL commands.

#### 2. Capture the newest policy ID

```bash
cd "$GUIDE_WS"
export POLICY_ID="$(python3 - <<'PY'
import json
import sqlite3
conn = sqlite3.connect('policy_opt.db')
row = conn.execute('SELECT data FROM policy_artifacts ORDER BY rowid DESC LIMIT 1').fetchone()
print(json.loads(row[0])['policy_id'] if row else '')
PY
)"
echo "$POLICY_ID"
```

Expected output:
- A policy ID such as `8f2c81be-86aa-4574-ba34-d8bbac1bcfd0`.

What just happened:
- You pulled the newest policy artifact ID directly from the local registry.

Next:
- Evaluate, canary, promote, and roll back it.

#### 3. Evaluate and manage the policy lifecycle

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet rl eval "$POLICY_ID"
"$AUTOAGENT_BIN" --quiet rl canary "$POLICY_ID"
"$AUTOAGENT_BIN" --quiet rl promote "$POLICY_ID"
"$AUTOAGENT_BIN" --quiet rl rollback "$POLICY_ID"
```

Expected output:
- An eval report, a canary confirmation, a promotion message, and a rollback confirmation.

What just happened:
- You exercised the whole local policy lifecycle after training.

### A.6 Benchmark and release commands

```bash
cd "$GUIDE_WS"
"$AUTOAGENT_BIN" --quiet benchmark run support_smoke --cycles 1
"$AUTOAGENT_BIN" --quiet release list
"$AUTOAGENT_BIN" --quiet release create --experiment-id demochg1
```

Expected output:
- `benchmark run` acknowledges the named benchmark
- `release` commands acknowledge the requested release flow

What just happened:
- In the current repo, these are scaffold commands. They run and confirm intent, but they do not yet create a durable benchmark or release history artifact.

### A.7 Server-side integration commands

#### ADK deploy (**live credentials required**)

```bash
"$AUTOAGENT_BIN" --quiet adk deploy "$AUTOAGENT_REPO/tests/fixtures/sample_adk_agent" --target cloud-run --project YOUR_GCP_PROJECT --region us-central1
```

Expected output:
- A deployment confirmation from the chosen GCP target.

What just happened:
- This is the live deployment path for ADK agents once you have real cloud credentials.

#### CX deploy/export/status/list (**live credentials required**)

```bash
"$AUTOAGENT_BIN" --quiet cx list --project YOUR_GCP_PROJECT --location global --credentials /absolute/path/to/service-account.json
"$AUTOAGENT_BIN" --quiet cx status --project YOUR_GCP_PROJECT --location global --agent YOUR_CX_AGENT_ID --credentials /absolute/path/to/service-account.json
"$AUTOAGENT_BIN" --quiet cx export --project YOUR_GCP_PROJECT --location global --agent YOUR_CX_AGENT_ID --config "$GUIDE_WS/imported_agent.yaml" --snapshot "$GUIDE_WS/cx-import-demo/your_snapshot.json" --credentials /absolute/path/to/service-account.json --dry-run
"$AUTOAGENT_BIN" --quiet cx deploy --project YOUR_GCP_PROJECT --location global --agent YOUR_CX_AGENT_ID --environment production --credentials /absolute/path/to/service-account.json
```

Expected output:
- Live CX API responses for your project.

What just happened:
- These commands are the production integration surface for CX Agent Studio.

### A.8 Demo commands

#### 1. Run the guided demo quickstart

```bash
"$AUTOAGENT_BIN" --quiet demo quickstart --dir "$AUTOAGENT_REPO/.tmp/demo-quickstart-guide" --no-open
```

Expected output:
- A compact demo flow that initializes a workspace, runs one eval pass, performs one optimization cycle, and ends with `Demo complete!`

What just happened:
- `demo quickstart` is the presentation-friendly sibling of `quickstart`. In the current repo it forces mock mode so the demo stays copy-pasteable even when API keys are present in your shell.

Next:
- Run the storytelling demo variant.

#### 2. Run the VP-ready storytelling demo

```bash
"$AUTOAGENT_BIN" --quiet demo vp --agent-name "Docs Demo Bot" --company "Docs Corp" --no-pause
```

Expected output:
- A scripted five-act story showing health, diagnosis, optimization, review, and results.

What just happened:
- `demo vp` is a polished terminal narrative for presentations. `--no-pause` removes the dramatic delays so it is safe to paste into a terminal during the tutorial.

## Appendix B: Command Reference Cheat Sheet

### Bootstrap and health

| Command | Purpose |
|---------|---------|
| `autoagent init` | Scaffold a new project |
| `autoagent quickstart` | Run the safe one-command golden path |
| `autoagent status` | Show health, counts, and next action |
| `autoagent doctor` | Check config, API keys, and local stores |
| `autoagent logs` | Show recent conversation logs |
| `autoagent explain` | Summarize the current agent state |
| `autoagent replay` | Show optimization history |
| `autoagent diagnose` | Produce structured failure clusters |

### Build, eval, optimize

| Command | Purpose |
|---------|---------|
| `autoagent build` | Generate an agent artifact from a prompt |
| `autoagent eval generate` | Create a synthetic eval suite |
| `autoagent eval run` | Run evals against a suite or dataset |
| `autoagent eval results` | Read a result file |
| `autoagent eval list` | List local result files |
| `autoagent optimize` | Run discrete optimization cycles |
| `autoagent loop` | Run the continuous loop |
| `autoagent pause` / `autoagent resume` | Control the loop |
| `autoagent full-auto` | High-autonomy optimize + loop |
| `autoagent autonomous` | Scoped autonomous mode |

### Trace, context, review, AutoFix

| Command | Purpose |
|---------|---------|
| `autoagent trace blame` | Cluster failures by likely root cause |
| `autoagent trace grade` | Grade spans in one trace |
| `autoagent trace graph` | Show critical path and bottlenecks |
| `autoagent trace promote` | Start trace-to-eval promotion flow |
| `autoagent context analyze` | Inspect per-trace context utilization |
| `autoagent context simulate` | Preview compaction strategies |
| `autoagent context report` | Show aggregate context health |
| `autoagent review list/show/apply/reject/export` | Human review for change cards |
| `autoagent changes list/show/approve/reject/export` | Alias family for review cards |
| `autoagent autofix suggest/apply/history` | AutoFix proposal lifecycle |

### Configs, deploy, and release

| Command | Purpose |
|---------|---------|
| `autoagent config list/show/diff/migrate` | Versioned config management |
| `autoagent edit` | Natural-language config editing |
| `autoagent pin` / `autoagent unpin` | Freeze or unfreeze config surfaces |
| `autoagent deploy` | Canary or immediate deployment |
| `autoagent reject` | Roll back a promoted experiment |
| `autoagent release list/create` | Release object scaffold surface |

### Skills, registry, runbooks, memory

| Command | Purpose |
|---------|---------|
| `autoagent skill list/show/create/test/search` | Inspect and manage skills |
| `autoagent skill compose` | Combine multiple skills |
| `autoagent skill export-md/import-md` | Portable `SKILL.md` round-trip |
| `autoagent skill effectiveness/recommend` | Inspect skill performance and suggestions |
| `autoagent skill install/publish/review/promote/archive` | Marketplace and lifecycle commands |
| `autoagent registry add/list/show/diff/import` | Manage skills, policies, tools, handoffs |
| `autoagent runbook create/list/show/apply` | Curated bundles of registry items |
| `autoagent memory show/add` | Manage `AUTOAGENT.md` project memory |

### Scoring, judges, data, and policy optimization

| Command | Purpose |
|---------|---------|
| `autoagent scorer create/list/show/refine/test` | NL scorer lifecycle |
| `autoagent judges list/calibrate/drift` | Judge operations |
| `autoagent dataset create/list/stats` | Dataset registry |
| `autoagent outcomes import` | Outcome ingestion |
| `autoagent reward create/list/test` | Reward definitions |
| `autoagent pref collect/export` | Preference collection/export |
| `autoagent rl dataset/train/jobs/eval/canary/promote/rollback` | Policy optimization lifecycle |
| `autoagent benchmark run` | Benchmark scaffold command |

### Integrations

| Command | Purpose |
|---------|---------|
| `autoagent adk import/status/diff/export/deploy` | Local ADK import and cloud deployment |
| `autoagent cx compat/widget/list/import/export/deploy/status` | CX Agent Studio integration |
| `autoagent server` | Start the API server and web console |
| `autoagent mcp-server` | Start the MCP server |

## Troubleshooting

### `doctor` says mock mode is enabled

That is expected for this guide. It keeps the walkthrough safe and reproducible.
When you want live provider calls, update `autoagent.yaml` and add real provider credentials.

### `config list` says no versions found

`config list/show/diff` expects a versioned config directory with a manifest.
Use `config-demo/` from this guide, or create your own directory with versioned YAML files plus a manifest.

### `autofix suggest` prints `No proposals generated.`

That is normal when the current workspace does not match any built-in AutoFix heuristics.
Use the seeded `demoaf1` proposal from `seed_demo_state.py` for a deterministic walkthrough.

### `trace promote` only prints a message

That is the current behavior in this repo. The command acknowledges the request but does not yet write a promoted eval case file.

### `release create`, `benchmark run`, or `pref export` feel light-weight

Those commands are scaffold surfaces today. They do run, but they are not yet full end-to-end workflows in the current codebase.

### `cx import` / `cx deploy` / `adk deploy` fail locally

Those commands need real cloud credentials and project-specific identifiers.
There is no offline mock path for the live cloud operations in this repo.

### `quickstart` used mock mode even though you have API keys

That is intentional for the guided path. It keeps the first-run experience reproducible.
After the tutorial, switch to live providers with your real runtime config and `eval run`.

## Verification Notes

The following command families were exercised locally while preparing this guide:

- `init`, `quickstart`, `status`, `doctor`, `logs`, `explain`, `replay`, `diagnose`
- `build`
- `eval generate`, `eval run`, `eval results`, `eval list`
- `trace blame`, `trace grade`, `trace graph`
- `context analyze`, `context simulate`, `context report`
- `optimize`, `loop`, `pause`, `resume`, `full-auto`, `autonomous`
- `review list/show/apply/export`, `changes reject`
- `autofix history`, `autofix apply`
- `skill create`, `skill list`, `skill show`, `skill test`, `skill compose`, `skill export-md`, `skill import-md`
- `registry add`, `registry list`, `registry show`, `registry diff`, `registry import`
- `runbook create`, `runbook list`, `runbook show`, `runbook apply`
- `memory show`, `memory add`
- `scorer create`, `scorer list`, `scorer show`, `scorer refine`, `scorer test`
- `judges list`, `judges calibrate`, `judges drift`
- `config list`, `config show`, `config diff`, `config migrate`, `edit`, `pin`, `unpin`
- `deploy`, `reject`
- `dataset create`, `dataset list`, `dataset stats`
- `outcomes import`
- `reward create`, `reward list`, `reward test`
- `rl dataset`, `rl train`, `rl jobs`, `rl eval`, `rl canary`, `rl promote`, `rl rollback`
- `curriculum generate`, `curriculum list`, `curriculum apply`
- `adk status`, `adk import`, `adk diff`, `adk export --dry-run`
- `cx compat`, `cx widget`
- `demo quickstart`, `demo vp`
- `server` plus `/api/intelligence/*`
- `mcp-server` plus `/mcp` `tools/list`
