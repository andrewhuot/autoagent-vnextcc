import { describe, expect, it } from 'vitest';
import { getProductStatusMeta, statusLabel, statusVariant } from './utils';

describe('product status language', () => {
  it('normalizes key operator statuses into consistent labels and variants', () => {
    expect(getProductStatusMeta('blocked')).toMatchObject({
      label: 'Blocked',
      variant: 'error',
    });
    expect(getProductStatusMeta('ready')).toMatchObject({
      label: 'Ready',
      variant: 'success',
    });
    expect(getProductStatusMeta('interrupted')).toMatchObject({
      label: 'Interrupted',
      variant: 'warning',
    });
    expect(getProductStatusMeta('review_required')).toMatchObject({
      label: 'Review required',
      variant: 'pending',
    });
    expect(getProductStatusMeta('promoted')).toMatchObject({
      label: 'Promoted',
      variant: 'success',
    });
    expect(getProductStatusMeta('rejected')).toMatchObject({
      label: 'Rejected',
      variant: 'error',
    });
    expect(getProductStatusMeta('no_data')).toMatchObject({
      label: 'No data',
      variant: 'pending',
    });
    expect(getProductStatusMeta('mock')).toMatchObject({
      label: 'Preview mode',
      variant: 'warning',
    });
  });

  it('keeps existing aliases readable without page-specific wording', () => {
    expect(statusLabel('pending_review')).toBe('Review required');
    expect(statusVariant('pending_review')).toBe('pending');
    expect(statusLabel('rolled_back')).toBe('Rolled back');
    expect(statusVariant('rolled_back')).toBe('warning');
    expect(statusLabel('rejected_noop')).toBe('No change');
    expect(statusVariant('rejected_noop')).toBe('warning');
    expect(statusLabel('awaiting_eval_run')).toBe('Waiting for eval');
    expect(statusVariant('awaiting_eval_run')).toBe('pending');
  });
});
