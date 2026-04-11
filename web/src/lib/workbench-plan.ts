/**
 * Pure helpers that operate on a PlanTask tree.
 *
 * Kept separate from the Zustand store so unit tests can exercise the
 * tree algorithms without touching React state.
 */

import type { PlanTask, PlanTaskStatus } from './workbench-api';

/** Depth-first search for a task by ID; returns a mutable reference. */
export function findTaskById(root: PlanTask, taskId: string): PlanTask | null {
  if (root.id === taskId) return root;
  for (const child of root.children ?? []) {
    const found = findTaskById(child, taskId);
    if (found) return found;
  }
  return null;
}

/** Iterate every task in the tree depth-first (parents first, then children). */
export function* walkTasks(root: PlanTask): Generator<PlanTask> {
  yield root;
  for (const child of root.children ?? []) {
    yield* walkTasks(child);
  }
}

/** Return only the leaf tasks — the ones the executor actually runs. */
export function walkLeaves(root: PlanTask): PlanTask[] {
  const children = root.children ?? [];
  if (children.length === 0) return [root];
  const leaves: PlanTask[] = [];
  for (const child of children) {
    leaves.push(...walkLeaves(child));
  }
  return leaves;
}

/**
 * Bubble leaf statuses up to parents so groups show the right rollup icon.
 *
 * Matches the backend's Python implementation byte-for-byte so the UI and
 * persisted snapshot stay in sync.
 */
export function recomputeParentStatus(root: PlanTask): void {
  const children = root.children ?? [];
  if (children.length === 0) return;
  for (const child of children) {
    recomputeParentStatus(child);
  }
  const statuses = new Set<PlanTaskStatus>(children.map((c) => c.status));
  if (statuses.size === 1 && statuses.has('done')) {
    root.status = 'done';
    return;
  }
  if (statuses.has('error')) {
    root.status = 'error';
    return;
  }
  if (statuses.has('running')) {
    root.status = 'running';
    return;
  }
  if (statuses.size === 1 && statuses.has('paused')) {
    root.status = 'paused';
    return;
  }
  if (statuses.has('done') && statuses.has('pending')) {
    root.status = 'running';
  }
}

/** Count total / done / running across the whole tree.
 *
 * ``done`` / ``running`` are leaf-only so the header counter reads
 * "3/8 steps" rather than double-counting parent bubble-up status.
 */
export function summarizePlan(root: PlanTask | null): {
  total: number;
  done: number;
  running: number;
  leafCount: number;
} {
  if (!root) {
    return { total: 0, done: 0, running: 0, leafCount: 0 };
  }
  let total = 0;
  let done = 0;
  let running = 0;
  let leafCount = 0;
  for (const task of walkTasks(root)) {
    total += 1;
    const isLeaf = !task.children || task.children.length === 0;
    if (isLeaf) {
      leafCount += 1;
      if (task.status === 'done') done += 1;
      if (task.status === 'running') running += 1;
    }
  }
  return { total, done, running, leafCount };
}
