import { useState } from 'react';
import { Columns3, Settings2 } from 'lucide-react';
import { useConfigDiff, useConfigs, useConfigShow } from '../lib/api';
import { EmptyState } from '../components/EmptyState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { YamlViewer } from '../components/YamlViewer';
import { YamlDiff } from '../components/YamlDiff';
import { formatTimestamp, statusVariant } from '../lib/utils';

export function Configs() {
  const { data: configs, isLoading, isError, refetch } = useConfigs();
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compareA, setCompareA] = useState<number | null>(null);
  const [compareB, setCompareB] = useState<number | null>(null);

  const { data: selectedConfig, isLoading: configLoading } = useConfigShow(selectedVersion);
  const { data: diffData, isLoading: diffLoading } = useConfigDiff(
    compareMode ? compareA : null,
    compareMode ? compareB : null
  );

  function handleToggleCompare() {
    setCompareMode((current) => !current);
    if (compareMode) {
      setCompareA(null);
      setCompareB(null);
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={4} />
        <LoadingSkeleton rows={7} />
      </div>
    );
  }

  if (!configs || configs.length === 0) {
    return (
      <EmptyState
        icon={Settings2}
        title="No configurations found"
        description="Config versions appear after initialization and optimization cycles."
        actionLabel="Refresh"
        onAction={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Config Versions"
        description="Inspect every versioned configuration, review YAML content, and compare diffs side by side."
        actions={
          <button
            onClick={handleToggleCompare}
            className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${
              compareMode
                ? 'bg-gray-900 text-white hover:bg-gray-800'
                : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
            }`}
          >
            <Columns3 className="h-4 w-4" />
            {compareMode ? 'Exit Compare' : 'Compare Versions'}
          </button>
        }
      />

      {isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load config metadata.
        </div>
      )}

      {compareMode && (
        <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">Version A</label>
              <select
                value={compareA ?? ''}
                onChange={(event) => setCompareA(event.target.value ? Number(event.target.value) : null)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">Select version</option>
                {configs.map((config) => (
                  <option key={config.version} value={config.version}>
                    v{config.version}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">Version B</label>
              <select
                value={compareB ?? ''}
                onChange={(event) => setCompareB(event.target.value ? Number(event.target.value) : null)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">Select version</option>
                {configs.map((config) => (
                  <option key={config.version} value={config.version}>
                    v{config.version}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>
      )}

      {compareMode && diffLoading && <LoadingSkeleton rows={5} />}
      {compareMode && diffData && compareA !== null && compareB !== null && (
        <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <YamlDiff lines={diffData.diff_lines} versionA={compareA} versionB={compareB} />
        </section>
      )}

      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Version</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Created</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Status</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Hash</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Composite</th>
              </tr>
            </thead>
            <tbody>
              {configs.map((config, index) => (
                <tr
                  key={config.version}
                  onClick={() => {
                    if (compareMode) return;
                    setSelectedVersion((current) => (current === config.version ? null : config.version));
                  }}
                  className={`border-b border-gray-100 ${
                    compareMode ? '' : 'cursor-pointer hover:bg-blue-50/60'
                  } ${index % 2 ? 'bg-gray-50/60' : ''}`}
                >
                  <td className="px-4 py-2 font-medium text-gray-900">v{config.version}</td>
                  <td className="px-4 py-2 text-gray-600">{formatTimestamp(config.timestamp)}</td>
                  <td className="px-4 py-2">
                    <StatusBadge variant={statusVariant(config.status)} label={config.status} />
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-600">{config.config_hash}</td>
                  <td className="px-4 py-2 text-gray-700">
                    {config.composite_score !== null ? config.composite_score.toFixed(1) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selectedVersion !== null && !compareMode && (
        <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Config v{selectedVersion}</h3>
            <button
              onClick={() => setSelectedVersion(null)}
              className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50"
            >
              Close
            </button>
          </div>

          {configLoading ? (
            <LoadingSkeleton rows={6} />
          ) : selectedConfig?.yaml_content ? (
            <YamlViewer content={selectedConfig.yaml_content} />
          ) : (
            <p className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-6 text-center text-sm text-gray-500">
              No YAML content available.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
