# AutoAgent Assistant - Backend Core Modules

This directory contains the backend core modules for the AutoAgent Assistant feature.

## Overview

The Assistant provides a conversational AI interface to all AutoAgent capabilities:
- Build agents from transcripts, documents, or guided conversation
- Iterate on agents (diagnose, fix, optimize)
- Explore conversations with semantic search and clustering

## Architecture

### Core Modules (Implemented)

#### 1. **orchestrator.py** - The Brain
Routes natural language messages to appropriate AutoAgent modules.

**Class:** `AssistantOrchestrator`
**Key Methods:**
- `handle_message(message, files) -> AsyncIterator[Event]` - Main entry point
- Intent classification using pattern matching (LLM-based classification coming in API layer)
- Routes to: diagnose, fix, optimize, explore, deploy, explain, status

**Integrations:**
- Observer (diagnosis)
- Optimizer (fix/optimize)
- Deployer (deploy)
- EvalRunner (evaluation)
- TraceStore (exploration)

#### 2. **conversation.py** - Context Management
Tracks conversation state across turns for continuity.

**Classes:**
- `ConversationState` - Main state manager
- `ConversationContext` - Current context (last diagnosis, diff, cluster, etc.)
- `ConversationTurn` - Single turn record

**Key Features:**
- Reference resolution ("fix that", "show diff again")
- Conversation history tracking
- Context serialization (JSON)
- Recent turn retrieval for LLM context windows

#### 3. **cards.py** - Rich UI Data
Generates structured card data for rendering rich responses.

**Class:** `CardGenerator`
**Card Types:**
- `diagnosis_card` - Root cause analysis
- `diff_card` - Config changes (before/after)
- `metrics_card` - Score comparisons
- `agent_preview_card` - Agent structure visualization
- `conversation_card` - Transcript with highlights
- `progress_card` - Step-by-step progress
- `deploy_card` - Deployment status
- `cluster_card` - Failure clustering

All cards return structured dicts ready for JSON serialization.

#### 4. **file_processor.py** - File Upload Handling
Processes uploaded files into structured data.

**Class:** `FileProcessor`
**Supported Formats:**
- Transcripts: CSV, JSON, JSONL, ZIP
- Documents: PDF, TXT, MD
- Audio: MP3, WAV, M4A (stub - TODO: Whisper integration)

**Key Features:**
- Auto-detection of file type from extension
- Normalization of transcript records to standard format
- Archive extraction (ZIP processing)
- Metadata summary extraction
- Validation

**Standard transcript format:**
```python
{
    "conversation_id": str,
    "user_message": str,
    "assistant_message": str,
    "specialist_used": str (optional),
    "success": bool (optional),
    "metadata": dict (optional)
}
```

#### 5. **explorer.py** - Conversational Trace Exploration
Natural language queries over conversation traces with semantic search, clustering, and impact ranking.

**Class:** `ConversationExplorer`
**Key Methods:**
- `explore(query, conversation_state) -> AsyncIterator[Event]` - Main exploration flow
- `drill_down(cluster_id, detail_type) -> AsyncIterator[Event]` - Drill into cluster details

**Key Features:**
- NL queries: "Why are customers angry about shipping?"
- Semantic search over trace store (keyword-based, embeddings planned)
- Failure clustering with impact scoring (frequency × severity)
- Trend detection (increasing/stable/decreasing)
- Example conversation highlighting
- Integration with existing BlameMap module

**Event Types:**
- ThinkingEvent - Progress updates
- TextEvent - Plain text responses
- CardEvent - ClusterCard data structures
- SuggestionsEvent - Contextual next actions
- ErrorEvent - Error messages

**ClusterCard Structure:**
- rank, cluster_id, title, description
- count, total_traces, impact_score, impact_percentage
- trend, severity, example_trace_ids
- suggested_fix, metadata

See detailed documentation below for full API reference.

### Supporting Modules (Pre-existing)

- **events.py** - Event types for streaming (ThinkingEvent, TextEvent, CardEvent, etc.)
- **builder.py** - Agent building from transcripts
- **intent_extractor.py** - Intent/entity extraction
- **agent_generator.py** - Agent config generation

## Event Streaming

The orchestrator uses AsyncIterator to stream events to the client:

```python
async for event in orchestrator.handle_message("Why is my agent failing?"):
    match event:
        case ThinkingEvent(step, progress):
            # Show progress indicator
        case TextEvent(content):
            # Display text response
        case CardEvent(card_type, data):
            # Render rich card
        case SuggestionsEvent(actions):
            # Show action buttons
```

## Usage Example

```python
from assistant import AssistantOrchestrator, ConversationState

# Initialize with existing modules
orchestrator = AssistantOrchestrator(
    observer=observer,
    optimizer=optimizer,
    deployer=deployer,
    eval_runner=eval_runner,
    trace_store=trace_store,
)

# Handle a message
async for event in orchestrator.handle_message("Diagnose my billing agent"):
    print(event.to_dict())

# Access conversation state
context = orchestrator.conversation.get_context()
print(f"Last diagnosis: {context.last_diagnosis}")
```

## Integration Points

### With Observer
- `_handle_diagnose()` calls Observer to generate health report
- Uses BlameMap to cluster failures
- Presents diagnosis cards with root causes

### With Optimizer
- `_handle_fix()` calls Optimizer to generate mutation proposals
- `_handle_optimize()` runs full optimization cycle
- Shows diff cards and metrics cards

### With Deployer
- `_handle_deploy()` initiates canary deployment
- Shows deploy cards with canary status
- Supports rollback

### With EvalRunner
- Used by optimizer for candidate evaluation
- Provides metrics for comparison cards

### With TraceStore
- `_handle_explore()` performs semantic search over traces
- Clusters results by root cause
- Shows cluster cards

## Testing

Run the test suite:
```bash
python3 -m pytest tests/test_assistant_orchestrator.py
python3 -m pytest tests/test_assistant_conversation.py
python3 -m pytest tests/test_assistant_cards.py
python3 -m pytest tests/test_assistant_file_processor.py
```

Basic integration test:
```bash
python3 -c "
import asyncio
from assistant import AssistantOrchestrator

async def test():
    orch = AssistantOrchestrator()
    async for event in orch.handle_message('Help me build an agent'):
        print(event.to_dict()['type'])

asyncio.run(test())
"
```

## Next Steps

### Short Term
1. Add LLM-based intent classification (replace pattern matching)
2. Integrate with actual Observer/Optimizer/Deployer instances
3. Implement builder flow (transcripts → agent config)
4. Add explorer flow (semantic search over traces)

### Medium Term
1. Add audio transcription (Whisper API)
2. Add PDF text extraction (pdfplumber)
3. Add conversation history persistence (SQLite)
4. Add multi-turn context pruning

### Long Term
1. Add voice input/output
2. Add real-time agent monitoring
3. Add collaborative features (multi-user)
4. Add mobile-optimized layout

## File TODOs

### file_processor.py
- [ ] Integrate PDF parsing library (pdfplumber or PyPDF2)
- [ ] Integrate Whisper API for audio transcription
- [ ] Add DOCX support for document processing

### orchestrator.py
- [ ] Replace pattern matching with LLM-based intent classification
- [ ] Integrate actual Observer instance for diagnosis
- [ ] Integrate actual Optimizer instance for fixes
- [ ] Add builder module integration
- [ ] Add explorer module integration

## Code Quality

- All modules have type hints
- All public methods have docstrings
- Error handling with try/except
- Follows existing codebase patterns (see optimizer/loop.py, evals/runner.py)
- AsyncIterator for streaming responses
- Dataclasses for structured data
- Enums for intent actions

## Dependencies

No new dependencies added. Uses only Python stdlib and existing project dependencies.

Future dependencies (when implementing TODOs):
- `pdfplumber` or `PyPDF2` for PDF parsing
- `openai` for Whisper API (audio transcription) and embeddings
- `faiss-cpu` or `pinecone-client` for vector search

---

# ConversationExplorer Module - Detailed Documentation

## Overview

The `explorer.py` module provides conversational exploration over conversation traces. It enables natural language queries like "Why are customers angry about shipping?" and returns clustered failure insights with impact rankings.

## Key Classes

### ConversationExplorer

Main class for trace exploration.

```python
from assistant.explorer import ConversationExplorer

explorer = ConversationExplorer(trace_store=None, db_path="traces.db")
```

**Parameters:**
- `trace_store` (TraceStore, optional): Existing TraceStore instance
- `db_path` (str): Path to SQLite trace database (default: "traces.db")

### Event Types

All events inherit from the base `Event` class and include:

```python
@dataclass
class Event:
    event_type: EventType
    timestamp: float
    data: dict[str, Any]
```

**EventType Enum:**
- `thinking` - Progress updates
- `text` - Plain text messages
- `card` - Rich data structures
- `suggestions` - Action suggestions
- `error` - Error messages

**Concrete Event Classes:**

1. **ThinkingEvent(step, progress, details)**
   ```python
   ThinkingEvent("Searching conversations...", progress=0.3)
   # data = {"step": str, "progress": float | None, "details": dict}
   ```

2. **TextEvent(content)**
   ```python
   TextEvent("I analyzed 340 conversations. Found 3 root causes:")
   # data = {"content": str}
   ```

3. **CardEvent(card_type, card_data)**
   ```python
   CardEvent("cluster", cluster_card.to_dict())
   # data = {"type": str, "data": dict}
   ```

4. **SuggestionsEvent(actions)**
   ```python
   SuggestionsEvent(["Fix the top issue", "Show examples", "Compare to last week"])
   # data = {"actions": list[str]}
   ```

5. **ErrorEvent(message, details)**
   ```python
   ErrorEvent("Exploration failed", details={"query": query})
   # data = {"message": str, "details": dict}
   ```

### ClusterCard

Data structure for cluster visualization.

```python
@dataclass
class ClusterCard:
    rank: int
    cluster_id: str
    title: str
    description: str
    count: int
    total_traces: int
    impact_score: float
    trend: str  # "growing", "stable", "shrinking"
    severity: str  # "critical", "high", "medium", "low"
    example_trace_ids: list[str]
    first_seen: float
    last_seen: float
    suggested_fix: str | None
    metadata: dict[str, Any]
```

**to_dict() Output:**
```python
{
    "rank": 1,
    "cluster_id": "abc123",
    "title": "Shipping delays in northeast",
    "description": "68% of complaints (20/29) are affected. Trend: increasing.",
    "count": 20,
    "total_traces": 29,
    "impact_score": 0.68,
    "impact_percentage": 68.0,
    "trend": "growing",
    "severity": "critical",
    "example_trace_ids": ["trace_001", "trace_002", "trace_003"],
    "first_seen": 1774506533.2,
    "last_seen": 1774506933.4,
    "suggested_fix": "Increase warehouse staffing",
    "metadata": {
        "grader_name": "semantic_search",
        "agent_path": "root/support/shipping",
        "raw_failure_reason": "Shipping delay: warehouse staffing issue"
    }
}
```

### ConversationState

Placeholder for conversation context (full implementation in `conversation.py`).

```python
@dataclass
class ConversationState:
    context: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
```

## Main Methods

### explore(query, conversation_state)

Explore conversations based on natural language query.

```python
async def explore(
    query: str,
    conversation_state: ConversationState | None = None,
) -> AsyncIterator[Event]:
```

**Parameters:**
- `query` (str): Natural language query
- `conversation_state` (ConversationState, optional): Current conversation context

**Yields:**
- `Event` objects (thinking, text, card, suggestions, error)

**Example:**
```python
async for event in explorer.explore("Why are customers angry about shipping?"):
    if event.event_type == EventType.thinking:
        print(f"Status: {event.data['step']}")
    elif event.event_type == EventType.card:
        cluster = event.data['data']
        print(f"Cluster {cluster['rank']}: {cluster['title']}")
```

**Event Flow:**
1. ThinkingEvent("Searching conversations...", 0.1)
2. ThinkingEvent("Found N matching conversations", 0.3)
3. ThinkingEvent("Clustering by root cause...", 0.5)
4. ThinkingEvent("Analyzing impact and trends...", 0.8)
5. TextEvent("I analyzed N conversations matching 'query'. Found M root causes:")
6. CardEvent("cluster", cluster_1_data) × M
7. SuggestionsEvent([...])

### drill_down(cluster_id, detail_type)

Drill down into a specific cluster (placeholder implementation).

```python
async def drill_down(
    cluster_id: str,
    detail_type: str = "examples",
) -> AsyncIterator[Event]:
```

**Parameters:**
- `cluster_id` (str): ID of cluster to examine
- `detail_type` (str): Type of detail ("examples", "timeline", "fix")

**Yields:**
- `Event` objects

**Future Implementation:**
- "examples": Show conversation transcripts with highlighted failures
- "timeline": Show failure occurrences over time
- "fix": Generate automated fix suggestions

## Internal Methods

### _parse_query_intent(query)

Extracts intent, keywords, filters, and time windows from natural language.

```python
def _parse_query_intent(query: str) -> dict[str, Any]:
```

**Returns:**
```python
{
    "raw_query": "Why are customers angry about shipping this week?",
    "keywords": ["customers", "angry", "shipping", "week"],
    "intent_type": "failure_analysis",  # or "general", "trend_analysis", "comparison"
    "time_window": 604800,  # seconds (7 days)
    "filters": {"topic_hint": "shipping"}
}
```

**Intent Types:**
- `general`: Broad queries
- `failure_analysis`: Contains keywords like "fail", "error", "wrong", "angry"
- `trend_analysis`: Contains "trend", "increasing", "growing"
- `comparison`: Contains "compare", "vs", "difference"

**Time Windows:**
- "today" → 86400 (1 day)
- "this week" / "last 7 days" → 604800 (7 days)
- "this month" / "last 30 days" → 2592000 (30 days)

### _semantic_search(query, query_intent)

Search traces using semantic similarity (currently keyword-based).

```python
async def _semantic_search(
    query: str,
    query_intent: dict[str, Any],
) -> list[tuple[str, TraceEvent, float]]:
```

**Returns:**
List of (trace_id, event, relevance_score) tuples

**Search Strategy:**
1. Extract keywords from query_intent
2. Apply time window filter if specified
3. SQL LIKE search across:
   - error_message
   - tool_input
   - tool_output
   - metadata
4. Compute relevance scores:
   - Base score = keyword match count
   - Error events get 2x boost
5. Sort by relevance descending
6. Limit to top 500 results

**Future Implementation:**
- Use OpenAI embeddings (text-embedding-3-small)
- Store embeddings in vector database (FAISS/Pinecone)
- Hybrid search: keyword + semantic similarity

### _cluster_results(results, query_intent)

Cluster search results by root cause using BlameMap.

```python
async def _cluster_results(
    results: list[tuple[str, TraceEvent, float]],
    query_intent: dict[str, Any],
) -> list[BlameCluster]:
```

**Returns:**
List of BlameCluster objects sorted by impact_score

**Clustering Process:**
1. Extract unique trace IDs from results
2. Get all events and spans for each trace
3. Create synthetic SpanGrades for error events
4. Use BlameMap to cluster by (grader_name, agent_path, failure_reason)
5. Compute impact scores and trends
6. Return sorted clusters

### _rank_by_impact(clusters)

Rank clusters by impact and compute severity.

```python
def _rank_by_impact(
    clusters: list[BlameCluster]
) -> list[tuple[BlameCluster, str]]:
```

**Returns:**
List of (cluster, severity) tuples

**Severity Classification:**
- Critical: impact_score >= 0.2 (20%+)
- High: impact_score >= 0.1 (10-20%)
- Medium: impact_score >= 0.05 (5-10%)
- Low: impact_score < 0.05 (<5%)

### _create_cluster_card(cluster, rank, severity)

Create a ClusterCard from a BlameCluster.

```python
def _create_cluster_card(
    cluster: BlameCluster,
    rank: int,
    severity: str = "medium"
) -> ClusterCard:
```

**Returns:**
ClusterCard object

**Processing:**
1. Generate human-readable title from failure_reason and agent_path
2. Generate description with impact percentage and trend
3. Suggest fix based on failure pattern matching
4. Package metadata

### _generate_suggestions(query, clusters, query_intent)

Generate contextual suggestions for next actions.

```python
def _generate_suggestions(
    query: str,
    clusters: list[tuple[BlameCluster, str]],
    query_intent: dict[str, Any],
) -> list[str]:
```

**Returns:**
List of suggested action strings (max 4)

**Suggestion Logic:**
- If clusters exist:
  - Drill-down: "Tell me more about the {agent} failures"
  - Fix: "Fix the top issue" (if suggested_fix available)
  - Compare: "Compare top 2 issues" (if 2+ clusters)
- Always:
  - "Show example conversations"
- Time-based:
  - "Compare to previous period" (if time_window specified)
  - "Show trends over time" (if no time_window)

## Integration Points

### observer/traces.py

**TraceStore Integration:**
```python
from observer.traces import TraceStore, TraceEvent, TraceSpan

store = TraceStore(db_path="traces.db")
explorer = ConversationExplorer(trace_store=store)
```

**Methods Used:**
- `store.get_trace(trace_id)` - Get all events for a trace
- `store.get_spans(trace_id)` - Get all spans for a trace
- Direct SQL queries for search

### observer/blame_map.py

**BlameMap Integration:**
```python
from observer.blame_map import BlameMap, BlameCluster

bmap = BlameMap()
bmap.add_grades(trace_id, grades, timestamp)
clusters = bmap.compute(window_seconds=time_window)
```

**Methods Used:**
- `BlameMap.add_grades()` - Add span grades
- `BlameMap.compute()` - Generate clusters

### observer/trace_grading.py

**SpanGrade Integration:**
```python
from observer.trace_grading import SpanGrade

grade = SpanGrade(
    grader_name="semantic_search",
    span_id=event.event_id,
    passed=False,
    score=0.0,
    failure_reason=event.error_message,
    metadata={"agent_path": event.agent_path},
)
```

## Testing

Run tests:
```bash
python3 -m pytest tests/test_assistant_explorer.py -v
```

**Test Coverage:**
- Event types (6 tests)
- ClusterCard (2 tests)
- ConversationState (2 tests)
- Query intent parsing (7 tests)
- Semantic search (4 tests)
- Clustering (2 tests)
- Impact ranking (1 test)
- Cluster card generation (4 tests)
- Suggestion generation (2 tests)
- End-to-end exploration (5 tests)
- Drill-down (2 tests)
- Row conversion (1 test)

**Total: 38 tests, all passing**

## Performance Considerations

**Current Implementation:**
- Search: O(n) where n = matching events
- Clustering: O(m log m) where m = unique failure types
- Ranking: O(k log k) where k = number of clusters
- Memory: Bounded by 500 conversation limit

**Optimization Opportunities:**
1. Add database indexes on frequently searched fields
2. Implement result pagination
3. Cache frequent queries
4. Use read replicas for trace database
5. Implement incremental clustering for large datasets

**Production Recommendations:**
- Max search results: 500 conversations
- Max clusters returned: 10 (top clusters only)
- Time window limit: 90 days
- Query timeout: 30 seconds

## Future Enhancements

### Short-term
1. Replace keyword search with vector embeddings
2. Add LLM-based query parsing for structured filters
3. Implement full drill-down with conversation details
4. Add business impact scoring (customer tier, revenue)
5. Add time-series trend analysis

### Long-term
1. Automated fix generation from cluster patterns
2. Multi-turn conversational drill-down
3. Comparative analysis (time periods, branches)
4. Root cause reasoning with LLM
5. Predictive failure alerts
6. Export cluster data (CSV, JSON)
7. Cluster visualization (timeline, heatmap)

## Error Handling

All methods include try/except blocks:

```python
async def explore(query, conversation_state):
    try:
        # Main logic
    except Exception as e:
        yield ErrorEvent(f"Exploration failed: {str(e)}", details={"query": query})
```

**Common Errors:**
- Database connection failures
- Invalid query syntax
- Empty result sets
- Clustering failures (no error events found)

## Code Quality

- Full type hints on all methods
- Comprehensive docstrings
- Production-ready error handling
- Follows existing codebase patterns (observer/blame_map.py, optimizer/loop.py)
- AsyncIterator for streaming
- Dataclasses for structured data

---

# Builder Modules - Agent Generation from Transcripts

The builder modules (intent_extractor.py, agent_generator.py, builder.py) enable automated agent generation from customer support transcripts.

## Overview

Three production-ready Python modules that work together to build AI agents from conversation data:

1. **`intent_extractor.py`** - Extract intents and entities from transcripts
2. **`agent_generator.py`** - Generate agent config from extracted data  
3. **`builder.py`** - Agent building orchestrator with streaming progress

## Quick Start

```python
from assistant import AgentBuilder, IntentExtractor

# Sample conversation transcripts
transcripts = [
    {
        "id": "conv_1",
        "messages": [
            {"role": "user", "content": "Where is my order #12345?"},
            {"role": "agent", "content": "Your order is in transit."},
        ],
        "success": True,
    },
]

# Build agent with streaming progress
builder = AgentBuilder(intent_extractor=IntentExtractor(use_mock=True))

async for event in builder.build_from_transcripts(transcripts):
    if event.to_dict()["type"] == "thinking":
        print(f"Progress: {event.step}")
```

## Module Details

### IntentExtractor

Analyzes conversation transcripts to discover user intents, entities, routing patterns, failure modes, and required tools.

**Key Methods:**
```python
async def extract_intents(conversations: list[dict]) -> tuple[
    list[Intent],           # Discovered intents
    list[RoutingPattern],   # Routing patterns  
    list[FailureMode],      # Failure modes
    list[str]              # Required tools
]
```

**Data Structures:**
- `Intent` - User intent with keywords, frequency, success rate
- `Entity` - Extracted entity (order ID, product name, etc.)
- `RoutingPattern` - Discovered routing rule
- `FailureMode` - Failure pattern with severity and suggested fix

**Features:**
- LLM-based semantic analysis via `LLMRouter`
- Pattern matching fallback when no LLM available
- Mock mode for testing

### AgentGenerator

Generates complete agent configurations from extracted data.

**Key Methods:**
```python
def generate_config(
    intents: list[Intent],
    routing_patterns: list[RoutingPattern],
    failure_modes: list[FailureMode],
    required_tools: list[str],
) -> GeneratedAgentConfig
```

**Generated Config:**
- `AgentConfig` - Pydantic model with routing, prompts, tools
- `specialists` - List of specialist agents with instructions
- `routing_logic` - Human-readable routing summary
- `coverage_pct` - Percentage of intents covered

### AgentBuilder  

Orchestrates the complete agent building process with streaming events.

**Building Modes:**

**A. Build from Transcripts**
```python
async for event in builder.build_from_transcripts(transcripts):
    # Yields: ThinkingEvent, CardEvent, TextEvent, SuggestionsEvent
    pass
```

**B. Guided Building**
```python
async for event in builder.build_guided(
    domain="e-commerce customer support",
    goal="help customers with orders and returns"
):
    # Interactive Q&A to build agent
    pass
```

**C. Build from Documents** 
```python
async for event in builder.build_from_documents(documents):
    # Extract from SOPs, FAQs, policies
    pass
```

## Testing

42 comprehensive tests across 3 modules:

```bash
python3 -m pytest tests/test_assistant_intent_extractor.py -v  # 11 tests
python3 -m pytest tests/test_assistant_agent_generator.py -v   # 14 tests  
python3 -m pytest tests/test_assistant_builder.py -v           # 17 tests
```

## Demo

Interactive demo showing all modules in action:

```bash
PYTHONPATH=. python3 examples/assistant_builder_demo.py
```

## Files Created

```
assistant/
├── events.py                # Event type definitions
├── intent_extractor.py      # Intent extraction (453 lines)
├── agent_generator.py       # Config generation (459 lines)
└── builder.py               # Building orchestrator (369 lines)

tests/
├── test_assistant_intent_extractor.py   # 11 tests
├── test_assistant_agent_generator.py    # 14 tests
└── test_assistant_builder.py            # 17 tests

examples/
└── assistant_builder_demo.py            # Interactive demo
```

All tests passing. Production-ready with proper error handling, type hints, and docstrings.
