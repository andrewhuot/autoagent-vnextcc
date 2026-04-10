import { describe, expect, it } from 'vitest';
import {
  normalizeProviderFallback,
  fallbackBadgeLabel,
} from './provider-fallback';

describe('normalizeProviderFallback', () => {
  it('returns null when mock_mode is false', () => {
    expect(normalizeProviderFallback(false, 'HTTP Error 429: Too Many Requests')).toBeNull();
  });

  it('returns null when mock_mode is false even with empty reason', () => {
    expect(normalizeProviderFallback(false, '')).toBeNull();
  });

  // --- Rate-limit detection ---

  it('detects HTTP 429 error strings as rate-limit', () => {
    const result = normalizeProviderFallback(true, 'HTTP Error 429: Too Many Requests');
    expect(result).not.toBeNull();
    expect(result!.category).toBe('rate-limit');
    expect(result!.badge).toBe('Rate limited');
    expect(result!.retryable).toBe(true);
    expect(result!.headline).toContain('rate-limiting');
    expect(result!.guidance).toContain('retry');
  });

  it('detects "rate limit" text as rate-limit', () => {
    const result = normalizeProviderFallback(true, 'Provider rate limit exceeded');
    expect(result!.category).toBe('rate-limit');
    expect(result!.retryable).toBe(true);
  });

  it('detects "too many requests" as rate-limit (case insensitive)', () => {
    const result = normalizeProviderFallback(true, 'Too Many Requests from provider');
    expect(result!.category).toBe('rate-limit');
  });

  it('detects "quota exceeded" as rate-limit', () => {
    const result = normalizeProviderFallback(true, 'Quota exceeded for model gemini-2.5-pro');
    expect(result!.category).toBe('rate-limit');
  });

  it('detects "resource exhausted" as rate-limit', () => {
    const result = normalizeProviderFallback(true, 'RESOURCE_EXHAUSTED: rate limit');
    expect(result!.category).toBe('rate-limit');
  });

  // --- Auth detection ---

  it('detects 401 as auth error', () => {
    const result = normalizeProviderFallback(true, 'HTTP Error 401: Unauthorized');
    expect(result!.category).toBe('auth');
    expect(result!.badge).toBe('Auth error');
    expect(result!.retryable).toBe(false);
  });

  it('detects 403 as auth error', () => {
    const result = normalizeProviderFallback(true, 'HTTP 403 Forbidden');
    expect(result!.category).toBe('auth');
  });

  it('detects "invalid key" as auth error', () => {
    const result = normalizeProviderFallback(true, 'Invalid API key provided');
    expect(result!.category).toBe('auth');
  });

  // --- Generic fallback ---

  it('returns generic fallback for unknown reasons', () => {
    const result = normalizeProviderFallback(true, 'No configured builder LLM router is available.');
    expect(result!.category).toBe('generic');
    expect(result!.badge).toBe('Fallback');
    expect(result!.retryable).toBe(false);
    expect(result!.guidance).toContain('No configured builder LLM router');
  });

  it('returns generic fallback with default copy for empty reason', () => {
    const result = normalizeProviderFallback(true, '');
    expect(result!.category).toBe('generic');
    expect(result!.guidance).toContain('Setup');
  });

  it('returns generic fallback for null reason', () => {
    const result = normalizeProviderFallback(true, null);
    expect(result!.category).toBe('generic');
  });

  it('returns generic fallback for undefined reason', () => {
    const result = normalizeProviderFallback(true, undefined);
    expect(result!.category).toBe('generic');
  });
});

describe('fallbackBadgeLabel', () => {
  it('returns "Live" when mock_mode is false', () => {
    expect(fallbackBadgeLabel(false, '')).toBe('Live');
  });

  it('returns "Rate limited" for 429 reasons', () => {
    expect(fallbackBadgeLabel(true, 'HTTP Error 429: Too Many Requests')).toBe('Rate limited');
  });

  it('returns "Fallback" for generic reasons', () => {
    expect(fallbackBadgeLabel(true, 'Some unknown error')).toBe('Fallback');
  });

  it('returns "Auth error" for auth reasons', () => {
    expect(fallbackBadgeLabel(true, 'HTTP Error 401: Unauthorized')).toBe('Auth error');
  });
});
