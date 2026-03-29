# AutoAgent Assistant — "Manus for Agent Optimization"

## Vision

A conversational AI interface that makes the entire AutoAgent platform accessible through natural language. Users talk to the Assistant like they'd talk to a senior engineer: "Build me a customer support agent from these transcripts," "Why is my agent failing on billing questions?", "Fix it."

The Assistant orchestrates all existing modules (observer, optimizer, deployer, evals, blame map, mutations, search) under the hood. The 87 CLI commands and 131 API endpoints become invisible. Users just describe what they want.

**Inspiration:** Manus AI's conversational task interface — shows thinking, shows progress, delivers results in rich cards. Sierra Ghostwriter's "agent builds itself" UX. ChatGPT's conversational flow with tool use.

---

## Three Core Flows

### Flow 1: Build an Agent

**User says:** "I have 500 customer support transcripts. Build me an agent."

**Assistant does:**
1. Accepts file upload (transcripts as CSV/JSON/ZIP, PDFs, audio files, or raw text)
2. Ingests and analyzes transcripts:
   - Extract intents (billing, shipping, returns, technical support, etc.)
   - Extract entities (order IDs, product names, account numbers)
   - Identify routing patterns (which topics go where)
   - Discover edge cases and failure modes
   - Extract successful resolution patterns
   - Identify required tools (order lookup, refund processing, etc.)
3. Generates agent configuration:
   - Agent tree structure (orchestrator + specialists)
   - Routing rules based on discovered patterns
   - Instructions for each specialist agent
   - Tool definitions
   - Safety guardrails based on observed boundaries
   - Few-shot examples from best conversations
4. Presents the generated agent as a rich card:
   - Agent tree visualization
   - Routing logic summary
   - Specialist agent descriptions
   - Estimated coverage of discovered intents
5. User reviews and approves (or requests changes conversationally)
6. Saves config and runs baseline eval

**Alternative entry points:**
- "Build me a customer support agent for an e-commerce store" (guided, no transcripts)
- "Here's our SOP document, build an agent from it" (document-based)
- "Import my Dialogflow CX agent and optimize it" (existing agent)

### Flow 2: Iterate on an Agent

**User says:** "Billing questions are going to the wrong team"

**Assistant does:**
1. Runs diagnosis (observer → blame map → root cause analysis)
2. Presents findings in plain English:
   - "I found the issue: 40% of billing questions are routed to tech_support because your routing rules don't include keywords like 'invoice', 'refund', 'payment', or 'charge'."
   - Shows a blame cluster card with impact score
3. Proposes a fix:
   - "I can add 5 billing keywords to routing rules. Expected improvement: +19%. Confidence: high."
   - Shows a diff card (before/after)
   - Shows projected metrics card
4. User approves: "Fix it"
5. Runs gated eval → shows results → deploys if gates pass
6. Shows before/after card: "Success rate: 62% → 81%. Deployed."

**Other iteration examples:**
- "Make the agent more empathetic" → instruction mutation
- "Add a tool for checking order status" → tool mutation
- "The agent is too slow" → latency diagnosis → context pruning or model swap
- "Run an optimization cycle" → full optimizer loop with streaming progress
- "Show me what changed this week" → change history summary

### Flow 3: Explore Conversations

**User says:** "Why are customers angry about shipping?"

**Assistant does:**
1. Semantic search over conversation traces
2. Clusters results by root cause
3. Ranks by impact (frequency × severity × business impact)
4. Presents findings:
   - "I analyzed 2,340 conversations mentioning shipping. Found 3 root causes:"
   - Card 1: "Shipping delay in northeast (68% of complaints) — warehouse staffing issue"
   - Card 2: "Wrong tracking number provided (22%) — tool returning stale data"
   - Card 3: "Unclear delivery estimates (10%) — agent instruction too vague"
5. User can drill down: "Tell me more about the tracking number issue"
6. Shows specific conversation examples with highlighted failures
7. Offers to fix: "Want me to fix the tracking tool issue?"

**Other exploration examples:**
- "What are the top 5 failure modes this week?"
- "Compare this week to last week"
- "Show me conversations where the agent escalated unnecessarily"
- "What topics does my agent handle worst?"

---

## UX Design

### Chat Interface

The Assistant page is a full-width conversational interface (like ChatGPT or Manus):

```
┌─────────────────────────────────────────────────────────┐
│  🤖 AutoAgent Assistant                          [···]  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Welcome! I can help you build, optimize, and           │
│  debug AI agents. What would you like to do?            │
│                                                         │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────┐    │
│  │ 🏗️ Build    │ │ 🔧 Optimize  │ │ 🔍 Explore    │    │
│  │ New Agent   │ │ My Agent     │ │ Conversations  │    │
│  └─────────────┘ └──────────────┘ └───────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 📎 Upload files or type a message...            │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Rich Cards

The Assistant doesn't just return text — it renders rich interactive cards:

1. **Agent Preview Card** — tree visualization, specialist list, routing summary, coverage stats
2. **Diagnosis Card** — root cause, impact score, trend chart, affected conversations count
3. **Diff Card** — before/after with syntax highlighting, change description, risk level
4. **Metrics Card** — before/after scores, confidence interval, p-value, bar chart
5. **Conversation Card** — transcript with highlighted failure spans, grading
6. **Progress Card** — step-by-step progress (analyzing... found 3 issues... generating fix...) with collapsible details
7. **Deploy Card** — deployment status, canary progress, rollback button
8. **Cluster Card** — blame cluster with impact ranking, trend line, example conversations

### Thinking/Progress Display

Like Manus, the Assistant shows its work:

```
🤖 Analyzing your transcripts...

  ✓ Parsed 500 conversations
  ✓ Extracted 12 intents
  ✓ Identified 4 specialist domains
  ⏳ Generating routing rules...
  ○ Building agent configuration
  ○ Running baseline evaluation
```

Each step is collapsible — click to see details (e.g., the 12 extracted intents).

### Conversation Context

The Assistant maintains full conversation context:
- "Fix that" → refers to the last diagnosis
- "Try something else" → proposes alternative mutation
- "What about safety?" → adds safety eval to the current optimization
- "Go back" → reverts to previous state
- "Show me the diff again" → re-renders the last diff card

### File Upload

Support drag-and-drop or click-to-upload:
- Transcripts: CSV, JSON, JSONL, ZIP of text files
- Documents: PDF, DOCX, TXT (SOPs, playbooks, knowledge bases)
- Audio: MP3, WAV, M4A (transcribed via Whisper)
- Agent configs: YAML, JSON (existing agent definitions)

---

## Architecture

### Frontend

**New files:**
- `web/src/pages/Assistant.tsx` — main chat page (full-width, no sidebar by default)
- `web/src/components/assistant/ChatMessage.tsx` — message bubble with rich card rendering
- `web/src/components/assistant/AgentPreviewCard.tsx` — agent tree + specialists
- `web/src/components/assistant/DiagnosisCard.tsx` — root cause with impact
- `web/src/components/assistant/DiffCard.tsx` — before/after config diff
- `web/src/components/assistant/MetricsCard.tsx` — score comparison with charts
- `web/src/components/assistant/ConversationCard.tsx` — transcript with highlights
- `web/src/components/assistant/ProgressCard.tsx` — step-by-step with collapsible details
- `web/src/components/assistant/DeployCard.tsx` — deployment status
- `web/src/components/assistant/ClusterCard.tsx` — blame cluster visualization
- `web/src/components/assistant/FileUpload.tsx` — drag-and-drop upload
- `web/src/components/assistant/QuickActions.tsx` — suggested action buttons
- `web/src/lib/assistant-api.ts` — API hooks for assistant endpoints

**Styling:**
- Full-width layout (no sidebar) when on `/assistant`
- Clean, spacious chat bubbles
- Cards use the existing design system (light neutral, Inter font)
- Smooth animations for progress steps
- Code/diff blocks with syntax highlighting

### Backend

**New files:**
- `api/routes/assistant.py` — main assistant API endpoints
- `assistant/orchestrator.py` — NL intent classification → action routing
- `assistant/conversation.py` — conversation state management (context, history)
- `assistant/builder.py` — agent building from transcripts/docs/guided
- `assistant/explorer.py` — conversational exploration over traces
- `assistant/cards.py` — card data generation for rich responses
- `assistant/file_processor.py` — file upload handling (CSV, PDF, audio, etc.)
- `assistant/intent_extractor.py` — extract intents/entities from transcripts
- `assistant/agent_generator.py` — generate agent config from extracted data

**API Endpoints:**
- `POST /api/assistant/message` — send message, get response (streaming SSE)
- `POST /api/assistant/upload` — upload files for processing
- `GET /api/assistant/history` — get conversation history
- `DELETE /api/assistant/history` — clear conversation
- `GET /api/assistant/suggestions` — get contextual suggestions
- `POST /api/assistant/action/{action_id}` — execute a card action (approve fix, deploy, etc.)

**Streaming:**
The assistant streams responses via SSE (Server-Sent Events):
```
event: thinking
data: {"step": "Analyzing transcripts", "progress": 0.2}

event: thinking
data: {"step": "Found 12 intents", "progress": 0.4, "details": {...}}

event: card
data: {"type": "diagnosis", "data": {...}}

event: text
data: {"content": "I found 3 issues. The biggest one is..."}

event: card
data: {"type": "diff", "data": {...}}

event: text
data: {"content": "Want me to apply this fix?"}

event: suggestions
data: {"actions": ["Apply fix", "Show alternatives", "Explain more"]}
```

### Orchestrator Design

The orchestrator is the brain — it classifies intent and routes to the right module:

```python
class AssistantOrchestrator:
    """Routes NL messages to appropriate AutoAgent modules."""
    
    def __init__(self):
        self.conversation = ConversationState()
        self.builder = AgentBuilder()
        self.explorer = ConversationExplorer()
        # Existing modules
        self.observer = Observer()
        self.optimizer = Optimizer()
        self.deployer = Deployer()
        self.eval_runner = EvalRunner()
    
    async def handle_message(self, message: str, files: list = None) -> AsyncIterator[Event]:
        """Process a user message and yield response events."""
        
        # Classify intent
        intent = await self.classify_intent(message, self.conversation.context)
        
        # Route to handler
        match intent.action:
            case "build_agent":
                async for event in self.builder.build(message, files, self.conversation):
                    yield event
            case "diagnose":
                async for event in self.diagnose(message):
                    yield event
            case "fix" | "optimize":
                async for event in self.fix(message):
                    yield event
            case "explore":
                async for event in self.explorer.explore(message, self.conversation):
                    yield event
            case "deploy":
                async for event in self.deploy(message):
                    yield event
            case "explain":
                async for event in self.explain(message):
                    yield event
            case "status":
                async for event in self.status():
                    yield event
            case _:
                async for event in self.general_response(message):
                    yield event
        
        # Update conversation context
        self.conversation.add_turn(message, intent)
```

### Agent Builder Design

The builder is the most complex new module:

```python
class AgentBuilder:
    """Builds agent configurations from transcripts, documents, or guided conversation."""
    
    async def build_from_transcripts(self, transcripts: list[dict]) -> AsyncIterator[Event]:
        """Analyze transcripts and generate agent config."""
        
        yield ThinkingEvent("Parsing transcripts...")
        parsed = await self.parse_transcripts(transcripts)
        
        yield ThinkingEvent(f"Extracted {len(parsed.conversations)} conversations")
        
        # Extract intents
        yield ThinkingEvent("Extracting intents and entities...")
        intents = await self.extract_intents(parsed)
        yield ThinkingEvent(f"Found {len(intents)} intents", details=intents)
        
        # Identify routing patterns
        yield ThinkingEvent("Identifying routing patterns...")
        routing = await self.discover_routing(parsed, intents)
        
        # Extract resolution patterns from successful conversations
        yield ThinkingEvent("Learning from successful resolutions...")
        knowledge = await self.extract_knowledge(parsed)
        
        # Identify required tools
        yield ThinkingEvent("Identifying required tools...")
        tools = await self.discover_tools(parsed)
        
        # Generate agent tree
        yield ThinkingEvent("Generating agent configuration...")
        agent_config = await self.generate_config(
            intents=intents,
            routing=routing,
            knowledge=knowledge,
            tools=tools,
        )
        
        # Present preview
        yield CardEvent("agent_preview", agent_config.to_preview())
        yield TextEvent(
            f"I built a {len(agent_config.specialists)}-specialist agent "
            f"covering {len(intents)} intents with {len(tools)} tools. "
            f"Estimated coverage: {agent_config.coverage_pct}% of your transcripts."
        )
        yield SuggestionsEvent(["Looks good, save it", "Add more specialists", "Show routing logic", "Run baseline eval"])
    
    async def build_guided(self, domain: str, goal: str) -> AsyncIterator[Event]:
        """Build agent through guided conversation."""
        # Ask targeted questions based on domain
        # Generate synthetic training data
        # Build config iteratively
        ...
    
    async def build_from_documents(self, documents: list) -> AsyncIterator[Event]:
        """Build agent from SOP documents, knowledge bases."""
        # Parse documents (PDF, DOCX, TXT)
        # Extract procedures, policies, FAQ
        # Generate agent config with knowledge grounding
        ...
```

### Conversation Explorer Design

```python
class ConversationExplorer:
    """NL queries over conversation traces with clustering and impact ranking."""
    
    async def explore(self, query: str, conversation: ConversationState) -> AsyncIterator[Event]:
        """Search and analyze conversations based on NL query."""
        
        yield ThinkingEvent("Searching conversations...")
        
        # Semantic search over traces
        results = await self.semantic_search(query)
        yield ThinkingEvent(f"Found {len(results)} matching conversations")
        
        # Cluster by root cause
        yield ThinkingEvent("Clustering by root cause...")
        clusters = await self.cluster_results(results)
        
        # Rank by impact
        ranked = self.rank_by_impact(clusters)
        
        # Present findings
        yield TextEvent(
            f"I analyzed {len(results)} conversations matching '{query}'. "
            f"Found {len(ranked)} root causes:"
        )
        
        for i, cluster in enumerate(ranked[:5], 1):
            yield CardEvent("cluster", {
                "rank": i,
                "title": cluster.title,
                "description": cluster.description,
                "count": cluster.conversation_count,
                "impact": cluster.impact_score,
                "trend": cluster.trend,  # "increasing", "stable", "decreasing"
                "example_ids": cluster.example_conversation_ids[:3],
            })
        
        yield SuggestionsEvent([
            f"Tell me more about '{ranked[0].title}'",
            "Fix the top issue",
            "Compare to last week",
            "Show example conversations",
        ])
```

---

## Integration with Existing Modules

The Assistant is an orchestration layer — it calls existing modules, not replaces them:

| User Intent | Module Called | Existing Code |
|---|---|---|
| "Why is my agent failing?" | Observer → Blame Map | `observer/opportunities.py`, `observer/blame_map.py` |
| "Fix the routing issue" | Optimizer → Search → Eval → Deploy | `optimizer/loop.py`, `optimizer/search.py`, `evals/runner.py` |
| "Run an eval" | Eval Runner | `evals/runner.py` |
| "Deploy this change" | Deployer | `optimizer/deployer.py` |
| "Show me the diff" | Change Card | `optimizer/change_card.py` |
| "What changed this week?" | Experiment History | `optimizer/experiments.py` |
| "Check agent health" | Observer Report | `observer/observer.py` |
| "Undo the last change" | Deployer Rollback | `optimizer/deployer.py` |
| "Show me traces" | Trace Store | `observer/traces.py` |
| "Calibrate the judge" | Judge Ops | `judges/` |

The builder module is NEW — it doesn't exist yet:

| User Intent | New Module | New Code |
|---|---|---|
| "Build agent from transcripts" | Builder | `assistant/builder.py`, `assistant/intent_extractor.py`, `assistant/agent_generator.py` |
| "Build agent from SOP docs" | Builder | `assistant/builder.py`, `assistant/file_processor.py` |
| "Explore conversations" | Explorer | `assistant/explorer.py` (uses existing trace store) |

---

## Testing Strategy

### Unit Tests
- `tests/test_assistant_orchestrator.py` — intent classification, routing
- `tests/test_assistant_builder.py` — transcript parsing, intent extraction, config generation
- `tests/test_assistant_explorer.py` — semantic search, clustering, impact ranking
- `tests/test_assistant_conversation.py` — context management, turn tracking
- `tests/test_assistant_cards.py` — card data generation
- `tests/test_assistant_file_processor.py` — file upload handling

### Integration Tests
- `tests/test_assistant_build_flow.py` — full build flow from transcripts to config
- `tests/test_assistant_diagnose_flow.py` — full diagnose → fix → deploy flow
- `tests/test_assistant_explore_flow.py` — full explore → drill down → fix flow

### Target: 50+ new tests, maintain existing 1,825+

---

## Success Metrics

1. **Time to first agent**: < 3 minutes from transcript upload to baseline eval
2. **Time to first fix**: < 60 seconds from "why is it failing?" to deployed fix
3. **Conversation depth**: Users average 5+ turns per session (not bouncing after 1)
4. **Feature coverage**: Assistant can access 80%+ of AutoAgent's capabilities via NL

---

## Implementation Priority

1. **Core chat infrastructure** — message handling, SSE streaming, conversation state
2. **Diagnose + Fix flow** — highest immediate value, uses existing modules
3. **Explore flow** — semantic search, clustering, NL queries
4. **Build from transcripts** — most complex, highest Sierra-competitive value
5. **Build guided** — simpler, good for users without transcripts
6. **Rich cards** — iteratively improve card designs
7. **File upload** — PDF, audio, document processing

---

## Non-Goals (for this build)

- Voice input/output (future)
- Multi-user collaboration (future)
- Real-time agent monitoring in chat (future)
- Mobile-optimized layout (future)
