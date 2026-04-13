import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

interface HealthSnapshot {
  mock_mode?: boolean;
  mock_reasons?: string[];
  active_provider?: string | null;
  active_model?: string | null;
  real_provider_configured?: boolean;
}

const POLL_INTERVAL_MS = 15_000;

function formatProviderLabel(provider?: string | null): string {
  if (!provider) return 'Provider';
  const lower = provider.toLowerCase();
  if (lower === 'openai') return 'OpenAI';
  if (lower === 'anthropic') return 'Anthropic';
  if (lower === 'google') return 'Gemini';
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

/**
 * Permanent at-a-glance indicator showing whether the backend is currently
 * running on a real LLM provider or in mock/preview mode. Polls /api/health
 * and updates without a hard refresh so operators always see the truth.
 */
export function ProviderModePill() {
  const [snapshot, setSnapshot] = useState<HealthSnapshot | null>(null);
  const [reachable, setReachable] = useState<boolean>(true);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      try {
        const res = await fetch('/api/health', { signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as HealthSnapshot;
        if (!cancelled) {
          setSnapshot(data);
          setReachable(true);
        }
      } catch {
        if (!cancelled) setReachable(false);
      }
    }

    load();
    const handle = window.setInterval(load, POLL_INTERVAL_MS);
    const onSettings = () => load();
    window.addEventListener('agentlab:settings-updated', onSettings);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(handle);
      window.removeEventListener('agentlab:settings-updated', onSettings);
    };
  }, []);

  if (!reachable) {
    return (
      <Link
        to="/setup"
        title="Backend unreachable. Click to open Setup."
        className="hidden items-center gap-1.5 rounded-full border border-gray-300 bg-white px-2.5 py-1 text-[11px] font-medium text-gray-600 transition hover:bg-gray-50 sm:inline-flex"
      >
        <span aria-hidden className="h-2 w-2 rounded-full bg-gray-400" />
        Offline
      </Link>
    );
  }

  if (snapshot === null) {
    return (
      <span
        className="hidden items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-medium text-gray-400 sm:inline-flex"
        aria-label="Loading provider mode"
      >
        <span aria-hidden className="h-2 w-2 rounded-full bg-gray-300" />
        Checking…
      </span>
    );
  }

  const isMock = snapshot.mock_mode === true;
  const provider = formatProviderLabel(snapshot.active_provider);
  const model = (snapshot.active_model || '').trim();
  const tooltip = isMock
    ? `Mock mode${
        snapshot.mock_reasons && snapshot.mock_reasons.length > 0
          ? ` — ${snapshot.mock_reasons[0]}`
          : ''
      }. Click to open Setup.`
    : `Live · ${provider}${model ? ` · ${model}` : ''}. Click to open Setup.`;

  return (
    <Link
      to="/setup"
      title={tooltip}
      data-testid="provider-mode-pill"
      data-mode={isMock ? 'mock' : 'live'}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition ${
        isMock
          ? 'border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100'
          : 'border-emerald-300 bg-emerald-50 text-emerald-900 hover:bg-emerald-100'
      }`}
    >
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${isMock ? 'bg-amber-500' : 'bg-emerald-500'}`}
      />
      {isMock ? (
        <span>
          Mock <span className="text-amber-700">· preview</span>
        </span>
      ) : (
        <span>
          Live <span className="text-emerald-700">· {model || provider}</span>
        </span>
      )}
    </Link>
  );
}
