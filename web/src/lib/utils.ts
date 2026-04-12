import type { ProductStatusMeta, ProductStatusVariant } from './types';

export function formatTimestamp(ts: string | number): string {
  const value =
    typeof ts === 'number'
      ? new Date(ts > 2_000_000_000 ? ts : ts * 1000)
      : new Date(ts);
  const date = Number.isNaN(value.getTime()) ? new Date() : value;
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    year: 'numeric',
  });
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${mins}m`;
}

export function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatScore(score: number): string {
  return score.toFixed(1);
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + '...';
}

export function classNames(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ');
}

export function scoreColor(score: number): string {
  if (score >= 80) return 'text-green-600';
  if (score >= 60) return 'text-amber-600';
  return 'text-red-600';
}

export function scoreBgColor(score: number): string {
  if (score >= 80) return 'bg-green-500';
  if (score >= 60) return 'bg-amber-500';
  return 'bg-red-500';
}

const PRODUCT_STATUS_META: Record<string, Omit<ProductStatusMeta, 'key'>> = {
  accepted: { label: 'Accepted', variant: 'success' },
  active: { label: 'Active', variant: 'success' },
  awaiting_eval_run: { label: 'Waiting for eval', variant: 'pending' },
  blocked: { label: 'Blocked', variant: 'error' },
  candidate: { label: 'Candidate', variant: 'pending' },
  completed: { label: 'Completed', variant: 'success' },
  degraded: { label: 'Degraded', variant: 'warning' },
  done: { label: 'Ready', variant: 'success' },
  error: { label: 'Failed', variant: 'error' },
  fail: { label: 'Failed', variant: 'error' },
  failed: { label: 'Failed', variant: 'error' },
  failure: { label: 'Failed', variant: 'error' },
  interrupted: { label: 'Interrupted', variant: 'warning' },
  live: { label: 'Live', variant: 'success' },
  mock: { label: 'Preview mode', variant: 'warning' },
  mixed: { label: 'Mixed', variant: 'warning' },
  no_change: { label: 'No change', variant: 'warning' },
  no_data: { label: 'No data', variant: 'pending' },
  no_op: { label: 'No change', variant: 'warning' },
  pending: { label: 'Pending', variant: 'pending' },
  pending_review: { label: 'Review required', variant: 'pending' },
  promote: { label: 'Promoted', variant: 'success' },
  promoted: { label: 'Promoted', variant: 'success' },
  queued: { label: 'Queued', variant: 'pending' },
  ready: { label: 'Ready', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'error' },
  rejected_human: { label: 'Rejected', variant: 'error' },
  rejected_invalid: { label: 'Rejected', variant: 'warning' },
  rejected_no_improvement: { label: 'Rejected', variant: 'warning' },
  rejected_noop: { label: 'No change', variant: 'warning' },
  rejected_quality: { label: 'Rejected', variant: 'warning' },
  rejected_regression: { label: 'Rejected', variant: 'warning' },
  rejected_safety: { label: 'Rejected', variant: 'warning' },
  review_required: { label: 'Review required', variant: 'pending' },
  rollback: { label: 'Rolled back', variant: 'warning' },
  rolled_back: { label: 'Rolled back', variant: 'warning' },
  running: { label: 'Running', variant: 'running' },
  stopped: { label: 'Interrupted', variant: 'warning' },
  success: { label: 'Success', variant: 'success' },
  warning: { label: 'Warning', variant: 'warning' },
  waiting: { label: 'Waiting', variant: 'pending' },
};

// Normalize backend and UI status variants so product copy stays consistent across surfaces.
export function normalizeStatusKey(status: string): string {
  return status.trim().toLowerCase().replace(/[\s-]+/g, '_');
}

function fallbackStatusLabel(status: string): string {
  const normalized = normalizeStatusKey(status).replaceAll('_', ' ');
  return normalized.replace(/\b\w/g, (char) => char.toUpperCase());
}

// Centralize operator-facing labels and variants without changing raw API status payloads.
export function getProductStatusMeta(status: string): ProductStatusMeta {
  const key = normalizeStatusKey(status);
  const meta = PRODUCT_STATUS_META[key];
  if (meta) {
    return { key, ...meta };
  }
  return {
    key,
    label: fallbackStatusLabel(status),
    variant: 'pending',
  };
}

// Keep call sites from rephrasing the same status in slightly different ways.
export function productStatusLabel(status: string): string {
  return getProductStatusMeta(status).label;
}

// Share the same severity mapping between badges, empty states, and page-local pills.
export function productStatusVariant(status: string): ProductStatusVariant {
  return getProductStatusMeta(status).variant;
}

export function statusVariant(status: string): ProductStatusVariant {
  const meta = getProductStatusMeta(status);
  if (meta.key !== normalizeStatusKey(status) || meta.variant !== 'pending') {
    return meta.variant;
  }

  switch (meta.key) {
    case 'completed':
    case 'accepted':
    case 'success':
    case 'active':
    case 'promote':
    case 'promoted':
    case 'live':
      return 'success';
    case 'rejected':
    case 'rejected_human':
    case 'failed':
    case 'fail':
    case 'error':
    case 'failure':
    case 'rollback':
    case 'rolled_back':
      return 'error';
    case 'abandon':
    case 'rejected_quality':
    case 'rejected_safety':
    case 'rejected_no_improvement':
    case 'rejected_regression':
    case 'rejected_invalid':
    case 'rejected_noop':
    case 'warning':
    case 'degraded':
    case 'mock':
    case 'mixed':
      return 'warning';
    case 'running':
      return 'running';
    case 'pending_review':
      return 'pending';
    default:
      return meta.variant;
  }
}

export function statusLabel(status: string): string {
  return productStatusLabel(status);
}
