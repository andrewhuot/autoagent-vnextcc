import { useState } from 'react';
import { exportAdk, exportCx } from '../../../lib/workbench-api';

interface ExportResult {
  filename: string;
  content: string;
  content_type: string;
  warnings?: string[];
}

interface DownloadLink {
  url: string;
  filename: string;
}

interface DeployTabProps {
  sessionId: string | null;
}

export function DeployTab({ sessionId }: DeployTabProps) {
  const [adkLoading, setAdkLoading] = useState(false);
  const [cxLoading, setCxLoading] = useState(false);
  const [adkError, setAdkError] = useState<string | null>(null);
  const [cxError, setCxError] = useState<string | null>(null);
  const [adkLink, setAdkLink] = useState<DownloadLink | null>(null);
  const [cxLink, setCxLink] = useState<DownloadLink | null>(null);
  const [adkWarnings, setAdkWarnings] = useState<string[]>([]);
  const [cxWarnings, setCxWarnings] = useState<string[]>([]);

  const handleExportAdk = async () => {
    if (!sessionId) return;
    setAdkLoading(true);
    setAdkError(null);
    setAdkLink(null);
    setAdkWarnings([]);
    try {
      const result = (await exportAdk(sessionId)) as ExportResult;
      if (result.warnings) setAdkWarnings(result.warnings);
      const blob = new Blob([result.content], { type: result.content_type });
      const url = URL.createObjectURL(blob);
      setAdkLink({ url, filename: result.filename });
    } catch (err) {
      setAdkError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setAdkLoading(false);
    }
  };

  const handleExportCx = async () => {
    if (!sessionId) return;
    setCxLoading(true);
    setCxError(null);
    setCxLink(null);
    setCxWarnings([]);
    try {
      const result = (await exportCx(sessionId)) as ExportResult;
      if (result.warnings) setCxWarnings(result.warnings);
      const blob = new Blob([result.content], { type: result.content_type });
      const url = URL.createObjectURL(blob);
      setCxLink({ url, filename: result.filename });
    } catch (err) {
      setCxError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setCxLoading(false);
    }
  };

  if (!sessionId) {
    return (
      <p className="rounded-md border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-500">
        Start a conversation to enable deployment.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* ADK Bundle */}
      <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
        <p className="mb-2 text-xs font-semibold text-slate-200">Export ADK Bundle</p>
        <p className="mb-3 text-[11px] text-slate-500">
          Generate a Google Agent Development Kit configuration bundle.
        </p>

        {adkWarnings.length > 0 ? (
          <div className="mb-2 rounded-md border border-yellow-800 bg-yellow-950/50 p-2">
            <p className="mb-1 text-[11px] font-semibold text-yellow-400">Warnings</p>
            <ul className="list-inside list-disc space-y-0.5">
              {adkWarnings.map((w, i) => (
                <li key={i} className="text-[11px] text-yellow-300">
                  {w}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {adkError ? (
          <p className="mb-2 rounded-md border border-red-800 bg-red-950/50 px-3 py-1.5 text-xs text-red-400">
            {adkError}
          </p>
        ) : null}

        {adkLink ? (
          <a
            href={adkLink.url}
            download={adkLink.filename}
            className="mb-2 block text-xs text-sky-400 underline hover:text-sky-300"
          >
            Download {adkLink.filename}
          </a>
        ) : null}

        <button
          type="button"
          onClick={() => void handleExportAdk()}
          disabled={adkLoading}
          className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {adkLoading ? 'Exporting…' : 'Export ADK Bundle'}
        </button>
      </div>

      {/* CX Bundle */}
      <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
        <p className="mb-2 text-xs font-semibold text-slate-200">Export CX Bundle</p>
        <p className="mb-3 text-[11px] text-slate-500">
          Generate a Dialogflow CX Agent Studio configuration bundle.
        </p>

        {cxWarnings.length > 0 ? (
          <div className="mb-2 rounded-md border border-yellow-800 bg-yellow-950/50 p-2">
            <p className="mb-1 text-[11px] font-semibold text-yellow-400">Warnings</p>
            <ul className="list-inside list-disc space-y-0.5">
              {cxWarnings.map((w, i) => (
                <li key={i} className="text-[11px] text-yellow-300">
                  {w}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {cxError ? (
          <p className="mb-2 rounded-md border border-red-800 bg-red-950/50 px-3 py-1.5 text-xs text-red-400">
            {cxError}
          </p>
        ) : null}

        {cxLink ? (
          <a
            href={cxLink.url}
            download={cxLink.filename}
            className="mb-2 block text-xs text-sky-400 underline hover:text-sky-300"
          >
            Download {cxLink.filename}
          </a>
        ) : null}

        <button
          type="button"
          onClick={() => void handleExportCx()}
          disabled={cxLoading}
          className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {cxLoading ? 'Exporting…' : 'Export CX Bundle'}
        </button>
      </div>

      {/* Cloud Deploy placeholder */}
      <div className="rounded-md border border-slate-800 bg-slate-900/40 p-3 opacity-50">
        <p className="mb-1 text-xs font-semibold text-slate-400">Cloud Deploy</p>
        <p className="text-[11px] text-slate-600">
          One-click deploy to Vertex AI / Cloud Run — coming soon.
        </p>
        <button
          type="button"
          disabled
          className="mt-2 cursor-not-allowed rounded-md bg-slate-800 px-3 py-1.5 text-xs text-slate-600"
        >
          Deploy to Cloud (coming soon)
        </button>
      </div>
    </div>
  );
}
