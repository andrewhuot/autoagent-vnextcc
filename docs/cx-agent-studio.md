# CX Agent Studio Integration Guide

This guide describes a practical path to integrate AutoAgent VNextCC with Google Cloud CX Agent Studio (Dialogflow CX / CCAI).

Current state:
- AutoAgent core loop is implemented for local config/version control.
- A native CX adapter is **not** implemented in this repository yet.
- This document defines the recommended architecture and rollout plan for customer deployments.

## Who This Is For

Use this guide if you:
- already run an agent in Dialogflow CX
- want AutoAgent to analyze quality and propose improvements
- need controlled rollout and rollback semantics in a regulated environment

## Integration Modes

Start with the smallest-risk mode and move forward only after validation.

## Mode 1: Read-Only Analytics (recommended first)

- Pull conversation transcripts and metadata from CX
- Map data into AutoAgent conversation schema
- Run observer/evals/optimizer in recommendation-only mode
- No automatic write-back to CX

Best for first production pilots.

## Mode 2: Human-Approved Suggest + Apply

- AutoAgent proposes config changes in AutoAgent YAML
- Human approves in a review surface
- Adapter applies approved changes to CX via API

Best for teams that want velocity plus explicit approval controls.

## Mode 3: Controlled Auto-Apply + Canary

- AutoAgent can apply changes automatically under policy
- CX experiments or traffic split handles canary exposure
- Auto rollback on degraded success/safety outcomes

Best for mature teams with strong observability and change governance.

## Target Architecture

```text
┌─────────────────────────────┐      ┌──────────────────────────────────┐
│ Dialogflow CX (GCP)         │      │ AutoAgent VNextCC                │
│ - Agents / Flows / Pages    │<---->│ CX Adapter Layer                 │
│ - Conversations             │      │ - Conversation ingest            │
│ - Experiments               │      │ - Config translator              │
└──────────────┬──────────────┘      │ - Deploy bridge                  │
               │                     └──────────────┬───────────────────┘
               │                                    │
               │                           ┌────────▼────────┐
               │                           │ Observer/Evals  │
               │                           │ Optimizer/Gates │
               │                           └────────┬────────┘
               │                                    │
               └────────────────────────────┬───────▼─────────────┐
                                            │ Versioning + Canary  │
                                            │ + Audit trail        │
                                            └──────────────────────┘
```

## Required Google Cloud APIs

- Dialogflow CX API
- Dialogflow Conversations API
- Dialogflow Experiments API (if using experiments for canary)
- Cloud Logging API (optional, for enriched analytics)

## IAM and Security Model

Use a dedicated service account per environment (`dev`, `staging`, `prod`).

Recommended minimum roles (exact role names vary by org policy):
- read CX agent resources
- read conversation transcripts/metadata
- create/update experiments (if canary mode enabled)
- update flows/pages/intents only in approved environments

Hard requirements:
- store credentials in Secret Manager, not in repo
- explicit allowlist for project + location + agent IDs
- full audit log for every write-back operation

## Data Mapping Strategy

AutoAgent operates on a normalized conversation record shape. Build a deterministic mapper from CX conversation/turn payloads.

## Conversation Mapping

| CX source | AutoAgent field | Notes |
|---|---|---|
| Conversation resource name | `conversation_id` | Keep stable ID for traceability |
| Session identifier | `session_id` | Required for grouping |
| User utterance text | `user_message` | Latest or turn-scoped, depending on mode |
| Agent response text | `agent_response` | Flatten response variants deterministically |
| Webhook/tool metadata | `tool_calls` | Preserve payload for debugging |
| Derived latency | `latency_ms` | Compute from timestamps if needed |
| Token estimate | `token_count` | Optional estimate if raw token count unavailable |
| Outcome signal | `outcome` | Map to `success|fail|error|abandon` |
| Route/page/flow | `specialist_used` | Useful for routing analysis |
| Safety indicators | `safety_flags` | Normalize to a string list |
| Event timestamp | `timestamp` | Unix epoch in seconds |

## Config Mapping

AutoAgent config fields do not map 1:1 with CX resources. Use an adapter with explicit translation rules and validation.

| AutoAgent concept | Typical CX source |
|---|---|
| Routing rules | Flows, pages, transition routes, intent routes |
| Prompt/system text | Flow/page fulfillment text and generative settings |
| Tool hooks | Webhooks and integrations |
| Thresholds | NLU confidence / route settings |

Recommendation:
- keep a reversible mapping artifact for each sync
- reject ambiguous transforms instead of guessing
- require human review for destructive route changes

## Suggested Adapter Interfaces

Use three explicit components:

1. `CXConversationAdapter`
- incremental ingest by timestamp/watermark
- idempotent writes into `ConversationStore`

2. `CXConfigAdapter`
- `from_cx(...) -> autoagent_config`
- `to_cx(...) -> set of API operations`

3. `CXDeployBridge`
- apply approved config patch
- trigger experiment/canary
- report rollout status back to AutoAgent

## Rollout Plan

## Phase 1: Read-Only Validation

Deliverables:
- conversation ingest job
- health dashboard from real CX traffic
- optimizer suggestions with no write-back

Acceptance criteria:
- deterministic mapping for >= 95% of sampled conversations
- no data loss across repeated sync windows
- useful failure buckets for routing/safety/tooling

## Phase 2: Human-Approved Write-Back

Deliverables:
- proposed changes rendered as reviewable diff
- approval action that triggers adapter apply
- rollback action from same control plane

Acceptance criteria:
- every write has audit record and operator identity
- roll-forward and rollback tested in staging
- failed applies are recoverable without manual DB edits

## Phase 3: Managed Canary Automation

Deliverables:
- traffic split or CX experiment orchestration
- automated verdict logic (promote/rollback)
- policy guardrails (safety floor, min sample size, timeout)

Acceptance criteria:
- no unsafe promotion when safety gate fails
- measurable regression detection under real traffic
- on-call runbook validated by game day

## Operational Guardrails

Before enabling auto-apply in production:
- set explicit minimum sample sizes for canary verdicts
- enforce safety hard gate at both eval and runtime layers
- block multi-surface edits in one release when confidence is low
- require rollback path verification in every deploy window

## Recommended Telemetry

Capture these dimensions for each candidate:
- baseline vs canary success rate
- safety incident rate
- latency distribution (not just average)
- fallback/escalation rate
- route-level failure concentration

## Example Future CLI (proposed)

These commands are examples for a future integration package, not current built-ins:

```bash
autoagent cx connect --project-id P --location L --agent-id A
autoagent cx sync conversations --since 2026-03-01T00:00:00Z
autoagent cx propose --window 500
autoagent cx apply --proposal-id prop_123 --strategy canary
autoagent cx rollback --deployment-id dep_456
```

## Non-Goals for Initial Release

- full bidirectional conflict-free merge between CX UI edits and AutoAgent edits
- automatic schema migration of all custom CX artifacts
- cross-region active/active orchestration

Keep initial scope narrow and auditable. Expand after stable production evidence.

