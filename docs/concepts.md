# Core Concepts

This guide explains the product concepts that show up across the AutoAgent CLI, API, and web console today.

If you are new to the project, start with these ideas:

1. A workspace holds versioned agent configs, evals, and local runtime state.
2. Most work follows the same loop: build, eval, compare, optimize, review, deploy.
3. The UI and CLI operate on the same files and local databases, so they should agree.

## The Core Loop

The current product is organized around this operator loop:

```text
BUILD -> EVAL -> COMPARE -> OPTIMIZE -> REVIEW -> DEPLOY
```

What each step means in practice:

- **Build** creates or updates a config from a prompt, transcript archive, builder chat session, or imported runtime.
- **Eval** runs that config against eval cases and records a scored run.
- **Compare** helps you judge deltas between runs or configs instead of looking at one score in isolation.
- **Optimize** generates and tests candidate improvements.
- **Review** is where humans approve or reject proposed changes.
- **Deploy** controls active and canary rollout state.

This loop matters because AutoAgent is not just a prompt editor. It is a local system for iterating on agent behavior with evidence.

## Workspace

A workspace is the local directory where AutoAgent stores the things it needs to work on an agent over time.

Typical workspace contents include:

- `autoagent.yaml` for workspace-level settings
- `configs/` for versioned configs such as `v001.yaml`
- `evals/` for eval cases and generated suites
- `.autoagent/` for operational state such as traces, deployment metadata, CX metadata, and local stores
- `AUTOAGENT.md` for project memory

When the docs mention "the active workspace", they mean the directory AutoAgent discovered from your current working directory.

## Config Versions

AutoAgent treats configs as versioned artifacts, not an untracked blob.

Important terms:

- **Config version**: a numbered config file such as `configs/v003.yaml`
- **Active config**: the version the workspace currently treats as the main local candidate
- **Canary version**: a version currently being observed in rollout
- **Imported version**: a version produced by an external import flow such as Connect or CX

Common CLI surfaces:

```bash
autoagent config list
autoagent config show
autoagent config set-active 3
autoagent build show latest
```

The web console exposes the same idea through Build, Configs, Compare, and Deploy.

## Modes: Mock, Live, and Auto

AutoAgent supports three execution modes:

- **mock**: safe local/demo behavior, useful when provider credentials are missing
- **live**: run against live providers and real integrations
- **auto**: let AutoAgent choose based on what is configured

This is why Setup shows both provider readiness and effective mode. A workspace can be healthy in mock mode even before real API keys are configured.

Common CLI surfaces:

```bash
autoagent mode show
autoagent mode set mock
autoagent mode set live
autoagent doctor
```

## Instructions

New starter workspaces now default to XML root instructions.

The root instruction usually lives in:

- `prompts.root` in the active config

Why that matters:

- the CLI can validate and regenerate the instruction structure
- the Build page includes an XML Instruction Studio
- eval runs can apply temporary instruction overrides without rewriting the baseline config

Common CLI surfaces:

```bash
autoagent instruction show
autoagent instruction validate
autoagent instruction generate --brief "customer support agent for refunds"
autoagent instruction migrate
```

Plain-text prompts still load, but XML is now the default authoring format.

## Build Sources

There is no single "one true" way to create an agent in AutoAgent.

The current build surface supports four main entry points:

- **Prompt**: generate from a plain-language brief
- **Transcript**: import archived conversations and generate from the observed patterns
- **Builder Chat**: iteratively refine behavior in a conversational workflow
- **Saved Artifacts**: inspect previous build outputs

The related import surface is **Connect**, which is for bringing in an existing runtime instead of starting from scratch.

## Eval Runs vs Results Explorer vs Compare

These are related, but they are not the same thing.

### Eval Runs

Use Eval Runs to answer:

- Did the run finish?
- How many cases passed?
- Which config did I test?
- What is the high-level score?

### Results Explorer

Use Results Explorer to answer:

- Which examples failed?
- What patterns are showing up?
- Which examples need annotations?
- What should I export for review?

### Compare

Use Compare to answer:

- Which config or run performed better head-to-head?
- Is the difference meaningful?
- Where are the biggest deltas?

This split is one of the biggest changes in the current product. The docs should not collapse all eval behavior into one generic "results page."

## Improvements

The current review workflow is called **Improvements**.

It brings together four related objects:

- **Opportunities**: ranked failure clusters or problem areas worth addressing
- **Experiments**: evaluated candidate changes and their evidence
- **Review**: change cards and approval decisions
- **History**: accepted and rejected decisions over time

Older names such as `Change Review`, `Experiments`, or `Opportunities` still exist as legacy routes in some cases, but the current primary page is `Improvements`.

## Deployment State

Deploy is about rollout state, not edit history.

The important concepts are:

- **Active version**: the version currently considered primary
- **Canary version**: the version being observed before wider promotion
- **Deployment history**: what was pushed, when, and with what status
- **Rollback**: return traffic to the prior stable state

Common CLI surfaces:

```bash
autoagent deploy --strategy canary --yes
autoagent deploy status
autoagent deploy rollback --yes
```

The review step and deploy step are intentionally separate. Accepting a change does not automatically mean it is fully promoted.

## Human Control

AutoAgent can automate a lot, but it still exposes explicit human control points.

The most important ones today are:

- review and apply pending changes
- deploy with confirmation or `--yes`
- pause and resume loop activity
- pin and unpin config surfaces
- reject a specific experiment or review card

Examples:

```bash
autoagent review list
autoagent review apply pending
autoagent pause
autoagent resume
autoagent pin prompts.root
autoagent unpin prompts.root
```

These commands live in the advanced surface, so use `autoagent advanced` if you do not see them in the default help.

## Integrations

AutoAgent now has multiple import and deployment surfaces:

- **Connect** for OpenAI Agents, Anthropic projects, HTTP runtimes, and transcript imports
- **CX Studio** for Google CX auth, import, diff, export, and sync workflows
- **ADK** for Google Agent Development Kit import and deploy flows
- **MCP server** for coding-agent integrations like Codex, Claude Code, Cursor, and Windsurf

These are part of the current product, not side experiments.

## Recommended Mental Model

If you only remember one model, use this:

1. Start with a workspace that is healthy in Setup.
2. Build or import a versioned config.
3. Run evals and inspect the results.
4. Compare versions when you need a decision, not just a score.
5. Review proposed improvements before you ship them.
6. Deploy with canary-friendly rollout when the evidence is strong enough.

## Next Steps

- [Platform Overview](platform-overview.md)
- [UI Quick Start Guide](UI_QUICKSTART_GUIDE.md)
- [App Guide](app-guide.md)
- [CLI Reference](cli-reference.md)
- [XML Instructions](xml-instructions.md)
