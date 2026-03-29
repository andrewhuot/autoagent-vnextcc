# CX Agent Studio Integration Brief

## Mission
Build a bidirectional integration between AutoAgent and Google Cloud CX Agent Studio (Conversational Agents). Users should be able to:
1. **Import** an existing CX agent's config, playbooks, tools, and conversation history into AutoAgent
2. **Optimize** the agent using AutoAgent's loop
3. **Export** the optimized config back to CX Agent Studio
4. **Deploy** the optimized agent as a web widget or via REST API

## Reference Documentation

### CX Agent Studio REST API
- Base URL: `https://ces.googleapis.com/v1`
- Resource hierarchy: `projects/{project}/locations/{location}/apps/{app}/...`
- Key resources (v1 API):
  - **Apps**: Top-level application containers
  - **Agents**: CRUD on agent configs (display name, default language, description, gen AI settings)
  - **Tools**: Tool definitions (OpenAPI specs, data store connections, function definitions)
  - **Toolsets**: Collections of tools
  - **Examples**: Few-shot learning examples (replaces test cases/training phrases)
  - **Guardrails**: Safety settings and content filters
  - **Deployments**: Deployment environments (production, staging, etc.)
  - **Conversations**: Conversation history and session management
  - **Sessions**: Runtime session handling (runSession, streamRunSession)
  - **Versions**: Version management for apps
  - **Changelogs**: Change history tracking
- Auth: Google Cloud service account or ADC (Application Default Credentials)
- API Reference: https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/reference/rest/v1-overview

**Note**: CX Agent Studio is NOT Dialogflow CX. The resource model is different:
- Uses `ces.googleapis.com` (NOT `dialogflow.googleapis.com`)
- Apps are the parent resource (NOT direct agent hierarchy)
- Uses Examples (NOT Intents/Flows/Training Phrases from Dialogflow CX)
- Uses Guardrails (NOT just generativeSettings)

### Web Widget Deployment
- Embed via `<chat-messenger>` web component (NOT `<df-messenger>`)
- Config includes: project-id, agent-id, language-code, chat-title, theme customization
- Widget scripts/CSS may still be hosted at dialogflow-console URLs (legacy hosting)
- Docs: https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/deploy/web-widget

### CX Agent Studio MCP Server
- Available as an MCP server for tool-based interaction
- Can be used for agent discovery, config reading, and potentially deployment
- Docs: https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/mcp-server

## Architecture Design Task

Before implementing, the architect (Opus) should:

1. **Read the existing codebase structure** — understand how configs, evals, and the optimizer work today
2. **Design the module structure** — likely:
   ```
   cx_studio/
   ├── __init__.py
   ├── auth.py           # Google Cloud auth (ADC, service account JSON)
   ├── client.py          # REST API client for CX Agent Studio
   ├── importer.py        # Import agent → AutoAgent config format
   ├── exporter.py        # Export optimized config → CX Agent Studio format
   ├── deployer.py        # Deploy to web widget + environments
   ├── mapper.py          # Bidirectional mapping: CX schema ↔ AutoAgent schema
   ├── types.py           # CX-specific type definitions
   └── mcp.py             # MCP server integration (optional)
   ```
3. **Design the CLI commands**:
   ```
   autoagent cx import --project PROJECT --location LOCATION --agent AGENT_ID
   autoagent cx export --project PROJECT --location LOCATION --agent AGENT_ID
   autoagent cx deploy --project PROJECT --location LOCATION --agent AGENT_ID [--environment production]
   autoagent cx widget --project PROJECT --location LOCATION --agent AGENT_ID [--output widget.html]
   autoagent cx status --project PROJECT --location LOCATION --agent AGENT_ID
   autoagent cx list --project PROJECT --location LOCATION
   ```
4. **Design the config mapping**:
   - CX Agent's `generativeSettings` → AutoAgent's `generation_settings` config surface
   - CX Playbook instructions → AutoAgent's `instructions` surface
   - CX Tools → AutoAgent's `tool_descriptions` surface
   - CX Examples → AutoAgent's `examples` surface
   - CX Flows/Pages/Routes → AutoAgent's `routing` surface
   - CX Test Cases → AutoAgent eval cases
   - CX Conversations → AutoAgent conversation store (for observer)
5. **Design the web console pages**:
   - Import wizard page (select project → select agent → preview → import)
   - Deploy page (select environment → deploy → get widget embed code)

## Key Design Decisions to Make

1. **Auth strategy**: ADC vs service account JSON vs both?
2. **Config mapping granularity**: Do we map every CX field or just the optimizable surfaces?
3. **Deployment safety**: Should export require human approval? (Yes — use change cards)
4. **MCP vs REST**: Use MCP server for discovery/read, REST API for writes/deploys?
5. **Offline mode**: Should import create a snapshot that works without GCP connectivity?
6. **Widget generation**: Static HTML file vs dynamic preview in web console?

## Implementation Constraints

- Add `cx_studio/` as a NEW top-level module — don't modify existing modules
- The `cx_studio/` module is Layer 1 (advanced) in the dependency hierarchy — it can import from core but core must not import from it
- CLI commands go under a `cx` subgroup in runner.py
- Use `google-auth` and `google-auth-httplib2` or `httpx` for API calls (check what's available)
- All API calls should have retry logic and proper error handling
- Add comprehensive tests with mocked API responses
- Web pages go in `web/src/pages/CxImport.tsx` and `web/src/pages/CxDeploy.tsx`
- API routes go in `api/routes/cx_studio.py`

## Quality Bar

- `python3 -m pytest tests/ -x -q` must pass with more tests than current (1,339+)
- `cd web && npx tsc --noEmit` must pass
- `python3 -m pytest tests/test_dependency_layers.py -v` must pass (cx_studio is Layer 1)
- Commit and push to master when done

## When Done
Run: `openclaw system event --text "Done: CX Agent Studio integration — import, export, deploy, widget" --mode now`
