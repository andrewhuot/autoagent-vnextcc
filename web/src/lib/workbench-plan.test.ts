import { describe, expect, it } from 'vitest';
import type { PlanTask, PlanTaskStatus } from './workbench-api';
import {
  findTaskById,
  recomputeParentStatus,
  summarizePlan,
  walkLeaves,
  walkTasks,
} from './workbench-plan';

function task(
  id: string,
  title: string,
  status: PlanTaskStatus = 'pending',
  children: PlanTask[] = []
): PlanTask {
  return {
    id,
    title,
    status,
    description: '',
    children,
    artifact_ids: [],
    log: [],
    parent_id: null,
    started_at: null,
    completed_at: null,
  };
}

describe('workbench-plan', () => {
  it('finds nested tasks by id', () => {
    const root = task('r', 'root', 'pending', [
      task('g', 'group', 'pending', [task('l1', 'leaf 1'), task('l2', 'leaf 2')]),
    ]);
    expect(findTaskById(root, 'l2')?.title).toBe('leaf 2');
    expect(findTaskById(root, 'missing')).toBeNull();
  });

  it('walks the tree depth-first and yields leaves', () => {
    const root = task('r', 'root', 'pending', [
      task('g1', 'group 1', 'pending', [task('l1', 'leaf 1'), task('l2', 'leaf 2')]),
      task('g2', 'group 2', 'pending', [task('l3', 'leaf 3')]),
    ]);
    expect([...walkTasks(root)].map((t) => t.id)).toEqual([
      'r',
      'g1',
      'l1',
      'l2',
      'g2',
      'l3',
    ]);
    expect(walkLeaves(root).map((t) => t.id)).toEqual(['l1', 'l2', 'l3']);
  });

  it('bubbles DONE up when all children are done', () => {
    const root = task('r', 'root', 'pending', [
      task('a', 'a', 'done'),
      task('b', 'b', 'done'),
    ]);
    recomputeParentStatus(root);
    expect(root.status).toBe('done');
  });

  it('marks parent RUNNING when any child is running', () => {
    const root = task('r', 'root', 'pending', [
      task('a', 'a', 'done'),
      task('b', 'b', 'running'),
      task('c', 'c', 'pending'),
    ]);
    recomputeParentStatus(root);
    expect(root.status).toBe('running');
  });

  it('marks parent ERROR when any child errored', () => {
    const root = task('r', 'root', 'pending', [
      task('a', 'a', 'done'),
      task('b', 'b', 'error'),
    ]);
    recomputeParentStatus(root);
    expect(root.status).toBe('error');
  });

  it('summarizes done / running / leaf counts', () => {
    const root = task('r', 'root', 'pending', [
      task('g', 'group', 'pending', [
        task('a', 'a', 'done'),
        task('b', 'b', 'running'),
        task('c', 'c', 'pending'),
      ]),
    ]);
    const summary = summarizePlan(root);
    expect(summary.leafCount).toBe(3);
    expect(summary.done).toBe(1);
    expect(summary.running).toBe(1);
  });
});
