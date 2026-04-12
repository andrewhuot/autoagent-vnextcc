# P1 Unified Review Surface — Implementation Plan

**Date:** 2026-04-12
**Author:** Claude Opus 4.6
**Branch:** feat/p1-unified-review-surface-claude
**Issue:** #5 — Unify the review/decision surface

---

## Problem Statement

An operator must check **two separate pages** to see all pending decisions:

1. **Optimize page** (`/optimize`) — shows `PendingReviewStore` items (optimizer proposals awaiting human approval). JSON-file backed. API: `GET /api/optimize/pending`.
2. **Improvements page** (`/improvements?tab=review`) — shows `ChangeCardStore` items (change cards from the experiment/intelligence pipeline). SQLite backed. API: `GET /api/changes`.

These two queues use different stores, different persistence formats, different API endpoints, different data models, and different UI components. There is no unified count of "things requiring attention" and no single surface where an operator can see and act on all pending work.

Additionally, the **History tab** on Improvements only shows `ExperimentStore` entries — it does not include `OptimizationMemory` decisions (accepted/rejected optimizer attempts), creating an incomplete audit trail.

---

## Strategy: Aggregation Layer, Not Store Merger

**We will NOT merge the underlying stores.** Both stores serve different pipelines (optimizer loop vs. experiment/intelligence pipeline) with different persistence characteristics. Merging them would be a risky multi-week refactor that touches the core optimizer loop.

Instead, we build a **read-through aggregation layer**:

1. **Backend**: New `GET /api/reviews/pending` endpoint that reads from both stores and returns a unified response shape with a `source` discriminator.
2. **Backend**: New `POST /api/reviews/{id}/approve` and `/reject` endpoints that dispatch to the correct underlying store based on the source field.
3. **Backend**: New `GET /api/reviews/stats` endpoint for badge counts.
4. **Frontend**: New `useUnifiedReviews()` hook and `UnifiedReviewQueue` component.
5. **Frontend**: Replace the Review tab content in Improvements with the unified component.
6. **Frontend**: Add pending review count badge to the Sidebar "Improvements" nav item.
7. **Frontend**: Enrich the History tab to include OptimizationMemory decisions.

---

## Unified Review Item Schema

```python
class UnifiedReviewItem(BaseModel):
    """Normalized review item from any source store."""
    id: str                    # Original store's ID
    source: Literal["optimizer", "change_card"]
    status: str                # "pending", "approved"/"applied", "rejected"
    title: str                 # Human-readable title
    description: str           # Why this change was proposed
    score_before: float        # Baseline composite score
    score_after: float         # Candidate composite score
    score_delta: float         # score_after - score_before
    risk_class: str            # "low", "medium", "high"
    diff_summary: str          # Config diff (unified diff text)
    created_at: datetime       # When the review was created
    strategy: str | None       # Optimization strategy used
    operator_family: str | None  # Operator family (if applicable)
    has_detailed_audit: bool   # Whether source has audit trail
```

### Mapping from PendingReview

| UnifiedReviewItem  | PendingReview source         |
|-------------------|------------------------------|
| id                | attempt_id                   |
| source            | "optimizer"                  |
| status            | "pending" (always)           |
| title             | change_description           |
| description       | reasoning                    |
| score_before      | score_before                 |
| score_after       | score_after                  |
| diff_summary      | config_diff                  |
| risk_class        | "medium" (default)           |
| strategy          | strategy                     |
| operator_family   | selected_operator_family     |
| has_detailed_audit| False                        |

### Mapping from ProposedChangeCard

| UnifiedReviewItem  | ChangeCard source            |
|-------------------|------------------------------|
| id                | card_id                      |
| source            | "change_card"                |
| status            | status                       |
| title             | title                        |
| description       | why                          |
| score_before      | max(metrics_before.values()) |
| score_after       | max(metrics_after.values())  |
| diff_summary      | rendered from diff_hunks     |
| risk_class        | risk_class                   |
| strategy          | None                         |
| operator_family   | None                         |
| has_detailed_audit| True                         |

---

## API Design

### New endpoints (api/routes/reviews.py)

```
GET  /api/reviews/pending    → list[UnifiedReviewItem]  (pending from both stores)
GET  /api/reviews/all        → list[UnifiedReviewItem]  (all statuses)
GET  /api/reviews/stats      → { pending: int, approved: int, rejected: int, by_source: {...} }
POST /api/reviews/{id}/approve  → { status, message }  (body: { source: "optimizer"|"change_card" })
POST /api/reviews/{id}/reject   → { status, message }  (body: { source, reason? })
```

### Existing endpoints (unchanged)

All existing `/api/optimize/pending/*` and `/api/changes/*` endpoints remain for backwards compatibility and source-specific detail views (e.g., per-hunk actions on change cards, audit trail).

---

## Frontend Design

### New hooks (in api.ts)

- `useUnifiedReviews(poll?)` — queries `GET /api/reviews/pending`, returns `UnifiedReviewItem[]`
- `useUnifiedReviewStats()` — queries `GET /api/reviews/stats`
- `useApproveUnifiedReview()` — mutation, `POST /api/reviews/{id}/approve`
- `useRejectUnifiedReview()` — mutation, `POST /api/reviews/{id}/reject`

### New component: UnifiedReviewQueue

Renders all pending items in one list, sorted by `created_at` descending. Each item shows:
- Source badge (Optimizer / Change Card)
- Title + description
- Score delta with visual indicator
- Risk class badge
- Approve/Reject buttons
- "View details" link that goes to the source-specific detail view

For optimizer items, "View details" expands inline (config diff + governance notes).
For change card items, "View details" opens the existing SelectedCardDetail component.

### Integration into Improvements page

The Review tab currently renders `<ChangeReview embedded />`. We replace it with a new `<UnifiedReviewQueue />` that:
1. Shows ALL pending items from both sources
2. Preserves the existing ChangeCard detail view (audit trail, hunk-level actions) for change card items
3. Adds equivalent detail view for optimizer items (config diff, governance notes, scores)

### History tab enrichment

The History tab currently only shows ExperimentStore entries. We enrich it by also fetching `GET /api/optimize/history` and interleaving optimizer decisions with experiment decisions, sorted by timestamp.

### Sidebar badge

The "Improvements" nav item gets a pending count badge showing the number of items awaiting review from both stores.

---

## Files to Create

| File | Purpose |
|------|---------|
| `api/routes/reviews.py` | Unified review API endpoints |
| `web/src/pages/UnifiedReviewQueue.tsx` | Unified review queue component |
| `tests/test_unified_reviews.py` | Backend tests for unified review API |

## Files to Modify

| File | Change |
|------|--------|
| `api/models.py` | Add `UnifiedReviewItem` and `UnifiedReviewStats` models |
| `api/server.py` | Register reviews router |
| `web/src/lib/api.ts` | Add unified review hooks |
| `web/src/lib/types.ts` | Add `UnifiedReviewItem` TypeScript type |
| `web/src/pages/Improvements.tsx` | Replace Review tab, enrich History tab |
| `web/src/components/Sidebar.tsx` | Add pending review count badge |

## Files NOT modified (preserved for backwards compat)

| File | Reason |
|------|--------|
| `optimizer/pending_reviews.py` | Underlying store unchanged |
| `optimizer/change_card.py` | Underlying store unchanged |
| `api/routes/optimize.py` | Existing endpoints preserved |
| `api/routes/changes.py` | Existing endpoints preserved |
| `web/src/pages/Optimize.tsx` | Keeps its inline review panel |

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| New endpoint adds latency (reads from two stores) | Both stores are local (JSON files + SQLite); reads are fast |
| Approve/reject dispatch could hit wrong store | Source field is required in the request body; validate before dispatch |
| Sidebar badge creates N+1 polling | Single endpoint, single query, 10s interval |
| Breaking existing Optimize page review panel | We don't remove it — it still works for operators who prefer the optimize-centric workflow |

---

## What This Unifies vs. What Stays Separate

### Unified
- Single pending review list across both stores
- Single approve/reject action surface
- Unified pending count badge
- Interleaved history (optimizer decisions + experiment decisions)

### Stays separate
- Underlying persistence (JSON files vs SQLite)
- Source-specific detail views (change card audit trail, hunk-level review)
- The Optimize page's inline review panel (still works independently)
- Per-store APIs (preserved for CLI, MCP, backwards compat)

---

## Implementation Order

1. Backend: `UnifiedReviewItem` model + `api/routes/reviews.py`
2. Backend: Register router in `api/server.py`
3. Backend: Tests
4. Frontend: Types + hooks
5. Frontend: `UnifiedReviewQueue` component
6. Frontend: Replace Review tab in Improvements
7. Frontend: Sidebar badge
8. Frontend: Enrich History tab
9. Integration test / UI validation
