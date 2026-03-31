# CX Studio Integration

This guide explains how AutoAgent integrates with Google Cloud CX Agent Studio and Dialogflow CX for real bidirectional import, diff, export, and sync workflows.

## What This Integration Covers

AutoAgent now imports and exports real Dialogflow CX agent resources rather than relying on placeholder mappings.

The integration covers:

- Agent metadata and generative settings
- Flows
- Pages nested under flows
- Intents
- Entity types
- Webhooks
- Playbooks
- Test cases
- Workspace snapshot persistence for round-trip fidelity
- Three-way sync with conflict detection

## API Surface

The implementation uses the Dialogflow CX REST `v3` API as the primary source of truth for agent resources:

- Global endpoint: `https://dialogflow.googleapis.com/v3`
- Regional endpoint pattern: `https://LOCATION-dialogflow.googleapis.com/v3`

This is intentional. The older CX Agent Studio REST surface is useful for some newer console features, but the required configuration surfaces in this implementation, especially flows, intents, entity types, and webhooks, live in Dialogflow CX `v3`.

## Authentication

AutoAgent uses `google-auth` and supports the three practical authentication modes teams use with Google Cloud:

1. Service account JSON
2. Application Default Credentials (ADC)
3. OAuth-backed ADC from `gcloud auth application-default login`

### Option 1: Service Account JSON

Use this for CI, production automation, and shared operational workflows.

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
autoagent cx auth
```

You can also pass the file directly:

```bash
autoagent cx auth --credentials /path/to/service-account.json
```

### Option 2: Application Default Credentials

If `GOOGLE_APPLICATION_CREDENTIALS` points to a service account file, AutoAgent will use it automatically through ADC.

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
autoagent cx auth
```

### Option 3: OAuth via gcloud

This is the easiest local development path for a human operator.

```bash
gcloud auth application-default login
autoagent cx auth
```

This produces user credentials in the local ADC store. AutoAgent treats that as an ADC flow, but the underlying credential source is OAuth.

### Verifying Auth

Use the new command before any import or export work:

```bash
autoagent cx auth [--credentials /path/to/service-account.json]
```

The command prints:

- Auth type
- Resolved project ID when available
- Principal
- Whether the integration is using ADC or an explicit credentials file

## IAM Permissions

Use the minimum permissions that still allow your intended workflow.

### Read-only import and diff

At minimum, the identity should be able to:

- Get agents
- List agents
- Get and list flows
- Get and list pages
- Get and list intents
- Get and list entity types
- Get and list webhooks
- Get and list playbooks
- Get and list test cases
- Get and list environments if you plan to inspect deployment status

### Export and sync

For write-back operations, the identity also needs permission to:

- Patch agents
- Patch flows
- Patch intents
- Patch entity types
- Patch webhooks
- Patch playbooks
- Create missing resources when AutoAgent needs to materialize new ones

### Recommended Role Strategy

In most environments, create a dedicated integration service account and grant it:

- Read-only permissions in production for initial rollout
- Write permissions only in approved staging or automation projects
- Narrow project and region scope where possible

For regulated or high-risk deployments:

- Use one service account per environment
- Store keys in Secret Manager, not in the repo
- Keep explicit audit logging around AutoAgent-triggered write-back
- Require human review before `sync` or non-dry-run `export`

## Workspace Model

When you import a CX agent, AutoAgent creates a normal workspace and also stores CX-specific round-trip metadata.

### Important Files

After import, the workspace contains:

- `configs/v001.yaml`
  The active AutoAgent config derived from the imported agent.
- `evals/cases/imported_connect.yaml`
  Starter evals generated from CX test cases when test-case import is enabled.
- `.autoagent/cx/snapshot.json`
  The imported CX snapshot used as the merge base for later export and sync.
- `.autoagent/cx/workspace.json`
  The mapped workspace representation used by the CX integration.
- `.autoagent/cx/manifest.json`
  The bridge file that links the workspace, config, snapshot, and CX agent coordinates.

### Why the Snapshot Matters

The snapshot is what makes incremental sync possible.

AutoAgent uses it as the base in a three-way comparison:

- Base: the imported snapshot
- Local: the current AutoAgent config mapped back to CX
- Remote: the latest live CX state fetched from Google Cloud

That is how the integration can distinguish:

- local-only edits
- remote-only edits
- overlapping edits that need conflict handling

## CLI Workflow

### 1. Authenticate

```bash
autoagent cx auth
```

Or with explicit credentials:

```bash
autoagent cx auth --credentials /path/to/service-account.json
```

### 2. List Agents

```bash
autoagent cx list --project PROJECT --location us-central1
```

### 3. Import an Agent

```bash
autoagent cx import AGENT_ID --project PROJECT --location us-central1
```

Compatibility form:

```bash
autoagent cx import --project PROJECT --location us-central1 --agent AGENT_ID
```

Optional flags:

- `--output-dir`
- `--credentials`
- `--no-test-cases`

### 4. Diff Local Changes Against the Live Agent

From inside the imported workspace:

```bash
autoagent cx diff AGENT_ID --project PROJECT --location us-central1
```

If you are already inside the imported workspace, AutoAgent can resolve the active config and snapshot automatically from `.autoagent/cx/manifest.json`.

You can still override paths explicitly:

```bash
autoagent cx diff AGENT_ID \
  --project PROJECT \
  --location us-central1 \
  --config configs/v004.yaml \
  --snapshot .autoagent/cx/snapshot.json
```

### 5. Preview Export

```bash
autoagent cx export AGENT_ID \
  --project PROJECT \
  --location us-central1 \
  --dry-run
```

This compares the active config with the imported snapshot and shows the changes that would be pushed.

### 6. Push Export

```bash
autoagent cx export AGENT_ID \
  --project PROJECT \
  --location us-central1
```

Use this when you want to push the local config as-is relative to the stored snapshot.

### 7. Safe Sync

```bash
autoagent cx sync AGENT_ID \
  --project PROJECT \
  --location us-central1
```

By default, sync uses conflict detection:

```bash
autoagent cx sync AGENT_ID \
  --project PROJECT \
  --location us-central1 \
  --conflict-strategy detect
```

If the same field changed both locally and remotely since import, AutoAgent reports a conflict and does not push.

## CLI Semantics: Export vs Sync

Use `export` when:

- You want to push local config changes based on the imported snapshot
- You do not need remote-aware merge semantics
- You already reviewed the workspace and want a direct write-back

Use `sync` when:

- The live CX agent may have changed since import
- You want conflict detection before writing
- You are operating in a shared admin environment

Use `diff` when:

- You want to inspect planned changes and conflicts without writing anything

## Web UI Workflow

The new web control surface lives at:

- `/cx/studio`

### What the Page Provides

- Project selector
- Region selector
- Optional credentials-path input
- Auth verification
- Agent browser
- Import action
- Config version selector
- Snapshot path control
- Diff against remote
- Preview export
- Safe sync
- Push export
- Conflict panel

### Recommended Usage

1. Enter project and region
2. Verify credentials
3. Browse and select an agent
4. Import it into a workspace
5. Choose the active config version
6. Review `Diff vs remote`
7. Use `Sync safely` if the agent may have changed remotely
8. Use `Push export` once the plan is understood

## Mapping Model

AutoAgent’s internal config model is simpler than Dialogflow CX, so the integration uses a layered mapping strategy.

### Normalized AutoAgent Fields

- `prompts`
- `routing.rules`
- `tools`
- `model`

### Preserved CX Fidelity

To avoid data loss, the integration stores full CX resource details in workspace metadata rather than forcing everything into the normalized config.

That preserved metadata includes:

- agent metadata
- flows
- intents
- entity types
- webhooks
- playbooks
- the full imported snapshot

This lets AutoAgent expose a usable local config while still restoring precise CX structures during export and sync.

## Conflict Detection

The sync path uses three-way conflict detection per managed field.

AutoAgent currently tracks conflicts across:

- Agent description and generative settings
- Playbook instruction text
- Flow descriptions and transition routes
- Intent training phrases
- Entity type kind, entities, and excluded phrases
- Webhook endpoint configuration, timeout, and disabled state

If both local and remote values changed from the same base and no longer match each other, the sync returns a conflict instead of writing.

## Incremental Sync Behavior

Successful sync does two things:

1. Pushes the merged changes to CX
2. Rewrites `.autoagent/cx/snapshot.json` with the merged post-sync snapshot

That keeps the next diff or sync incremental instead of comparing against stale import-time state forever.

## API Routes

The backend now exposes:

- `POST /api/cx/auth`
- `GET /api/cx/agents`
- `POST /api/cx/import`
- `POST /api/cx/export`
- `POST /api/cx/diff`
- `POST /api/cx/sync`
- `POST /api/cx/deploy`
- `POST /api/cx/widget`
- `GET /api/cx/status`
- `GET /api/cx/preview`

## Operational Guidance

Start with this rollout order:

1. `auth`
2. `list`
3. `import`
4. local config review and evals
5. `diff`
6. `sync` in staging
7. `export` or `sync` in production after review

For team use:

- Treat import as the beginning of a tracked workspace lifecycle
- Re-import if the live agent changed significantly outside AutoAgent
- Prefer `sync` over `export` when multiple operators touch the same CX agent

## Current Limitations

- The broader web app build currently has unrelated pre-existing TypeScript issues outside the CX pages, so targeted frontend tests are the reliable verification signal for this integration at the moment.
- The deploy and widget paths remain compatibility-oriented and were not the primary focus of this import/export implementation.
- The mapper preserves fidelity through metadata, so not every CX concept is expressed directly in the small normalized AutoAgent config surface.

## Verification Performed

Backend verification:

- `pytest -q tests/test_cx_roundtrip.py tests/test_cx_studio.py tests/test_cx_studio_api.py tests/test_cx_studio_integration.py`

Frontend verification:

- `npm test -- CXStudio.test.tsx CxImport.test.tsx`

Frontend build note:

- `npm run build` currently fails because of unrelated existing TypeScript issues in other result-comparison pages and shared types, not because of the new CX Studio page itself.
