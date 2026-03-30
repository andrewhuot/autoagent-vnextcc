import { useState } from 'react';
import { ArrowUpRight, Columns3, FileUp, Settings2, WandSparkles } from 'lucide-react';
import {
  useActivateConfig,
  useConfigDiff,
  useConfigs,
  useConfigShow,
  useImportConfig,
  useMigrateConfig,
  useNaturalLanguageConfigEdit,
} from '../lib/api';
import { EmptyState } from '../components/EmptyState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { YamlViewer } from '../components/YamlViewer';
import { YamlDiff } from '../components/YamlDiff';
import { toastError, toastSuccess } from '../lib/toast';
import { formatTimestamp, statusVariant } from '../lib/utils';
import type { ConfigEditResult } from '../lib/types';

export function Configs() {
  const { data: configs, isLoading, isError, refetch } = useConfigs();
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compareA, setCompareA] = useState<number | null>(null);
  const [compareB, setCompareB] = useState<number | null>(null);
  const [editDescription, setEditDescription] = useState('');
  const [previewedDescription, setPreviewedDescription] = useState('');
  const [editPreview, setEditPreview] = useState<ConfigEditResult | null>(null);
  const [importPath, setImportPath] = useState('');
  const [migrateInputPath, setMigrateInputPath] = useState('');
  const [migrateOutputPath, setMigrateOutputPath] = useState('');
  const [migrationPreview, setMigrationPreview] = useState<string | null>(null);

  const { data: selectedConfig, isLoading: configLoading } = useConfigShow(selectedVersion);
  const { data: diffData, isLoading: diffLoading } = useConfigDiff(
    compareMode ? compareA : null,
    compareMode ? compareB : null
  );
  const nlEdit = useNaturalLanguageConfigEdit();
  const activateConfig = useActivateConfig();
  const importConfig = useImportConfig();
  const migrateConfig = useMigrateConfig();

  function handleToggleCompare() {
    setCompareMode((current) => !current);
    if (compareMode) {
      setCompareA(null);
      setCompareB(null);
    }
  }

  function handleEditDescriptionChange(value: string) {
    setEditDescription(value);
    if (previewedDescription && value.trim() !== previewedDescription) {
      setEditPreview(null);
      setPreviewedDescription('');
    }
  }

  function handlePreviewEdit() {
    const description = editDescription.trim();
    if (!description) {
      toastError('Description required', 'Describe the config change you want to preview.');
      return;
    }

    nlEdit.mutate(
      { description, dry_run: true },
      {
        onSuccess: (result) => {
          setEditPreview(result);
          setPreviewedDescription(description);
          toastSuccess(
            'Preview ready',
            result.accepted
              ? 'Review the diff and apply when ready.'
              : 'Review the diff before deciding whether to apply.'
          );
        },
        onError: (error) => {
          toastError('Preview failed', error.message);
        },
      }
    );
  }

  function handleApplyPreview() {
    if (!previewedDescription) {
      toastError('Preview required', 'Preview the edit before applying it.');
      return;
    }

    nlEdit.mutate(
      { description: previewedDescription, dry_run: false },
      {
        onSuccess: (result) => {
          setEditPreview(result);
          toastSuccess(
            result.applied ? 'Config edit applied' : 'Config edit not applied',
            result.applied
              ? `Optimization attempt ${result.attempt?.attempt_id ?? 'created'}.`
              : 'The change did not clear acceptance checks.'
          );
        },
        onError: (error) => {
          toastError('Apply failed', error.message);
        },
      }
    );
  }

  function handleActivateSelected() {
    if (selectedVersion === null) {
      toastError('Select a version', 'Choose a config version before activating it.');
      return;
    }

    activateConfig.mutate(
      { version: selectedVersion },
      {
        onSuccess: (result) => {
          toastSuccess(
            'Config activated',
            result.workspace_updated
              ? `v${result.version} is now active in the workspace and manifest.`
              : `v${result.version} is now active in the config manifest.`
          );
          refetch();
        },
        onError: (error) => {
          toastError('Activation failed', error.message);
        },
      }
    );
  }

  function handleImportConfig() {
    const filePath = importPath.trim();
    if (!filePath) {
      toastError('Import path required', 'Provide a YAML or JSON file path to import.');
      return;
    }

    importConfig.mutate(
      { file_path: filePath },
      {
        onSuccess: (result) => {
          toastSuccess('Config imported', `Imported ${result.source_file} as v${result.version}.`);
          setImportPath('');
          refetch();
        },
        onError: (error) => {
          toastError('Import failed', error.message);
        },
      }
    );
  }

  function handleMigrateConfig() {
    const inputFile = migrateInputPath.trim();
    if (!inputFile) {
      toastError('Input path required', 'Provide the legacy config file you want to migrate.');
      return;
    }

    migrateConfig.mutate(
      {
        input_file: inputFile,
        output_file: migrateOutputPath.trim() || undefined,
      },
      {
        onSuccess: (result) => {
          setMigrationPreview(result.yaml_content);
          toastSuccess(
            'Migration complete',
            result.output_file ? `Wrote migrated config to ${result.output_file}.` : 'Showing migrated YAML preview below.'
          );
        },
        onError: (error) => {
          toastError('Migration failed', error.message);
        },
      }
    );
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
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load config metadata.
        </div>
      )}

      <section className="grid gap-4 xl:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-2">
            <ArrowUpRight className="h-4 w-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">Activate</h3>
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Promote the selected version into the active workspace slot without leaving the browser.
          </p>
          <p className="mt-3 text-xs text-gray-500">
            Selected version: {selectedVersion !== null ? `v${selectedVersion}` : 'None'}
          </p>
          <button
            onClick={handleActivateSelected}
            disabled={selectedVersion === null || activateConfig.isPending}
            className="mt-4 w-full rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
          >
            {activateConfig.isPending ? 'Activating...' : 'Activate Selected Version'}
          </button>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-2">
            <FileUp className="h-4 w-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">Import</h3>
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Pull an external YAML or JSON config into the versioned config history.
          </p>
          <input
            value={importPath}
            onChange={(event) => setImportPath(event.target.value)}
            placeholder="configs/incoming/support-agent.yaml"
            className="mt-4 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={handleImportConfig}
            disabled={importConfig.isPending}
            className="mt-3 w-full rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
          >
            {importConfig.isPending ? 'Importing...' : 'Import Config'}
          </button>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-2">
            <WandSparkles className="h-4 w-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">Migrate</h3>
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Convert a legacy optimizer config into the current optimization layout before importing it.
          </p>
          <div className="mt-4 space-y-2">
            <input
              value={migrateInputPath}
              onChange={(event) => setMigrateInputPath(event.target.value)}
              placeholder="legacy/autoagent.yaml"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            <input
              value={migrateOutputPath}
              onChange={(event) => setMigrateOutputPath(event.target.value)}
              placeholder="Optional output path"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <button
            onClick={handleMigrateConfig}
            disabled={migrateConfig.isPending}
            className="mt-3 w-full rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
          >
            {migrateConfig.isPending ? 'Migrating...' : 'Preview Migration'}
          </button>
        </div>
      </section>

      {migrationPreview && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Migrated Config Preview</h3>
              <p className="mt-1 text-sm text-gray-600">
                Review the migrated YAML before importing or applying it elsewhere.
              </p>
            </div>
          </div>
          <YamlViewer content={migrationPreview} />
        </section>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-gray-900">Natural-language edit</h3>
            <p className="mt-1 text-sm text-gray-600">
              Describe the change you want, preview the YAML diff, then apply it once the direction looks right.
            </p>
          </div>
          {editPreview && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
              {editPreview.applied ? 'Applied to the active config.' : 'Preview only until you confirm apply.'}
            </div>
          )}
        </div>

        <div className="mt-4 space-y-3">
          <div>
            <label htmlFor="config-nl-edit" className="mb-1 block text-xs font-medium text-gray-600">
              Describe config change
            </label>
            <textarea
              id="config-nl-edit"
              value={editDescription}
              onChange={(event) => handleEditDescriptionChange(event.target.value)}
              rows={4}
              placeholder="Reduce timeout_seconds from six to four for faster retries."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handlePreviewEdit}
              disabled={nlEdit.isPending}
              className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
            >
              {nlEdit.isPending ? 'Previewing...' : 'Preview edit'}
            </button>
            <button
              onClick={handleApplyPreview}
              disabled={
                nlEdit.isPending ||
                !editPreview ||
                !previewedDescription ||
                editDescription.trim() !== previewedDescription
              }
              className="rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
            >
              {nlEdit.isPending ? 'Applying...' : 'Apply previewed edit'}
            </button>
            {previewedDescription && editDescription.trim() !== previewedDescription && (
              <p className="text-xs text-amber-700">
                Preview is out of date. Run preview again before applying.
              </p>
            )}
          </div>
        </div>

        {editPreview && (
          <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-gray-700">
                {editPreview.intent.change_type}
              </span>
              {editPreview.intent.target_surfaces.map((surface) => (
                <span
                  key={surface}
                  className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700"
                >
                  {surface}
                </span>
              ))}
            </div>
            <p className="mt-3 text-sm text-gray-700">{editPreview.intent.description}</p>
            <p className="mt-2 text-xs text-gray-600">
              Composite score: {editPreview.score_before.toFixed(2)} {'->'} {editPreview.score_after.toFixed(2)}
            </p>
            <pre className="mt-3 overflow-x-auto rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-700">
              {editPreview.diff || 'No textual diff returned.'}
            </pre>
          </div>
        )}
      </section>

      {compareMode && (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Version A</label>
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
              <label className="mb-1 block text-xs text-gray-500">Version B</label>
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

      {compareMode && !diffLoading && (compareA === null || compareB === null) && (
        <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
          Select two versions to compare YAML changes side by side.
        </section>
      )}

      {compareMode && diffLoading && <LoadingSkeleton rows={5} />}
      {compareMode && diffData && compareA !== null && compareB !== null && (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <YamlDiff lines={diffData.diff_lines} versionA={compareA} versionB={compareB} />
        </section>
      )}

      <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
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
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Config v{selectedVersion}</h3>
            <div className="flex items-center gap-2">
              <button
                onClick={handleActivateSelected}
                disabled={activateConfig.isPending}
                className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-60"
              >
                {activateConfig.isPending ? 'Activating...' : 'Activate'}
              </button>
              <button
                onClick={() => setSelectedVersion(null)}
                className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
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
