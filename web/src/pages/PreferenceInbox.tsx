import { useState, useEffect } from 'react';
import { ThumbsUp, Plus, Download, BarChart2, X } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { formatTimestamp } from '../lib/utils';

const API_BASE = '/api';

interface PreferencePair {
  id: string;
  input_text: string;
  chosen: string;
  rejected: string;
  source: string;
  confidence: number;
  created_at: string;
}

interface PreferenceStats {
  total_pairs: number;
  by_source: Record<string, number>;
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

const defaultForm = {
  input_text: '',
  chosen: '',
  rejected: '',
  source: 'human',
  confidence: 0.9,
};

export function PreferenceInbox() {
  const [pairs, setPairs] = useState<PreferencePair[]>([]);
  const [stats, setStats] = useState<PreferenceStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...defaultForm });
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    Promise.all([
      fetchJson<PreferencePair[]>('/preferences/pairs'),
      fetchJson<PreferenceStats>('/preferences/stats'),
    ])
      .then(([p, s]) => { setPairs(p); setStats(s); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  async function submitPair() {
    if (!form.input_text.trim() || !form.chosen.trim() || !form.rejected.trim()) return;
    setSubmitting(true);
    try {
      const created = await fetchJson<PreferencePair>('/preferences/pairs', {
        method: 'POST',
        body: JSON.stringify(form),
      });
      setPairs((prev) => [created, ...prev]);
      setStats((prev) => prev
        ? {
            total_pairs: prev.total_pairs + 1,
            by_source: {
              ...prev.by_source,
              [form.source]: (prev.by_source[form.source] ?? 0) + 1,
            },
          }
        : prev
      );
      setForm({ ...defaultForm });
      setShowForm(false);
    } catch {
      // keep form open on error
    } finally {
      setSubmitting(false);
    }
  }

  async function exportPairs() {
    setExporting(true);
    try {
      await fetchJson('/preferences/export', { method: 'POST' });
    } catch {
      // ignore
    } finally {
      setExporting(false);
    }
  }

  function field(key: keyof typeof form, value: string | number) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Preference Inbox"
        description="Collect and manage human preference pairs used for RLHF fine-tuning and reward model training."
        actions={
          <div className="flex gap-2">
            <button
              onClick={exportPairs}
              disabled={exporting}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              {exporting ? 'Exporting...' : 'Export'}
            </button>
            <button
              onClick={() => setShowForm(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              <Plus className="h-4 w-4" />
              Add Pair
            </button>
          </div>
        }
      />

      {/* Stats */}
      {stats && (
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-2">
              <BarChart2 className="h-4 w-4 text-gray-400" />
              <p className="text-xs text-gray-500">Total Pairs</p>
            </div>
            <p className="mt-1 text-2xl font-semibold text-gray-900">{stats.total_pairs}</p>
          </div>
          {Object.entries(stats.by_source).map(([src, count]) => (
            <div key={src} className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-xs text-gray-500 capitalize">{src}</p>
              <p className="mt-1 text-2xl font-semibold text-gray-900">{count}</p>
            </div>
          ))}
        </section>
      )}

      {/* Create form */}
      {showForm && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">New Preference Pair</h3>
            <button
              onClick={() => setShowForm(false)}
              className="rounded p-1 text-gray-500 hover:bg-gray-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Input Text *</label>
              <textarea
                rows={2}
                value={form.input_text}
                onChange={(e) => field('input_text', e.target.value)}
                placeholder="The prompt or context shown to the model..."
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs text-gray-500">Chosen (preferred) *</label>
                <textarea
                  rows={3}
                  value={form.chosen}
                  onChange={(e) => field('chosen', e.target.value)}
                  placeholder="The better response..."
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">Rejected *</label>
                <textarea
                  rows={3}
                  value={form.rejected}
                  onChange={(e) => field('rejected', e.target.value)}
                  placeholder="The worse response..."
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs text-gray-500">Source</label>
                <select
                  value={form.source}
                  onChange={(e) => field('source', e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                >
                  <option value="human">human</option>
                  <option value="synthetic">synthetic</option>
                  <option value="model">model</option>
                  <option value="expert">expert</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">
                  Confidence: {form.confidence.toFixed(2)}
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={form.confidence}
                  onChange={(e) => field('confidence', parseFloat(e.target.value))}
                  className="mt-1 w-full"
                />
              </div>
            </div>
          </div>

          <div className="mt-4 flex justify-end">
            <button
              onClick={submitPair}
              disabled={submitting || !form.input_text.trim() || !form.chosen.trim() || !form.rejected.trim()}
              className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
            >
              {submitting ? 'Submitting...' : 'Submit Pair'}
            </button>
          </div>
        </section>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Pairs list */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-900">
          Preference Pairs {pairs.length > 0 && `(${pairs.length})`}
        </h3>

        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-lg border border-gray-200 bg-gray-100" />
            ))}
          </div>
        ) : pairs.length === 0 ? (
          <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
            No preference pairs yet. Add one to start training data collection.
          </div>
        ) : (
          <div className="space-y-2">
            {pairs.map((p) => (
              <div key={p.id} className="rounded-lg border border-gray-200 bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-medium text-gray-900 line-clamp-1">{p.input_text}</p>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">{p.source}</span>
                    <span className="text-xs text-gray-500">{(p.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-green-100 bg-green-50 px-3 py-2">
                    <div className="mb-1 flex items-center gap-1">
                      <ThumbsUp className="h-3 w-3 text-green-600" />
                      <span className="text-[10px] font-medium text-green-700">Chosen</span>
                    </div>
                    <p className="line-clamp-2 text-xs text-gray-700">{p.chosen}</p>
                  </div>
                  <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-2">
                    <div className="mb-1 flex items-center gap-1">
                      <span className="text-[10px] font-medium text-red-700">Rejected</span>
                    </div>
                    <p className="line-clamp-2 text-xs text-gray-700">{p.rejected}</p>
                  </div>
                </div>
                <p className="mt-2 text-[11px] text-gray-400">{formatTimestamp(p.created_at)}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default PreferenceInbox;
