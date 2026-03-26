# Assistant API Documentation

The Assistant API provides a conversational AI interface to the AutoAgent platform. Users can interact with the assistant via natural language to build, optimize, and debug AI agents.

## Base URL

```
/api/assistant
```

## Authentication

Currently no authentication required (development mode).

## Endpoints

### 1. Send Message (SSE Streaming)

Send a message to the assistant and receive a streaming response via Server-Sent Events.

**Endpoint:** `POST /api/assistant/message`

**Request Body:**
```json
{
  "message": "Build me a customer support agent",
  "session_id": "optional-session-uuid",
  "context": {
    "agent_id": "optional-context-data"
  }
}
```

**Response:** Server-Sent Events (SSE) stream

**Event Types:**

1. **thinking** - Progress updates
```
event: thinking
data: {"step": "Analyzing transcripts...", "progress": 0.3}
```

2. **card** - Rich data cards
```
event: card
data: {
  "type": "diagnosis",
  "data": {
    "root_cause": "Routing error",
    "impact_score": 0.82,
    "affected_conversations": 156
  }
}
```

Card types:
- `agent_preview` - Agent configuration preview
- `diagnosis` - Root cause analysis
- `diff` - Before/after configuration diff
- `metrics` - Performance metrics comparison
- `cluster` - Failure cluster visualization
- `conversation` - Example conversation transcript
- `progress` - Multi-step progress tracker
- `deploy` - Deployment status

3. **text** - Assistant text response
```
event: text
data: {"content": "I found 3 issues with your agent..."}
```

4. **suggestions** - Contextual action suggestions
```
event: suggestions
data: {"actions": ["Apply fix", "Show alternatives", "Explain more"]}
```

5. **error** - Error message
```
event: error
data: {"message": "Error processing message", "type": "internal_error"}
```

**Response Headers:**
- `Content-Type: text/event-stream`
- `X-Session-ID: {session-id}` - Session identifier for continuity

**Example curl:**
```bash
curl -N -X POST http://localhost:8000/api/assistant/message \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"message": "Why is my agent failing?"}'
```

**Example JavaScript:**
```javascript
const eventSource = new EventSource('/api/assistant/message', {
  method: 'POST',
  body: JSON.stringify({ message: 'Build an agent' })
});

eventSource.addEventListener('thinking', (e) => {
  const data = JSON.parse(e.data);
  console.log('Thinking:', data.step, data.progress);
});

eventSource.addEventListener('card', (e) => {
  const data = JSON.parse(e.data);
  renderCard(data.type, data.data);
});

eventSource.addEventListener('text', (e) => {
  const data = JSON.parse(e.data);
  console.log('Assistant:', data.content);
});

eventSource.addEventListener('suggestions', (e) => {
  const data = JSON.parse(e.data);
  showSuggestions(data.actions);
});
```

---

### 2. Upload Files

Upload files for processing by the assistant.

**Endpoint:** `POST /api/assistant/upload`

**Request:** `multipart/form-data`

**Form Fields:**
- `files` - One or more files (required)
- `session_id` - Session identifier (optional)
- `description` - Description of files (optional)

**Supported File Types:**
- Transcripts: `.csv`, `.json`, `.jsonl`, `.zip`
- Documents: `.pdf`, `.docx`, `.txt`
- Audio: `.mp3`, `.wav`, `.m4a`
- Configs: `.yaml`, `.yml`

**File Size Limit:** 50MB per file

**Response:**
```json
{
  "success": true,
  "session_id": "uuid",
  "files": [
    {
      "file_id": "uuid",
      "filename": "transcripts.csv",
      "extension": ".csv",
      "size_bytes": 12345,
      "content_type": "text/csv"
    }
  ],
  "total_files": 1,
  "message": "Uploaded 1 file(s). Use the message endpoint to process them."
}
```

**Example curl:**
```bash
curl -X POST http://localhost:8000/api/assistant/upload \
  -F "files=@transcripts.csv" \
  -F "files=@config.yaml" \
  -F "session_id=existing-session-uuid" \
  -F "description=Customer support transcripts"
```

---

### 3. Get Conversation History

Retrieve the full conversation history for a session.

**Endpoint:** `GET /api/assistant/history`

**Query Parameters:**
- `session_id` (required) - Session identifier

**Response:**
```json
{
  "session_id": "uuid",
  "turns": [
    {
      "turn_id": "uuid",
      "user_message": "Build me an agent",
      "assistant_response": [
        {"event": "thinking", "data": {...}},
        {"event": "card", "data": {...}},
        {"event": "text", "data": {...}}
      ],
      "timestamp": 1234567890.123,
      "session_id": "uuid"
    }
  ],
  "total": 1
}
```

**Example curl:**
```bash
curl "http://localhost:8000/api/assistant/history?session_id=your-session-id"
```

---

### 4. Clear Conversation History

Delete the conversation history for a session.

**Endpoint:** `DELETE /api/assistant/history`

**Query Parameters:**
- `session_id` (required) - Session identifier

**Response:**
```json
{
  "success": true,
  "session_id": "uuid",
  "message": "Conversation history cleared"
}
```

**Example curl:**
```bash
curl -X DELETE "http://localhost:8000/api/assistant/history?session_id=your-session-id"
```

---

### 5. Get Contextual Suggestions

Get suggested next actions based on conversation state.

**Endpoint:** `GET /api/assistant/suggestions`

**Query Parameters:**
- `session_id` (required) - Session identifier

**Response:**
```json
{
  "session_id": "uuid",
  "suggestions": [
    "Build a new agent",
    "Optimize my agent",
    "Diagnose issues"
  ],
  "quick_actions": [
    {"label": "Build Agent", "action": "build", "icon": "🏗️"},
    {"label": "Optimize", "action": "optimize", "icon": "🔧"}
  ]
}
```

**Example curl:**
```bash
curl "http://localhost:8000/api/assistant/suggestions?session_id=your-session-id"
```

---

### 6. Execute Card Action

Execute an interactive action from a card (approve fix, deploy, etc.).

**Endpoint:** `POST /api/assistant/action/{action_id}`

**Path Parameters:**
- `action_id` - Action identifier

**Supported Actions:**
- `approve_fix` - Apply proposed configuration change
- `deploy` - Deploy tested change to production
- `rollback` - Revert deployed change
- `show_examples` - Display example conversations
- `run_eval` - Run evaluation on current config

**Request Body:**
```json
{
  "session_id": "uuid",
  "action_data": {
    "optional": "action-specific data"
  }
}
```

**Response:**
```json
{
  "success": true,
  "action_id": "approve_fix",
  "result": {
    "applied": true,
    "description": "Applied routing rule fix",
    "score_before": 0.72,
    "score_after": 0.81
  },
  "message": "Fix applied successfully. Running evaluation..."
}
```

**Example curl:**
```bash
curl -X POST http://localhost:8000/api/assistant/action/approve_fix \
  -H "Content-Type: application/json" \
  -d '{"session_id": "your-session-id"}'
```

---

## Common Workflows

### Building an Agent

1. Upload transcripts
```bash
curl -X POST /api/assistant/upload -F "files=@transcripts.csv"
# Returns: {"session_id": "abc123", ...}
```

2. Ask assistant to build
```bash
curl -N -X POST /api/assistant/message \
  -H "Accept: text/event-stream" \
  -d '{"message": "Build agent from uploaded transcripts", "session_id": "abc123"}'
```

3. Review agent preview card in SSE stream

4. Save agent via action
```bash
curl -X POST /api/assistant/action/save_agent \
  -d '{"session_id": "abc123"}'
```

### Diagnosing Issues

1. Ask for diagnosis
```bash
curl -N -X POST /api/assistant/message \
  -H "Accept: text/event-stream" \
  -d '{"message": "Why are billing questions failing?"}'
```

2. Review diagnosis card in SSE stream

3. Approve fix
```bash
curl -X POST /api/assistant/action/approve_fix \
  -d '{"session_id": "xyz789"}'
```

### Exploring Conversations

1. Query conversations
```bash
curl -N -X POST /api/assistant/message \
  -H "Accept: text/event-stream" \
  -d '{"message": "Show me shipping complaints from last week"}'
```

2. Review cluster cards in SSE stream

3. Drill down on specific cluster
```bash
curl -N -X POST /api/assistant/message \
  -H "Accept: text/event-stream" \
  -d '{"message": "Tell me more about the tracking number issue", "session_id": "xyz789"}'
```

---

## Session Management

- Sessions are created automatically on first message
- Session IDs are returned in `X-Session-ID` header
- Include `session_id` in subsequent requests for conversation continuity
- Sessions are stored in-memory (development mode)
- Clear sessions with `DELETE /api/assistant/history`

---

## Error Handling

All endpoints return standard HTTP status codes:
- `200` - Success
- `400` - Bad request (validation error, unsupported file type, etc.)
- `404` - Not found (session not found, action not found)
- `422` - Unprocessable entity (Pydantic validation error)
- `500` - Internal server error

Error response format:
```json
{
  "detail": "Error message describing what went wrong"
}
```

SSE streams send errors via `error` events:
```
event: error
data: {"message": "Error processing message", "type": "internal_error"}
```

---

## Rate Limiting

Currently no rate limiting (development mode).

Production deployment should implement:
- Per-IP rate limiting
- Per-session rate limiting
- File upload size/count limits

---

## Production Considerations

Current implementation uses in-memory session storage. For production:

1. **Persistent Session Storage** - Use Redis, PostgreSQL, or similar
2. **File Storage** - Store uploads in S3, GCS, or filesystem
3. **Authentication** - Add JWT or API key authentication
4. **Rate Limiting** - Implement per-user/IP limits
5. **Monitoring** - Add metrics for message latency, error rates
6. **Scaling** - SSE connections are long-lived; use separate service
7. **Cleanup** - Implement session expiration and garbage collection

---

## Integration with AutoAgent Modules

The Assistant orchestrates existing AutoAgent modules:

- **Observer** - Diagnose agent health, blame map
- **Optimizer** - Propose and apply configuration changes
- **Eval Runner** - Run evaluations on configurations
- **Deployer** - Deploy changes with canary rollout
- **Trace Store** - Semantic search over conversations
- **Builder** (new) - Build agents from transcripts/docs

See `ASSISTANT_BRIEF.md` for architecture details.
