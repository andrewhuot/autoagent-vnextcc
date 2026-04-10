/**
 * Normalizes raw provider fallback reasons into structured, user-facing messaging.
 *
 * When a provider like Google/Gemini rate-limits a request (HTTP 429), the backend
 * sets mock_mode=true with a raw error string as mock_reason. This helper detects
 * rate-limit patterns and returns actionable, product-quality copy so the UI can
 * distinguish "provider is temporarily busy" from "no provider configured".
 */

export type FallbackCategory = 'rate-limit' | 'auth' | 'generic';

export interface NormalizedFallback {
  /** Broad category for UI branching. */
  category: FallbackCategory;
  /** Short label for badges and pills (e.g. "Rate limited"). */
  badge: string;
  /** One-line human explanation. */
  headline: string;
  /** Actionable next-step guidance for the user. */
  guidance: string;
  /** Whether a "Retry" affordance makes sense for this category. */
  retryable: boolean;
}

const RATE_LIMIT_PATTERN = /429|rate[\s\-_]?limit|too many requests|quota exceeded|resource[\s_]?exhausted/i;
const AUTH_PATTERN = /401|403|auth|unauthorized|forbidden|invalid.*key/i;

/**
 * Inspects a raw `mock_reason` string and returns normalized, user-facing messaging.
 *
 * Returns `null` when mock_mode is false or mock_reason is empty/absent,
 * signalling the UI should render the normal live-session state.
 */
export function normalizeProviderFallback(
  mockMode: boolean,
  mockReason: string | null | undefined,
): NormalizedFallback | null {
  if (!mockMode) return null;

  const reason = (mockReason ?? '').trim();
  if (!reason) {
    return {
      category: 'generic',
      badge: 'Fallback',
      headline: 'This draft was generated in fallback mode.',
      guidance: 'Check Setup to verify your provider keys, or try again later.',
      retryable: false,
    };
  }

  if (RATE_LIMIT_PATTERN.test(reason)) {
    return {
      category: 'rate-limit',
      badge: 'Rate limited',
      headline: 'Your provider is temporarily rate-limiting requests.',
      guidance:
        'This draft was generated using fallback data because the provider (e.g. Gemini) returned a rate-limit error. ' +
        'You can retry in a minute or two, or export/save what you have now.',
      retryable: true,
    };
  }

  if (AUTH_PATTERN.test(reason)) {
    return {
      category: 'auth',
      badge: 'Auth error',
      headline: 'Provider authentication failed.',
      guidance: 'Check your API key in Setup. The key may be invalid or expired.',
      retryable: false,
    };
  }

  return {
    category: 'generic',
    badge: 'Fallback',
    headline: 'This draft was generated in fallback mode.',
    guidance: reason.length > 200
      ? 'An unexpected error occurred. Check Setup to verify your provider keys.'
      : reason,
    retryable: false,
  };
}

/**
 * Convenience: extracts a short session-state label for summary pills and badges.
 */
export function fallbackBadgeLabel(
  mockMode: boolean,
  mockReason: string | null | undefined,
): string {
  const fb = normalizeProviderFallback(mockMode, mockReason);
  return fb?.badge ?? 'Live';
}
