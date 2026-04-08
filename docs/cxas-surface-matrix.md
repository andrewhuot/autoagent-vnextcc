# CXAS Surface Matrix

This checklist treats the official Google Conversational Agents / Dialogflow CX docs as the source-of-truth inventory for the agent surfaces that matter to AgentLab portability.

Scope:

- Included: agent authoring and round-trip surfaces that a real imported CX Agent Studio agent depends on.
- Excluded: session runtime APIs, experiment execution APIs, changelog feeds, IAM setup, and other non-agent-control-plane docs.

Parity definitions:

- `supported`: live import, classification, editable workspace contract, and truthful write-back are all present for the surface we claim to support.
- `partial`: some real support exists, but live import, editable coverage, or write-back is incomplete.
- `read_only`: AgentLab can fetch and classify the surface, but not optimize or push it back.
- `unsupported`: the docs surface is known, but current code does not import it truthfully enough for real parity claims.

Current matrix summary:

- `supported`: instructions, model selection, webhooks
- `partial`: routing, transition route groups, versions
- `read_only`: flows/pages, workflow topology, intents, intent parameters, entity types, app tools, speech settings, playbook parameters, playbook handlers, playbook code blocks, page forms, generators, test cases, environments
- `unsupported`: callbacks, playbook examples

| Surface | Google docs source | Current parity | Current code evidence | Why |
| --- | --- | --- | --- | --- |
| Instructions | `projects.locations.agents.playbooks`, `projects.locations.agents` | `supported` | `adapters/cx_agent_mapper.py`, `cx_studio/exporter.py`, `cx_studio/surface_inventory.py` | Playbook instructions and fallback agent descriptions import into prompts and round-trip back today. |
| Model selection | `projects.locations.agents` | `supported` | `adapters/cx_agent_mapper.py`, `cx_studio/exporter.py`, `cx_studio/surface_inventory.py` | The active LLM model path in `generativeSettings.llmModelSettings.model` is imported and exported. |
| Webhooks | `projects.locations.agents.webhooks` | `supported` | `adapters/cx_studio_client.py`, `adapters/cx_agent_mapper.py`, `cx_studio/exporter.py` | URI, headers, timeout, and enabled state are mapped into AgentLab config and written back. |
| Routing | `projects.locations.agents.flows`, `projects.locations.agents.flows.pages`, `projects.locations.agents.intents` | `partial` | `adapters/cx_agent_mapper.py`, `cx_studio/exporter.py`, `cx_studio/surface_inventory.py` | Routes and intent cues become editable routing rules, but mapper write-back is still blocked. |
| Transition route groups | `projects.locations.agents.transitionRouteGroups`, `projects.locations.agents.flows` | `partial` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Current imports preserve route-group references embedded in flows/pages, but do not fetch the route-group resources. |
| Versions | `projects.locations.agents.environments`, `v3-overview` | `partial` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Environment version references are visible, but version resources themselves are not fetched or mutated. |
| Flows and pages | `projects.locations.agents.flows`, `projects.locations.agents.flows.pages` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/portability.py`, `cx_studio/surface_inventory.py` | Flow/page resources are fetched and persisted, but not represented as editable workspace structures. |
| Workflow topology | `projects.locations.agents.flows`, `projects.locations.agents.flows.pages` | `read_only` | `cx_studio/portability.py`, `cx_studio/surface_inventory.py` | The graph is reported for visibility, but structural edits are not part of the current round-trip contract. |
| Intents | `projects.locations.agents.intents` | `read_only` | `adapters/cx_studio_client.py`, `adapters/cx_agent_mapper.py`, `cx_studio/surface_inventory.py` | Training phrases are imported and used for routing hints, but not editable in AgentLab config. |
| Intent parameters | `projects.locations.agents.intents` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Intent parameter schemas are fetched, but the workspace contract does not expose them. |
| Entity types | `projects.locations.agents.entityTypes` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/exporter.py`, `cx_studio/surface_inventory.py` | Entity types are fetched and preserved, but there is no editable AgentLab surface for them yet. |
| App tools | `projects.locations.agents.tools` | `read_only` | `adapters/cx_studio_client.py`, `adapters/cx_agent_mapper.py`, `cx_studio/surface_inventory.py` | Tool resources are now discoverable and classifiable, but only a thin description survives into config and no write-back exists. |
| Speech settings | `projects.locations.agents` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | STT/TTS settings are fetched from the agent resource, but not editable in the workspace contract. |
| Playbook parameters | `projects.locations.agents.playbooks` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Input/output parameter definitions are imported for classification only. |
| Playbook handlers | `projects.locations.agents.playbooks` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Handlers are fetched and reported, but not editable or round-trippable today. |
| Playbook code blocks | `projects.locations.agents.playbooks` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Inline code blocks are preserved in the snapshot for visibility only. |
| Page forms | `projects.locations.agents.flows.pages` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Page forms are fetched into the snapshot, but not exposed as editable workspace fields. |
| Generators | `projects.locations.agents.generators` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Generator resources are fetched and classified, but not mapped into the shared callback contract or exporter. |
| Test cases | `projects.locations.agents.testCases` | `read_only` | `adapters/cx_agent_mapper.py`, `cx_studio/importer.py`, `cx_studio/surface_inventory.py` | Test cases become starter evals, but are not written back to CX. |
| Environments | `projects.locations.agents.environments` | `read_only` | `adapters/cx_studio_client.py`, `cx_studio/surface_inventory.py` | Environments are imported for deployment context, but not editable in the workspace contract. |
| Callbacks | `projects.locations.agents.generators` | `unsupported` | `cx_studio/portability.py`, `cx_studio/surface_inventory.py` | AgentLab does not currently map CX generator processors into the shared callback model. |
| Playbook examples | `projects.locations.agents.playbooks`, `v3-overview` | `unsupported` | `cx_studio/importer.py`, `cx_studio/surface_inventory.py` | The current client does not fetch the dedicated playbook examples resource, so real live imports cannot classify it truthfully. |
