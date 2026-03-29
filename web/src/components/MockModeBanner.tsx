import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { AlertTriangle, X } from 'lucide-react';

const BANNER_COPY = 'Running in mock mode — add API keys for live optimization';
const DISMISS_KEY = 'autoagent.mock_mode_banner.dismissed';
const OPTIMIZATION_ROUTE_PREFIXES = ['/dashboard', '/evals', '/optimize', '/live-optimize', '/experiments'];

interface MockModeHealthPayload {
  mock_mode?: boolean;
  mock_reasons?: unknown;
  real_provider_configured?: boolean;
}

function isOptimizationRoute(pathname: string): boolean {
  return OPTIMIZATION_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function readDismissedState(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === 'true';
  } catch {
    return false;
  }
}

function persistDismissedState(value: boolean): void {
  try {
    if (value) {
      window.localStorage.setItem(DISMISS_KEY, 'true');
      return;
    }
    window.localStorage.removeItem(DISMISS_KEY);
  } catch {
    // Ignore storage errors and keep rendering from in-memory state.
  }
}

export function MockModeBanner() {
  const location = useLocation();
  const [mockMode, setMockMode] = useState(false);
  const [canDismiss, setCanDismiss] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(() => readDismissedState());

  const shouldRenderOnRoute = useMemo(
    () => isOptimizationRoute(location.pathname),
    [location.pathname]
  );

  useEffect(() => {
    if (!shouldRenderOnRoute) {
      return;
    }

    let cancelled = false;

    fetch('/api/health')
      .then((res) => res.json())
      .then((data: MockModeHealthPayload) => {
        if (cancelled) {
          return;
        }

        const reasons = Array.isArray(data?.mock_reasons)
          ? data.mock_reasons.filter(
              (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
            )
          : [];
        const providerConfigured = data?.real_provider_configured === true;

        setMockMode(data?.mock_mode === true || reasons.length > 0);
        setCanDismiss(providerConfigured);
        setDetail(reasons.find((value) => value !== BANNER_COPY) ?? null);

        if (!providerConfigured) {
          persistDismissedState(false);
          setDismissed(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMockMode(false);
          setCanDismiss(false);
          setDetail(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [shouldRenderOnRoute]);

  if (!shouldRenderOnRoute || !mockMode || (canDismiss && dismissed)) {
    return null;
  }

  function handleDismiss() {
    if (!canDismiss) {
      return;
    }
    persistDismissedState(true);
    setDismissed(true);
  }

  return (
    <div
      role="alert"
      className="sticky top-0 z-50 flex items-center justify-between gap-3 border-b border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950 shadow-sm"
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
        <div className="min-w-0">
          <p className="font-semibold text-amber-900">{BANNER_COPY}</p>
          {detail ? (
            <p className="mt-0.5 text-xs text-amber-800">{detail}</p>
          ) : null}
        </div>
      </div>

      {canDismiss ? (
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Dismiss mock mode warning"
          className="rounded-md p-1 text-amber-800 transition hover:bg-amber-100 hover:text-amber-950"
        >
          <X className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
