import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { AlertTriangle, RotateCcw, X } from 'lucide-react';

const PREVIEW_MODE_TITLE = 'Preview mode is on';
const PREVIEW_MODE_DESCRIPTION = 'AgentLab is using simulated responses until live providers are ready.';
const FRONTEND_ONLY_TITLE = 'Frontend-only mode';
const FRONTEND_ONLY_DESCRIPTION =
  'AgentLab cannot reach the backend right now, so live status and saved actions may be unavailable.';
const OPTIMIZATION_ROUTE_PREFIXES = ['/dashboard', '/build', '/evals', '/optimize', '/live-optimize', '/improvements', '/studio'];
const DISMISS_STORAGE_KEY = 'agentlab-mock-banner-dismissed';

interface MockModeHealthPayload {
  mock_mode?: boolean;
  mock_reasons?: unknown;
  real_provider_configured?: boolean;
}

type ShellBannerState =
  | {
      kind: 'hidden';
    }
  | {
      kind: 'preview';
      detail: string | null;
      realProviderConfigured: boolean;
    }
  | {
      kind: 'frontend-only';
    };

function isOptimizationRoute(pathname: string): boolean {
  return OPTIMIZATION_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function isDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

export function MockModeBanner() {
  const location = useLocation();
  const [bannerState, setBannerState] = useState<ShellBannerState>({ kind: 'hidden' });
  const [dismissed, setDismissed] = useState(isDismissed);
  const [refreshToken, setRefreshToken] = useState(0);
  const [retrying, setRetrying] = useState(false);

  const shouldRenderOnRoute = useMemo(
    () => isOptimizationRoute(location.pathname),
    [location.pathname]
  );

  useEffect(() => {
    const onSettingsUpdated = () => setRefreshToken((value) => value + 1);
    window.addEventListener('agentlab:settings-updated', onSettingsUpdated);
    return () => window.removeEventListener('agentlab:settings-updated', onSettingsUpdated);
  }, []);

  const fetchHealth = useCallback((signal?: AbortSignal) => {
    return fetch('/api/health', signal ? { signal } : undefined)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Health request failed: ${res.status}`);
        }
        return res.json();
      })
      .then((data: MockModeHealthPayload) => {
        const reasons = Array.isArray(data?.mock_reasons)
          ? data.mock_reasons.filter(
              (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
            )
          : [];

        const isPreviewMode = data?.mock_mode === true || reasons.length > 0;
        if (!isPreviewMode) {
          setBannerState({ kind: 'hidden' });
          return;
        }

        setBannerState({
          kind: 'preview',
          detail: reasons[0] ?? null,
          realProviderConfigured: data?.real_provider_configured === true,
        });
      })
      .catch(() => {
        setBannerState({ kind: 'frontend-only' });
      });
  }, []);

  useEffect(() => {
    if (!shouldRenderOnRoute) {
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    fetchHealth(controller.signal).then(() => {
      if (cancelled) return;
    });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [refreshToken, shouldRenderOnRoute, fetchHealth]);

  const handleDismiss = useCallback(() => {
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISS_STORAGE_KEY, '1');
    } catch {
      // ignore storage access failures
    }
  }, []);

  const handleRetry = useCallback(async () => {
    setRetrying(true);
    await fetchHealth();
    setRetrying(false);
  }, [fetchHealth]);

  const shouldHidePreviewNotice = bannerState.kind === 'preview' && dismissed;

  if (!shouldRenderOnRoute || bannerState.kind === 'hidden' || shouldHidePreviewNotice) {
    return null;
  }

  const isFrontendOnly = bannerState.kind === 'frontend-only';
  const title = isFrontendOnly ? FRONTEND_ONLY_TITLE : PREVIEW_MODE_TITLE;
  const description = isFrontendOnly ? FRONTEND_ONLY_DESCRIPTION : PREVIEW_MODE_DESCRIPTION;
  const detail = bannerState.kind === 'preview' ? bannerState.detail : null;

  return (
    <div
      role="alert"
      className="sticky top-0 z-50 flex items-center justify-between gap-3 border-b border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950 shadow-sm"
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
        <div className="min-w-0">
          <p className="font-semibold text-amber-900">{title}</p>
          <p className="mt-0.5 text-xs text-amber-800">{description}</p>
          {detail ? (
            <p className="mt-1 text-xs text-amber-800">{detail}</p>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {isFrontendOnly ? (
          <button
            type="button"
            onClick={handleRetry}
            disabled={retrying}
            className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 transition hover:bg-amber-100 disabled:opacity-50"
          >
            <RotateCcw className={`h-3.5 w-3.5 ${retrying ? 'animate-spin' : ''}`} />
            {retrying ? 'Checking…' : 'Retry connection'}
          </button>
        ) : (
          <Link
            to="/setup"
            className="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 transition hover:bg-amber-100"
          >
            Open Setup
          </Link>
        )}
        {bannerState.kind === 'preview' && bannerState.realProviderConfigured ? (
          <button
            type="button"
            aria-label="Dismiss mock mode warning"
            onClick={handleDismiss}
            className="rounded-md p-1.5 text-amber-700 transition hover:bg-amber-100"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>
    </div>
  );
}
