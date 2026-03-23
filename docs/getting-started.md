# Getting Started

This guide gets AutoAgent VNextCC running locally with the CLI, API, and web console.

## Prerequisites

- Python 3.11+
- `pip`
- Node.js 20+ (only needed for frontend development/build)
- Git

Check versions:

```bash
python --version
node --version
```

## Install

```bash
git clone https://github.com/your-org/AutoAgent-VNextCC.git
cd AutoAgent-VNextCC
pip install -e ".[dev]"
```

Verify CLI install:

```bash
autoagent --version
# autoagent, version 1.0.0
```

## Step 1: Initialize Project Assets

```bash
autoagent init --template customer-support
```

Expected output:

```text
Initialized AutoAgent project in /.../AutoAgent-VNextCC
  Template: customer-support
  Config:   configs/v001_base.yaml
  Evals:    evals/cases/
```

## Step 2: Run an Evaluation

```bash
autoagent eval run --output results.json
```

Expected output shape:

```text
Full eval suite
  Cases: 42/50 passed
  Quality:   0.7800
  Safety:    1.0000 (0 failures)
  Latency:   0.8500
  Cost:      0.7200
  Composite: 0.8270

Results written to results.json
```

Inspect results later:

```bash
autoagent eval results --file results.json
```

## Step 3: Start API + Web Console

```bash
autoagent server
```

By default, this starts:
- Web console: `http://localhost:8000`
- OpenAPI docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- WebSocket: `ws://localhost:8000/ws`

## First Web Walkthrough

1. Open `http://localhost:8000`
2. Go to **Eval Runs** and create a run from the UI
3. Open **Eval Detail** to inspect per-case outcomes
4. Go to **Optimize** and run a cycle
5. Open **Configs** to inspect YAML and compare versions

## Quick Validation Commands

```bash
# Status snapshot
autoagent status

# Config history
autoagent config list

# Recent logs
autoagent logs --limit 10

# API smoke test
curl http://localhost:8000/api/health
```

## Frontend Dev Mode (Optional)

If you are actively editing the React app:

```bash
# Terminal A
autoagent server

# Terminal B
cd web
npm install
npm run dev
```

Use the Vite URL (`http://localhost:5173`) for hot reload while keeping API on port 8000.

## Common Setup Issues

### `autoagent` command not found

Re-install with editable mode from repo root:

```bash
pip install -e ".[dev]"
```

### No data in Dashboard

The dashboard reflects logged conversation/eval/optimization data. Run:

```bash
autoagent eval run --output results.json
autoagent optimize --cycles 1
```

Then refresh the web app.

### Frontend does not load from `autoagent server`

Build frontend assets once:

```bash
cd web
npm install
npm run build
```

Then re-run `autoagent server`.
