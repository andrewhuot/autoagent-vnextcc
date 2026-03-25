import { useState } from 'react';
import { Wrench, Loader2, CheckCircle, XCircle } from 'lucide-react';

interface FixButtonProps {
  failureFamily: string;
  failureCount: number;
  onComplete?: () => void;
}

const RUNBOOK_MAP: Record<string, string> = {
  routing_error: 'fix-retrieval-grounding',
  safety_violation: 'tighten-safety-policy',
  quality_issue: 'enhance-few-shot-examples',
  latency_problem: 'reduce-tool-latency',
  cost_overrun: 'optimize-cost-efficiency',
  tool_error: 'reduce-tool-latency',
  hallucination: 'fix-retrieval-grounding',
};

export function FixButton({ failureFamily, failureCount, onComplete }: FixButtonProps) {
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runbook = RUNBOOK_MAP[failureFamily];

  if (!runbook) {
    return null; // No runbook available for this failure family
  }

  const handleApply = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/quickfix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ failure_family: failureFamily }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || 'Failed to apply fix');
      }

      const result = await response.json();
      setSuccess(result.success);

      if (result.success) {
        setTimeout(() => {
          setShowModal(false);
          setSuccess(false);
          onComplete?.();
        }, 2000);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        onClick={() => setShowModal(true)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-blue-300 bg-blue-50 px-2.5 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100"
      >
        {loading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : success ? (
          <CheckCircle className="h-3.5 w-3.5 text-green-600" />
        ) : error ? (
          <XCircle className="h-3.5 w-3.5 text-red-600" />
        ) : (
          <Wrench className="h-3.5 w-3.5" />
        )}
        <span>Fix</span>
      </button>

      {/* Confirmation Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-xl">
            <h3 className="text-lg font-semibold text-gray-900">Apply Runbook</h3>
            <p className="mt-2 text-sm text-gray-600">
              Apply <span className="font-medium text-gray-900">'{runbook}'</span> and run 1 optimization cycle to fix{' '}
              {failureCount} {failureFamily} failures?
            </p>

            {error && (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {error}
              </div>
            )}

            {success && (
              <div className="mt-3 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
                Fix applied successfully! Optimization cycle complete.
              </div>
            )}

            <div className="mt-6 flex gap-3">
              <button
                onClick={() => {
                  setShowModal(false);
                  setError(null);
                  setSuccess(false);
                }}
                disabled={loading}
                className="flex-1 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                onClick={handleApply}
                disabled={loading || success}
                className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-60"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Applying...
                  </span>
                ) : success ? (
                  'Applied'
                ) : (
                  'Apply & Optimize'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
