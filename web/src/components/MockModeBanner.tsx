import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { AlertTriangle, RotateCcw, X } from 'lucide-react';
import { normalizeProviderFallback } from '../lib/provider-fallback';

const PREVIEW_MODE_TITLE = 'Preview mode is on';
const PREVIEW_MODE_DESCRIPTION = 'AgentLab is using simulated responses until live providers are ready.';
const FRONTEND_ONLY_TITLE = 'Frontend-only mode';
const FRONTEND_ONLY_DESCRIPTION =
  'AgentLab cannot reach the backend right now, so live status and saved actions may be unavailable.';
const WORKSPACE_INVALID_TITLE = 'Workspace needs attention';
const WORKSPACE_INVALID_DESCRIPTION =
  'Start the server from a valid AgentLab workspace, or pass an explicit workspace path.';
const OPTIMIZATION_ROUTE_PREFIXES = [
  '/dashboard',
  '/build',
  '/evals',
  '/optimize',
  '/live-optimize',
  '/improvements',
  '/studio',
  '/workbench',
];
const DISMISS_STORAGE_KEY = 'agentlab-mock-banner-dismissed';

interface MockModeHealthPayload {
  mock_mode?: boolean;
  mock_reasons?: unknown;
  real_provider_configured?: boolean;
  workspace_valid?: boolean;
  workspace?: unknown;
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
    }
  | {
      kind: 'workspace-invalid';
      currentPath: string | null;
      message: string;
      recoveryCommands: string[];
    };

interface WorkspaceHealthPayload {
  valid?: boolean;
  current_path?: string;
  message?: string;
  recovery_commands?: unknown;
}

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

function parseWorkspaceState(data: MockModeHealthPayload): {
  invalid: boolean;
  currentPath: string | null;
  message: string;
  recoveryCommands: string[];
} {
  const workspace = data.workspace && typeof data.workspace === 'object'
    ? data.workspace as WorkspaceHealthPayload
    : {};
  const invalid = data.workspace_valid === false || workspace.valid === false;
  const recoveryCommands = Array.isArray(workspace.recovery_commands)
    ? workspace.recovery_commands.filter(
        (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
      )
    : [];

  return {
    invalid,
    currentPath: typeof workspace.current_path === 'string' && workspace.current_path.trim()
      ? workspace.current_path
      : null,
    message: typeof workspace.message === 'string' && workspace.message.trim()
      ? workspace.message
      : WORKSPACE_INVALID_DESCRIPTION,
    recoveryCommands,
  };
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
        const workspaceState = parseWorkspaceState(data);
        if (workspaceState.invalid) {
          setBannerState({
            kind: 'workspace-invalid',
            currentPath: workspaceState.currentPath,
            message: workspaceState.message,
            recoveryCommands: workspaceState.recoveryCommands,
          });
          return;
        }

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
    let cancelled = false;
    const controller = new AbortController();

    fetchHealth(controller.signal).then(() => {
      if (cancelled) return;
    });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [refreshToken, fetchHealth]);

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

  if (
    bannerState.kind !== 'workspace-invalid'
    && (!shouldRenderOnRoute || bannerState.kind === 'hidden' || shouldHidePreviewNotice)
  ) {
    return null;
  }

  const isFrontendOnly = bannerState.kind === 'frontend-only';
  const isWorkspaceInvalid = bannerState.kind === 'workspace-invalid';
  const detail = bannerState.kind === 'preview' ? bannerState.detail : null;
  const fallback = bannerState.kind === 'preview'
    ? normalizeProviderFallback(true, bannerState.detail)
    : null;
  const isRateLimit = fallback?.category === 'rate-limit';
  const title = isWorkspaceInvalid
    ? WORKSPACE_INVALID_TITLE
    : isFrontendOnly
    ? FRONTEND_ONLY_TITLE
    : isRateLimit
      ? 'Provider rate limited'
      : PREVIEW_MODE_TITLE;
  const description = isWorkspaceInvalid
    ? WORKSPACE_INVALID_DESCRIPTION
    : isFrontendOnly
    ? FRONTEND_ONLY_DESCRIPTION
    : isRateLimit
      ? 'Your provider (e.g. Gemini) is temporarily rate-limiting requests. Drafts use fallback data until the limit clears. Retry in a minute or two.'
      : PREVIEW_MODE_DESCRIPTION;
  const colorClass = isWorkspaceInvalid
    ? 'border-red-300 bg-red-50 text-red-950'
    : isRateLimit
      ? 'border-orange-300 bg-orange-50 text-orange-950'
      : 'border-amber-300 bg-amber-50 text-amber-950';
  const iconClass = isWorkspaceInvalid
    ? 'text-red-700'
    : isRateLimit
      ? 'text-orange-700'
      : 'text-amber-700';
  const titleClass = isWorkspaceInvalid
    ? 'text-red-900'
    : isRateLimit
      ? 'text-orange-900'
      : 'text-amber-900';
  const bodyClass = isWorkspaceInvalid
    ? 'text-red-800'
    : isRateLimit
      ? 'text-orange-800'
      : 'text-amber-800';
  const buttonClass = isWorkspaceInvalid
    ? 'border-red-300 text-red-900 hover:bg-red-100'
    : isRateLimit
      ? 'border-orange-300 text-orange-900 hover:bg-orange-100'
      : 'border-amber-300 text-amber-900 hover:bg-amber-100';

  return (
    <div
      role="alert"
      className={`sticky top-0 z-50 flex items-center justify-between gap-3 border-b px-4 py-3 text-sm shadow-sm ${colorClass}`}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${iconClass}`} />
        <div className="min-w-0">
          <p className={`font-semibold ${titleClass}`}>{title}</p>
          <p className={`mt-0.5 text-xs ${bodyClass}`}>{description}</p>
          {isWorkspaceInvalid ? (
            <div className={`mt-1 space-y-1 text-xs ${bodyClass}`}>
              <p>{bannerState.message}</p>
              {bannerState.currentPath ? (
                <p>
                  Started from <code className="rounded border border-red-200 bg-white px-1 py-0.5 font-mono">{bannerState.currentPath}</code>
                </p>
              ) : null}
              {bannerState.recoveryCommands.length > 0 ? (
                <ul className="space-y-1">
                  {bannerState.recoveryCommands.map((command) => (
                    <li key={command}>
                      <code className="rounded border border-red-200 bg-white px-1 py-0.5 font-mono">{command}</code>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          {detail && !isRateLimit ? (
            <p className="mt-1 text-xs text-amber-800">{detail}</p>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {isFrontendOnly || isRateLimit || isWorkspaceInvalid ? (
          <button
            type="button"
            onClick={handleRetry}
            disabled={retrying}
            className={`inline-flex items-center gap-1.5 rounded-md border bg-white px-3 py-1.5 text-xs font-semibold transition disabled:opacity-50 ${buttonClass}`}
          >
            <RotateCcw className={`h-3.5 w-3.5 ${retrying ? 'animate-spin' : ''}`} />
            {retrying ? 'Checking…' : isWorkspaceInvalid ? 'Retry workspace check' : isRateLimit ? 'Retry now' : 'Retry connection'}
          </button>
        ) : (
          <Link
            to="/setup"
            className="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 transition hover:bg-amber-100"
          >
            Open Setup
          </Link>
        )}
        {isWorkspaceInvalid ? (
          <Link
            to="/setup"
            className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-semibold text-red-900 transition hover:bg-red-100"
          >
            Open Setup
          </Link>
        ) : null}
        {bannerState.kind === 'preview' && bannerState.realProviderConfigured ? (
          <button
            type="button"
            aria-label="Dismiss mock mode warning"
            onClick={handleDismiss}
            className={`rounded-md p-1.5 transition ${isRateLimit ? 'text-orange-700 hover:bg-orange-100' : 'text-amber-700 hover:bg-amber-100'}`}
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>
    </div>
  );
}
