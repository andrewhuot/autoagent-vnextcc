# AutoAgent Quick Start

Get a working agent in under 2 minutes.

## Install

```bash
git clone https://github.com/andrewhuot/autoagent-vnextcc.git
cd autoagent-vnextcc
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Create an agent

```bash
autoagent new my-agent --template customer-support --demo
cd my-agent
```

`--demo` seeds extra review data so the full walkthrough includes review and autofix surfaces on a brand-new workspace.

## Build it

```bash
autoagent build "customer support agent for order tracking, refunds, and cancellations"
```

## Test it

```bash
autoagent eval run
```

## Optimize it

```bash
autoagent optimize --cycles 1
```

## Deploy it

```bash
autoagent deploy --auto-review --yes
```

## What's next?

- `autoagent status` — see workspace health
- `autoagent shell` — interactive mode
- `autoagent doctor` — troubleshoot issues
- See the [Detailed Guide](DETAILED_GUIDE.md) for the full walkthrough

## Troubleshooting

**"No workspace found"** — You're outside a workspace directory. Run `autoagent new my-project`.

**"Provider credentials missing"** — Set your API key: `export OPENAI_API_KEY=sk-...` AutoAgent auto-detects your key and switches to live mode.

**"No candidate config version available to deploy"** — This usually means your workspace only has an active deployed version. Run `autoagent build "Describe your agent"` to stage a fresh config, `autoagent review apply pending` to accept a saved review card, or `autoagent optimize --cycles 1` to generate more reviewable output.

**Need advanced features?** — Run `autoagent advanced` to see all commands (permissions, sessions, usage tracking, MCP, and more).
