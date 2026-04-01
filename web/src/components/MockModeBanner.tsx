import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';

const BANNER_COPY = 'Running in mock mode — add API keys for live optimization';
const OPTIMIZATION_ROUTE_PREFIXES = ['/dashboard', '/evals', '/optimize', '/live-optimize', '/improvements'];

interface MockModeHealthPayload {
  mock_mode?: boolean;
  mock_reasons?: unknown;
  real_provider_configured?: boolean;
}

function isOptimizationRoute(pathname: string): boolean {
  return OPTIMIZATION_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function MockModeBanner() {
  const location = useLocation();
  const [mockMode, setMockMode] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const shouldRenderOnRoute = useMemo(
    () => isOptimizationRoute(location.pathname),
    [location.pathname]
  );

  useEffect(() => {
    const onSettingsUpdated = () => setRefreshToken((value) => value + 1);
    window.addEventListener('agentlab:settings-updated', onSettingsUpdated);
    return () => window.removeEventListener('agentlab:settings-updated', onSettingsUpdated);
  }, []);

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

        setMockMode(data?.mock_mode === true || reasons.length > 0);
        setDetail(reasons.find((value) => value !== BANNER_COPY) ?? null);
      })
      .catch(() => {
        if (!cancelled) {
          setMockMode(false);
          setDetail(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [refreshToken, shouldRenderOnRoute]);

  if (!shouldRenderOnRoute || !mockMode) {
    return null;
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

      <Link
        to="/setup"
        className="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 transition hover:bg-amber-100"
      >
        Exit Mock Mode
      </Link>
    </div>
  );
}
