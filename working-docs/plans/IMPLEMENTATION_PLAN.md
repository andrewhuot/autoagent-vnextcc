# WOW Features Implementation Plan

## Executive Summary
Implement 6 high-impact UX features across 4 parallel tracks. All features are ADDITIVE — no breaking changes.

**Quality Gates:**
- All 1,429+ existing tests must pass
- TypeScript compilation must succeed
- Dependency layer enforcement must pass
- New tests required for: SSE endpoint, quickfix API, CLI sparkles, smart search

---

## Track A: Celebration Components (Features 1 + 3)

### Feature 1: Animated Score Celebration

#### Component 1: Confetti.tsx
**Path:** `web/src/components/Confetti.tsx`

```typescript
interface ConfettiProps {
  trigger: boolean;  // When true, starts animation
  duration?: number; // Default 2000ms
}
```

**Implementation:**
- Pure CSS animation, no libraries
- 20 particle divs, absolutely positioned
- Random colors: ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6']
- Burst pattern: spread from center using `translate()` and `rotate()`
- Each particle: random angle (0-360°), random distance (100-300px)
- Animation: `opacity: 1 → 0`, `transform: translateY(0) → translateY(100px)`, 2s ease-out
- Auto-cleanup: unmount particles after animation completes

**CSS Keyframes:**
```css
@keyframes confetti-burst {
  0% { transform: translate(0, 0) rotate(0deg); opacity: 1; }
  100% { transform: translate(var(--x), var(--y)) rotate(720deg); opacity: 0; }
}
```

#### Component 2: AnimatedNumber.tsx
**Path:** `web/src/components/AnimatedNumber.tsx`

```typescript
interface AnimatedNumberProps {
  value: number;
  decimals?: number;  // Default 4
  duration?: number;  // Default 800ms
}
```

**Implementation:**
- Use `requestAnimationFrame` for smooth counting
- Easing: ease-out (slow at end)
- Start from previous value (stored in ref)
- Update displayed value 60fps during animation
- Format with fixed decimals

**Logic:**
```typescript
const animate = (start: number, end: number, duration: number) => {
  const startTime = performance.now();
  const step = (currentTime: number) => {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
    const current = start + (end - start) * eased;
    setDisplayValue(current);
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
};
```

#### Component 3: MetricCard glow animation
**Path:** `web/src/components/MetricCard.tsx` (MODIFY)

**New Prop:**
```typescript
interface MetricCardProps {
  // ... existing props
  glow?: boolean;  // Trigger glow animation
}
```

**CSS Addition:**
```css
@keyframes metric-glow {
  0%, 100% { box-shadow: 0 0 0 rgba(16, 185, 129, 0); border-color: rgb(229, 231, 235); }
  50% { box-shadow: 0 0 20px rgba(16, 185, 129, 0.5); border-color: rgb(16, 185, 129); }
}

.metric-card-glow {
  animation: metric-glow 1.5s ease-in-out;
}
```

**Logic:** When `glow` prop changes to true, add the class for 1.5s, then remove.

#### Component 4: PersonalBestBadge
**Path:** `web/src/components/PersonalBestBadge.tsx`

```typescript
interface PersonalBestBadgeProps {
  show: boolean;
  onHide: () => void;
}
```

**Implementation:**
- Gold gradient background: `bg-gradient-to-r from-yellow-400 to-orange-500`
- Sparkle icon (✨) + "New personal best!" text
- Fixed position: top-right of viewport, z-50
- Fade in animation (0.3s), auto-hide after 5s with fade out
- CSS: `@keyframes slideInRight` for entrance

### Feature 3: Agent Health Pulse

#### Component: HealthPulse.tsx
**Path:** `web/src/components/HealthPulse.tsx`

```typescript
interface HealthPulseProps {
  score: number;        // 0-1
  label?: string;       // "Agent Health"
  size?: 'sm' | 'md' | 'lg';  // Default 'md'
}
```

**Implementation:**

**SVG Structure:**
```tsx
<svg viewBox="0 0 120 120" className={sizeClass}>
  {/* Pulse ring - animated circle */}
  <circle
    cx="60" cy="60" r="50"
    fill="none"
    stroke={strokeColor}
    strokeWidth="2"
    className="pulse-ring"
  />
  {/* Static background circle */}
  <circle cx="60" cy="60" r="45" fill={bgColor} />
  {/* Score text */}
  <text x="60" y="60" textAnchor="middle" className="score-text">
    {(score * 100).toFixed(0)}
  </text>
</svg>
```

**CSS Keyframes:**
```css
@keyframes pulse-healthy {
  0%, 100% { r: 50; opacity: 0.8; }
  50% { r: 55; opacity: 0.4; }
}

@keyframes pulse-warning {
  0%, 100% { r: 50; opacity: 0.8; }
  50% { r: 55; opacity: 0.4; }
}

@keyframes pulse-critical {
  0%, 100% { r: 50; opacity: 1; }
  50% { r: 56; opacity: 0.3; }
}
```

**Color/Animation Logic:**
- `score > 0.85`: green (#10b981), 3s pulse
- `0.65 <= score <= 0.85`: amber (#f59e0b), 1.5s pulse
- `score < 0.65`: red (#ef4444), 0.8s pulse

**ECG Line:** Small SVG path next to score, animated using `stroke-dashoffset`

**Status Text:** Below the ring, animated fade-in on change

---

## Track B: Live Optimization Feed (Feature 2)

### Backend: SSE Endpoint

#### File: api/routes/optimize_stream.py
**Path:** `api/routes/optimize_stream.py` (CREATE)

```python
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import asyncio
import json

router = APIRouter(prefix="/api/optimize", tags=["optimize"])

@router.get("/stream")
async def optimize_stream(
    request: Request,
    cycles: int = 3,
    mode: str = "standard"
) -> StreamingResponse:
    """Server-Sent Events stream for live optimization progress."""

    async def event_generator() -> AsyncGenerator[str, None]:
        optimizer = request.app.state.optimizer
        eval_runner = request.app.state.eval_runner

        for cycle in range(1, cycles + 1):
            # Event 1: cycle_start
            yield f"event: cycle_start\ndata: {json.dumps({'cycle': cycle, 'total': cycles})}\n\n"
            await asyncio.sleep(0.1)

            # Event 2: diagnosis
            diagnosis_result = await run_diagnosis()  # Get from optimizer
            yield f"event: diagnosis\ndata: {json.dumps(diagnosis_result)}\n\n"
            await asyncio.sleep(0.5)

            # Event 3: proposal
            proposal_result = await run_proposal()
            yield f"event: proposal\ndata: {json.dumps(proposal_result)}\n\n"
            await asyncio.sleep(0.5)

            # Event 4: evaluation
            eval_result = await run_evaluation()
            yield f"event: evaluation\ndata: {json.dumps(eval_result)}\n\n"
            await asyncio.sleep(0.5)

            # Event 5: decision
            decision_result = await run_decision()
            yield f"event: decision\ndata: {json.dumps(decision_result)}\n\n"
            await asyncio.sleep(0.5)

            # Event 6: cycle_complete
            yield f"event: cycle_complete\ndata: {json.dumps({'cycle': cycle, 'best_score': 0.78})}\n\n"

        # Event 7: optimization_complete
        yield f"event: optimization_complete\ndata: {json.dumps({'cycles': cycles, 'baseline': 0.72, 'final': 0.83, 'improvement': 0.11})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

**Event Schema Reference:**
1. `cycle_start`: `{ cycle: number, total: number }`
2. `diagnosis`: `{ failure_buckets: object, dominant: string, total_failures: number }`
3. `proposal`: `{ change_description: string, config_section: string, reasoning: string }`
4. `evaluation`: `{ score_before: number, score_after: number, improvement: number }`
5. `decision`: `{ accepted: boolean, p_value: number, effect_size: number }`
6. `cycle_complete`: `{ cycle: number, best_score: number }`
7. `optimization_complete`: `{ cycles: number, baseline: number, final: number, improvement: number }`

**Register Route:** Add to `api/server.py`:
```python
from api.routes import optimize_stream
app.include_router(optimize_stream.router)
```

### Frontend: Live Optimization Page

#### Component 1: PhaseIndicator.tsx
**Path:** `web/src/components/PhaseIndicator.tsx`

```typescript
interface PhaseIndicatorProps {
  activePhase: 'diagnose' | 'propose' | 'evaluate' | 'decide' | null;
  completedPhases: Set<string>;
}
```

**Implementation:**
- 4 boxes in a row with arrows between
- Each box: 120px wide, rounded border
- States:
  - Pending: gray bg, gray border, circle outline icon
  - Active: blue bg, blue border, pulse animation, filled circle icon
  - Complete: green bg, green border, checkmark icon
- Arrow: `→` character or SVG, gray

**CSS:**
```css
@keyframes phase-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.05); opacity: 0.9; }
}
```

#### Component 2: LiveCycleCard.tsx
**Path:** `web/src/components/LiveCycleCard.tsx`

```typescript
interface LiveCycleCardProps {
  cycle: number;
  changeDescription: string;
  scoreDelta: number;
  accepted: boolean;
}
```

**Implementation:**
- Card with border
- Header: "Cycle #{cycle}" + Accept/Reject badge (green/red)
- Body: change description (truncated to 2 lines)
- Footer: Score delta with arrow icon (up/down based on sign)
- Animate in from bottom: `@keyframes slideInUp`

#### Page: LiveOptimize.tsx
**Path:** `web/src/pages/LiveOptimize.tsx`

**State:**
```typescript
const [isRunning, setIsRunning] = useState(false);
const [currentPhase, setCurrentPhase] = useState<Phase | null>(null);
const [completedCycles, setCompletedCycles] = useState<CycleResult[]>([]);
const [scoreData, setScoreData] = useState<ScorePoint[]>([]);
```

**Layout:**
- Top: "Live Optimization" heading + "Start Optimization" button (or "Running..." when active)
- Center: PhaseIndicator (large, prominent)
- Below: Real-time score chart (updates as cycles complete)
- Bottom: Grid of LiveCycleCard components (newest first)

**SSE Connection:**
```typescript
const startOptimization = () => {
  const eventSource = new EventSource('/api/optimize/stream?cycles=3&mode=standard');

  eventSource.addEventListener('cycle_start', (e) => {
    const data = JSON.parse(e.data);
    setCurrentPhase('diagnose');
  });

  eventSource.addEventListener('diagnosis', (e) => {
    setCurrentPhase('propose');
  });

  eventSource.addEventListener('proposal', (e) => {
    setCurrentPhase('evaluate');
  });

  eventSource.addEventListener('evaluation', (e) => {
    setCurrentPhase('decide');
  });

  eventSource.addEventListener('cycle_complete', (e) => {
    const data = JSON.parse(e.data);
    setCompletedCycles(prev => [...prev, data]);
    setScoreData(prev => [...prev, { cycle: data.cycle, score: data.best_score }]);
    setCurrentPhase(null);
  });

  eventSource.addEventListener('optimization_complete', (e) => {
    setIsRunning(false);
    triggerConfetti();  // From Feature 1
    eventSource.close();
  });
};
```

---

## Track C: Dashboard Integration (Features 5 + 6)

### Feature 5: Journey Timeline

#### Component: JourneyTimeline.tsx
**Path:** `web/src/components/JourneyTimeline.tsx`

```typescript
interface TimelineNode {
  version: string;
  score: number;
  change: string;
  status: 'accepted' | 'rejected' | 'baseline';
  timestamp: number;
}

interface JourneyTimelineProps {
  nodes: TimelineNode[];
  onNodeClick?: (version: string) => void;
}
```

**Implementation:**

**Structure:**
```tsx
<div className="timeline-container horizontal-scroll">
  <svg className="timeline-line">
    {/* Animated path connecting nodes */}
    <path d="M 0 50 L {totalWidth} 50" stroke="#ccc" strokeWidth="2" className="timeline-path" />
  </svg>
  <div className="timeline-nodes">
    {nodes.map((node, i) => (
      <div key={node.version} className="timeline-node" style={{ left: `${i * 150}px` }}>
        {/* Circle */}
        <div className={`node-circle ${node.status}`}>
          <span className="node-label">{node.version}</span>
        </div>
        {/* Score below */}
        <div className="node-score">{node.score.toFixed(2)}</div>
        {/* Change above */}
        <div className="node-change">{truncate(node.change, 20)}</div>
      </div>
    ))}
  </div>
</div>
```

**CSS:**
```css
@keyframes draw-line {
  from { stroke-dashoffset: 1000; }
  to { stroke-dashoffset: 0; }
}

.timeline-path {
  stroke-dasharray: 1000;
  animation: draw-line 2s ease-out forwards;
}

.node-circle.accepted {
  background: #10b981;
  border: 2px solid #059669;
}

.node-circle.rejected {
  background: #ef4444;
  border: 2px solid #dc2626;
}

.node-circle.current {
  animation: pulse-ring 2s infinite;
}
```

**Data Source:** Fetch from `/api/optimize/history`, transform to TimelineNode format.

### Feature 6: One-Click Fix Buttons

#### Component: FixButton.tsx
**Path:** `web/src/components/FixButton.tsx`

```typescript
interface FixButtonProps {
  failureFamily: string;  // e.g., "routing_error"
  failureCount: number;
  onComplete?: () => void;
}
```

**Runbook Mapping:**
```typescript
const RUNBOOK_MAP: Record<string, string> = {
  routing_error: 'fix-retrieval-grounding',
  safety_violation: 'tighten-safety-policy',
  quality_issue: 'enhance-few-shot-examples',
  latency_problem: 'reduce-tool-latency',
  cost_overrun: 'optimize-cost-efficiency',
  tool_error: 'reduce-tool-latency',
  hallucination: 'fix-retrieval-grounding',
};
```

**Implementation:**
- Button: "Fix →" with wrench icon
- Click: Open modal with confirmation
  - Title: "Apply Runbook"
  - Body: "Apply '{runbook_name}' and run 1 optimization cycle to fix {failure_count} {failureFamily} failures?"
  - Actions: "Cancel" | "Apply & Optimize"
- On confirm: POST to `/api/quickfix` with `{ failure_family: string }`
- Loading state: Button shows spinner
- Success: Button shows green checkmark, toast notification
- Error: Button shows red X, error message

**API Call:**
```typescript
const handleApply = async () => {
  setLoading(true);
  try {
    const response = await fetch('/api/quickfix', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ failure_family: failureFamily }),
    });
    const result = await response.json();
    setSuccess(result.success);
    onComplete?.();
  } catch (error) {
    setError(error.message);
  } finally {
    setLoading(false);
  }
};
```

#### Backend: Quickfix Endpoint

**Path:** `api/routes/quickfix.py` (CREATE)

```python
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["quickfix"])

class QuickfixRequest(BaseModel):
    failure_family: str

RUNBOOK_MAP = {
    "routing_error": "fix-retrieval-grounding",
    "safety_violation": "tighten-safety-policy",
    "quality_issue": "enhance-few-shot-examples",
    "latency_problem": "reduce-tool-latency",
    "cost_overrun": "optimize-cost-efficiency",
    "tool_error": "reduce-tool-latency",
    "hallucination": "fix-retrieval-grounding",
}

@router.post("/quickfix")
async def quickfix(request: Request, body: QuickfixRequest):
    """One-click fix: apply runbook + run 1 optimization cycle."""
    runbook_name = RUNBOOK_MAP.get(body.failure_family)
    if not runbook_name:
        raise HTTPException(status_code=400, detail="Unknown failure family")

    runbook_store = request.app.state.runbook_store
    runbook = runbook_store.get(runbook_name)
    if not runbook:
        raise HTTPException(status_code=404, detail="Runbook not found")

    # Apply runbook surfaces/skills to config
    # ... (load active config, merge runbook surfaces, save as experiment)

    # Run 1 optimization cycle targeting those surfaces
    optimizer = request.app.state.optimizer
    result = optimizer.optimize(cycles=1, surfaces=runbook.surfaces)

    return {
        "success": result.accepted,
        "runbook": runbook_name,
        "score_before": result.score_before,
        "score_after": result.score_after,
        "improvement": result.improvement,
    }
```

**Register Route:** Add to `api/server.py`:
```python
from api.routes import quickfix
app.include_router(quickfix.router)
```

#### Dashboard Integration

**Path:** `web/src/pages/Dashboard.tsx` (MODIFY)

**Changes:**
1. Add FixButton to failure breakdown section (currently in "Why? Diagnostic Signals" collapsible)
2. Replace static health score with HealthPulse component
3. Add JourneyTimeline between health metrics and failure breakdown
4. Add Confetti trigger when new score exceeds all-time best
5. Use AnimatedNumber for composite score display

**Example:**
```tsx
{/* Replace static score with HealthPulse */}
<HealthPulse score={metrics.composite} label="Agent Health" size="lg" />

{/* Add Journey Timeline */}
<section className="...">
  <h3>Optimization Journey</h3>
  <JourneyTimeline nodes={timelineNodes} onNodeClick={(v) => navigate(`/configs?v=${v}`)} />
</section>

{/* Add FixButton to failure breakdown */}
<div className="failure-item">
  <span>{failureFamily}</span>
  <div className="failure-bar">...</div>
  <FixButton failureFamily={failureFamily} failureCount={count} onComplete={refreshAll} />
</div>
```

---

## Track D: Command Palette + CLI (Features 4 + 1 CLI)

### Feature 4: Natural Language Command Palette Search

**Path:** `web/src/components/CommandPalette.tsx` (MODIFY)

**Add Smart Search Mapping:**
```typescript
const SMART_SEARCH_MAP: Array<{
  keywords: string[];
  label: string;
  description: string;
  href: string;
  category: 'Suggested Actions' | 'Navigate' | 'Recent';
}> = [
  {
    keywords: ['why', 'routing', 'failing', 'failure', 'blame'],
    label: 'Diagnose routing failures',
    description: 'Jump to Blame Map filtered on routing_error',
    href: '/blame?filter=routing_error',
    category: 'Suggested Actions',
  },
  {
    keywords: ['fix', 'safety', 'violation'],
    label: 'Fix safety violations',
    description: 'Apply tighten-safety-policy runbook',
    href: '/runbooks?action=apply&runbook=tighten-safety-policy',
    category: 'Suggested Actions',
  },
  {
    keywords: ['what', 'changed', 'changes', 'diff'],
    label: 'What changed?',
    description: 'View recent config changes',
    href: '/changes',
    category: 'Navigate',
  },
  {
    keywords: ['show', 'failures', 'conversations', 'fail'],
    label: 'Show me failures',
    description: 'Browse failed conversations',
    href: '/conversations?outcome=fail',
    category: 'Navigate',
  },
  {
    keywords: ['how', 'agent', 'doing', 'health', 'status'],
    label: 'How is my agent doing?',
    description: 'Open dashboard',
    href: '/',
    category: 'Navigate',
  },
  {
    keywords: ['deploy', 'production', 'ship', 'release'],
    label: 'Deploy to production',
    description: 'Open CX Deploy page',
    href: '/cx/deploy',
    category: 'Suggested Actions',
  },
  {
    keywords: ['import', 'agent', 'cx', 'studio'],
    label: 'Import agent',
    description: 'Import from Vertex AI Agent Studio',
    href: '/cx/import',
    category: 'Navigate',
  },
  {
    keywords: ['optimize', 'improve', 'run', 'cycle'],
    label: 'Run optimization',
    description: 'Start live optimization',
    href: '/live-optimize',
    category: 'Suggested Actions',
  },
  {
    keywords: ['compare', 'configs', 'diff', 'versions'],
    label: 'Compare configs',
    description: 'View config history',
    href: '/configs',
    category: 'Navigate',
  },
];
```

**Fuzzy Match Logic:**
```typescript
function smartSearch(query: string): SmartSearchResult[] {
  const tokens = query.toLowerCase().split(/\s+/);
  const results: Array<{ item: typeof SMART_SEARCH_MAP[0], score: number }> = [];

  for (const item of SMART_SEARCH_MAP) {
    let score = 0;
    for (const token of tokens) {
      for (const keyword of item.keywords) {
        if (keyword.includes(token)) {
          score += token.length / keyword.length;  // Partial match scoring
        }
      }
    }
    if (score > 0) {
      results.push({ item, score });
    }
  }

  return results
    .sort((a, b) => b.score - a.score)
    .slice(0, 5)
    .map(r => r.item);
}
```

**UI Changes:**
- When smart search results exist, show "Smart Results" group at the top
- Show icon badge (sparkle ✨) next to smart results
- Regular search results appear below

### Feature 1 CLI: Sparkles on Improvements

**Path:** `runner.py` (MODIFY)

**Location:** Find the optimization output section (search for where composite scores are printed)

**Changes:**

1. **Track all-time best score:**
```python
# At the top of optimize command
best_score_file = Path(".autoagent/best_score.txt")
all_time_best = 0.0
if best_score_file.exists():
    all_time_best = float(best_score_file.read_text().strip())
```

2. **Add sparkle on improvement:**
```python
# After each cycle evaluation
improvement = score_after - score_before
if improvement > 0:
    sparkle = " ✨" if score_after > all_time_best else ""
    click.echo(f"  ✓ composite={score_after:.4f} (+{improvement:.4f}){sparkle}")

    # Update all-time best
    if score_after > all_time_best:
        best_score_file.parent.mkdir(exist_ok=True)
        best_score_file.write_text(str(score_after))
        click.echo(click.style("\n  ✨ New personal best!", fg="yellow", bold=True))
else:
    click.echo(f"  ✗ composite={score_after:.4f} ({improvement:+.4f})")
```

**Color:** Use `click.style()` with `fg="yellow"` for the sparkle and "New personal best!" message.

---

## Integration Checklist

### Dashboard.tsx Integration
- [ ] Import: HealthPulse, JourneyTimeline, FixButton, Confetti, AnimatedNumber
- [ ] Replace static health display with `<HealthPulse score={metrics.composite} />`
- [ ] Add `<JourneyTimeline nodes={timelineNodes} />` section
- [ ] Add `<FixButton>` to each failure bucket in diagnostics
- [ ] Add `<Confetti trigger={showConfetti} />` at top level
- [ ] Replace score number with `<AnimatedNumber value={metrics.composite} />`
- [ ] Add logic to detect new personal best and trigger confetti

### App.tsx Routing
- [ ] Import LiveOptimize page
- [ ] Add route: `<Route path="/live-optimize" element={<LiveOptimize />} />`

### Sidebar.tsx Navigation
- [ ] Add nav item: `{ to: '/live-optimize', label: 'Live Optimize', icon: Sparkles }`
- [ ] Style with special highlight (e.g., gradient text or icon color)

### server.py Routes
- [ ] Import and register optimize_stream router
- [ ] Import and register quickfix router

### Tests Required

#### Backend Tests
1. `tests/api/test_optimize_stream.py` - SSE endpoint streaming
2. `tests/api/test_quickfix.py` - Quickfix endpoint logic
3. `tests/test_runner_sparkles.py` - CLI sparkle output

#### Frontend Tests (optional, not required for passing)
- Smart search keyword matching
- SSE event handling in LiveOptimize

---

## CSS Variables & Keyframes (Global)

Add to `web/src/index.css`:

```css
/* Confetti particles */
@keyframes confetti-burst {
  0% {
    transform: translate(0, 0) rotate(0deg) scale(1);
    opacity: 1;
  }
  100% {
    transform: translate(var(--x), var(--y)) rotate(720deg) scale(0.5);
    opacity: 0;
  }
}

/* Metric card glow */
@keyframes metric-glow {
  0%, 100% {
    box-shadow: 0 0 0 rgba(16, 185, 129, 0);
    border-color: rgb(229, 231, 235);
  }
  50% {
    box-shadow: 0 0 20px rgba(16, 185, 129, 0.5);
    border-color: rgb(16, 185, 129);
  }
}

/* Health pulse rings */
@keyframes pulse-healthy {
  0%, 100% { r: 50; opacity: 0.8; }
  50% { r: 55; opacity: 0.4; }
}

@keyframes pulse-warning {
  0%, 100% { r: 50; opacity: 0.8; }
  50% { r: 55; opacity: 0.4; }
}

@keyframes pulse-critical {
  0%, 100% { r: 50; opacity: 1; }
  50% { r: 56; opacity: 0.3; }
}

/* Phase indicator pulse */
@keyframes phase-pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.05);
    opacity: 0.9;
  }
}

/* Timeline line draw */
@keyframes draw-line {
  from { stroke-dashoffset: 1000; }
  to { stroke-dashoffset: 0; }
}

/* Slide in animations */
@keyframes slideInRight {
  from {
    transform: translateX(100%);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

@keyframes slideInUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}
```

---

## Dependency Layer Classification

New modules may need classification in `tests/test_dependency_layers.py`:

- `api/routes/optimize_stream.py` → **surface** (API route)
- `api/routes/quickfix.py` → **surface** (API route)
- All web components remain unclassified (frontend code)

---

## Commit Strategy

**Feature branches:**
1. `feat/celebration-components` (Track A)
2. `feat/live-optimization-feed` (Track B)
3. `feat/dashboard-integration` (Track C)
4. `feat/smart-palette-cli` (Track D)

**Final commit:** Merge all tracks to master with message:
```
feat: wow UX — celebrations, live feed, health pulse, smart search, journey timeline, one-click fix

- Animated celebrations: confetti, score counter, glow, personal best badge
- Live optimization feed: SSE streaming, phase indicators, real-time updates
- Agent health pulse: living indicator with color-coded animations
- Smart command palette: natural language search with keyword matching
- Journey timeline: horizontal optimization history visualization
- One-click fix buttons: runbook application + optimization in single click
- CLI sparkles: ✨ on improvements and personal bests

All features additive, no breaking changes. Tests: 1,429+ passing.
```

---

## Quality Assurance

### Pre-commit Checks
```bash
# TypeScript compilation
cd web && npx tsc --noEmit

# Python tests
python3 -m pytest tests/ -x -q

# Dependency layers
python3 -m pytest tests/test_dependency_layers.py -v
```

### Manual Testing Checklist
- [ ] Confetti triggers on score improvement in Dashboard
- [ ] Health pulse animates with correct color/speed based on score
- [ ] Live Optimize page SSE connection works end-to-end
- [ ] Phase indicator updates correctly during optimization
- [ ] Journey timeline renders and is scrollable
- [ ] Timeline nodes show correct colors (green/red/gray)
- [ ] Fix buttons open modal, call API, show loading/success states
- [ ] Command palette smart search returns relevant results
- [ ] CLI shows ✨ sparkle on improvements
- [ ] CLI shows "New personal best!" message when exceeding all-time best
- [ ] AnimatedNumber counts smoothly from old to new value
- [ ] Sidebar "Live Optimize" nav item has special styling

---

## Success Criteria

✅ All 6 features implemented and functional
✅ 1,429+ tests passing
✅ TypeScript compilation successful
✅ Dependency layer test passing
✅ No breaking changes to existing features
✅ Performance: No noticeable lag in animations or SSE streaming
✅ Accessibility: Keyboard navigation works in command palette
✅ Mobile: Dashboard remains responsive with new components

---

## Timeline Estimate

- **Track A** (Celebration Components): 2-3 hours
- **Track B** (Live Feed): 3-4 hours
- **Track C** (Dashboard Integration): 2-3 hours
- **Track D** (Smart Palette + CLI): 1-2 hours
- **Integration & Testing**: 1-2 hours

**Total:** 9-14 hours (parallelized to ~4-6 hours with 4 agents)
