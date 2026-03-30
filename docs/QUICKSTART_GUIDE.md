# AutoAgent Quick Start

Get a working agent in under 2 minutes.

## Install

```bash
pip install autoagent
```

## Create an agent

```bash
autoagent new my-agent --template customer-support
cd my-agent
```

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
autoagent optimize --cycles 3
```

## Deploy it

```bash
autoagent deploy canary --yes
```

## What's next?

- `autoagent status` — see workspace health
- `autoagent shell` — interactive mode
- `autoagent doctor` — troubleshoot issues
- See the [Detailed Guide](DETAILED_GUIDE.md) for the full walkthrough

## Troubleshooting

**"No workspace found"** — You're outside a workspace directory. Run `autoagent new my-project`.

**"Provider credentials missing"** — Set your API key: `export OPENAI_API_KEY=sk-...` AutoAgent auto-detects your key and switches to live mode.

**Need advanced features?** — Run `autoagent advanced` to see all commands (permissions, sessions, usage tracking, MCP, and more).
