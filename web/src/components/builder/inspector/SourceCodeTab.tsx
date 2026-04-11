import { useState } from 'react';
import { exportAdk, exportCx } from '../../../lib/workbench-api';

type SubTab = 'adk' | 'cx';

interface ExportResult {
  filename: string;
  content: string;
  content_type: string;
  warnings?: string[];
}

interface SourceCodeTabProps {
  sessionId: string | null;
}

export function SourceCodeTab({ sessionId }: SourceCodeTabProps) {
  const [subTab, setSubTab] = useState<SubTab>('adk');
  const [adkResult, setAdkResult] = useState<ExportResult | null>(null);
  const [cxResult, setCxResult] = useState<ExportResult | null>(null);
  const [adkLoading, setAdkLoading] = useState(false);
  const [cxLoading, setCxLoading] = useState(false);
  const [adkError, setAdkError] = useState<string | null>(null);
  const [cxError, setCxError] = useState<string | null>(null);

  if (!sessionId) {
    return (
      <p className="rounded-md border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-500">
        No active session — start a conversation to generate source code.
      </p>
    );
  }

  const handleSelectSubTab = async (tab: SubTab) => {
    setSubTab(tab);
    if (tab === 'adk' && !adkResult && !adkLoading) {
      setAdkLoading(true);
      setAdkError(null);
      try {
        const res = await exportAdk(sessionId);
        setAdkResult(res as ExportResult);
      } catch (err) {
        setAdkError(err instanceof Error ? err.message : 'Export failed');
      } finally {
        setAdkLoading(false);
      }
    }
    if (tab === 'cx' && !cxResult && !cxLoading) {
      setCxLoading(true);
      setCxError(null);
      try {
        const res = await exportCx(sessionId);
        setCxResult(res as ExportResult);
      } catch (err) {
        setCxError(err instanceof Error ? err.message : 'Export failed');
      } finally {
        setCxLoading(false);
      }
    }
  };

  // Trigger initial fetch for the default sub-tab on first render
  if (subTab === 'adk' && !adkResult && !adkLoading && !adkError) {
    void handleSelectSubTab('adk');
  }

  const activeResult = subTab === 'adk' ? adkResult : cxResult;
  const activeLoading = subTab === 'adk' ? adkLoading : cxLoading;
  const activeError = subTab === 'adk' ? adkError : cxError;

  return (
    <div className="flex flex-col gap-3">
      {/* Sub-tab toggle */}
      <div className="flex gap-1">
        {(['adk', 'cx'] as SubTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => void handleSelectSubTab(tab)}
            className={
              subTab === tab
                ? 'rounded-md bg-slate-700 px-3 py-1 text-[11px] font-medium text-slate-100'
                : 'rounded-md bg-slate-900 px-3 py-1 text-[11px] text-slate-500 transition hover:bg-slate-800 hover:text-slate-300'
            }
          >
            {tab === 'adk' ? 'ADK' : 'CX Studio'}
          </button>
        ))}
      </div>

      {activeError ? (
        <p className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-xs text-red-400">
          {activeError}
        </p>
      ) : null}

      {activeLoading ? (
        <p className="rounded-md border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-500">
          Generating…
        </p>
      ) : null}

      {activeResult && !activeLoading ? (
        <div className="flex flex-col gap-2">
          {activeResult.warnings && activeResult.warnings.length > 0 ? (
            <div className="rounded-md border border-yellow-800 bg-yellow-950/50 p-2">
              <p className="mb-1 text-[11px] font-semibold text-yellow-400">Warnings</p>
              <ul className="list-inside list-disc space-y-0.5">
                {activeResult.warnings.map((w, i) => (
                  <li key={i} className="text-[11px] text-yellow-300">
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <p className="text-[11px] text-slate-500">{activeResult.filename}</p>
          <pre className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap rounded-md border border-slate-700 bg-slate-950 p-3 font-mono text-[11px] text-slate-200">
            {activeResult.content}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
