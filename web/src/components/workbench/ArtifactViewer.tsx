/**
 * Right pane — single active artifact with Preview / Source / Diff tab bar
 * and a category tab bar along the top.
 *
 * Added in Phase 3:
 *   - "Diff" tab alongside Preview and Source
 *   - Version badge ("v2") on artifact cards in the sub-navigation
 *   - Better empty state when no artifacts yet
 */

import { useMemo } from 'react';
import { Box } from 'lucide-react';
import { classNames } from '../../lib/utils';
import type { WorkbenchArtifactCategory } from '../../lib/workbench-api';
import {
  useWorkbenchStore,
  type ArtifactCategoryFilter,
  type ArtifactView,
} from '../../lib/workbench-store';
import { SourceCodeView } from './SourceCodeView';
import { EmptyPreview } from './EmptyPreview';

const CATEGORY_TABS: Array<{ id: ArtifactCategoryFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'agent', label: 'Agent' },
  { id: 'tool', label: 'Tools' },
  { id: 'guardrail', label: 'Guardrails' },
  { id: 'eval', label: 'Evals' },
  { id: 'environment', label: 'Environment' },
];

const VIEW_TABS: Array<{ id: ArtifactView; label: string }> = [
  { id: 'preview', label: 'Preview' },
  { id: 'source', label: 'Source' },
  { id: 'diff', label: 'Diff' },
];

function extensionForLanguage(language: string): string {
  switch (language) {
    case 'python':
      return 'py';
    case 'typescript':
      return 'ts';
    case 'javascript':
      return 'js';
    case 'json':
      return 'json';
    case 'yaml':
      return 'yaml';
    case 'markdown':
      return 'md';
    default:
      return 'txt';
  }
}

function defaultFilename(artifact: {
  name: string;
  category: string | WorkbenchArtifactCategory;
  language: string;
}): string {
  const base = artifact.name.replace(/\s+/g, '_').toLowerCase();
  if (artifact.category === 'agent') return 'agent.py';
  if (artifact.category === 'environment') return 'agent.py';
  return `${base}.${extensionForLanguage(artifact.language)}`;
}

// ---------------------------------------------------------------------------
// Diff view
// ---------------------------------------------------------------------------

interface DiffLine {
  type: 'same' | 'added' | 'removed';
  content: string;
  lineNumber: number;
}

/**
 * Very simple line-by-line diff. Does NOT compute an LCS — just aligns lines
 * by splitting on newlines and comparing. Good enough for code artifacts that
 * change in blocks. A proper Myers diff is overkill for the harness prototype.
 */
function buildLineDiff(oldSource: string, newSource: string): DiffLine[] {
  const oldLines = oldSource.split('\n');
  const newLines = newSource.split('\n');
  const result: DiffLine[] = [];

  // Walk both lists in tandem; mark removed-then-added pairs first.
  let o = 0;
  let n = 0;

  while (o < oldLines.length || n < newLines.length) {
    const oldLine = oldLines[o];
    const newLine = newLines[n];

    if (o >= oldLines.length) {
      result.push({ type: 'added', content: newLine, lineNumber: n + 1 });
      n++;
    } else if (n >= newLines.length) {
      result.push({ type: 'removed', content: oldLine, lineNumber: o + 1 });
      o++;
    } else if (oldLine === newLine) {
      result.push({ type: 'same', content: newLine, lineNumber: n + 1 });
      o++;
      n++;
    } else {
      // Changed line — show removal then addition.
      result.push({ type: 'removed', content: oldLine, lineNumber: o + 1 });
      result.push({ type: 'added', content: newLine, lineNumber: n + 1 });
      o++;
      n++;
    }
  }

  return result;
}

function DiffView({
  oldSource,
  newSource,
}: {
  oldSource: string;
  newSource: string;
}) {
  const lines = useMemo(
    () => buildLineDiff(oldSource, newSource),
    [oldSource, newSource]
  );

  const changedCount = lines.filter((l) => l.type !== 'same').length;

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 px-4 py-2 text-[11px] text-[color:var(--wb-text-dim)]">
        {changedCount === 0
          ? 'No changes between versions.'
          : `${changedCount} changed line${changedCount === 1 ? '' : 's'}`}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <pre className="min-w-max font-mono text-[12px] leading-5">
          {lines.map((line, idx) => (
            <div
              key={idx}
              className={classNames(
                'flex items-start gap-0',
                line.type === 'added' &&
                  'bg-[color:var(--wb-success-weak)] text-[color:var(--wb-success)]',
                line.type === 'removed' &&
                  'bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)]',
                line.type === 'same' && 'text-[color:var(--wb-text-soft)]'
              )}
            >
              <span className="w-7 shrink-0 select-none px-1 text-right text-[10px] text-[color:var(--wb-code-line)]">
                {line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '}
              </span>
              <span className="whitespace-pre px-2">{line.content}</span>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ArtifactViewer() {
  const artifacts = useWorkbenchStore((s) => s.artifacts);
  const previousVersionArtifacts = useWorkbenchStore((s) => s.previousVersionArtifacts);
  const diffTargetVersion = useWorkbenchStore((s) => s.diffTargetVersion);
  const activeCategory = useWorkbenchStore((s) => s.activeCategory);
  const setActiveCategory = useWorkbenchStore((s) => s.setActiveCategory);
  const activeView = useWorkbenchStore((s) => s.activeArtifactView);
  const setActiveView = useWorkbenchStore((s) => s.setActiveArtifactView);
  const setActiveArtifact = useWorkbenchStore((s) => s.setActiveArtifact);
  const activeArtifactId = useWorkbenchStore((s) => s.activeArtifactId);

  const active = useMemo(
    () =>
      activeArtifactId
        ? artifacts.find((a) => a.id === activeArtifactId) ?? null
        : artifacts[artifacts.length - 1] ?? null,
    [artifacts, activeArtifactId]
  );

  const filtered = useMemo(
    () =>
      activeCategory === 'all'
        ? artifacts
        : artifacts.filter((a) => a.category === activeCategory),
    [artifacts, activeCategory]
  );

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const tab of CATEGORY_TABS) counts.set(tab.id, 0);
    for (const artifact of artifacts) {
      counts.set('all', (counts.get('all') ?? 0) + 1);
      counts.set(artifact.category, (counts.get(artifact.category) ?? 0) + 1);
    }
    return counts;
  }, [artifacts]);

  const filename = active ? defaultFilename(active) : '';

  // Find the previous version of the active artifact for diff.
  const previousArtifact = useMemo(() => {
    if (!active || diffTargetVersion === null) return null;
    return previousVersionArtifacts.find((a) => a.id === active.id) ?? null;
  }, [active, previousVersionArtifacts, diffTargetVersion]);

  // Whether the diff tab is meaningful.
  const hasDiff = previousArtifact !== null && diffTargetVersion !== null;

  // Auto-switch to a sensible tab when diff becomes available/unavailable.
  const effectiveView: ArtifactView =
    activeView === 'diff' && !hasDiff ? 'preview' : activeView;

  return (
    <section className="flex h-full min-h-0 flex-col bg-[color:var(--wb-bg)]">
      {/* Top category tab bar */}
      <div className="flex items-center gap-1 border-b border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {CATEGORY_TABS.map((tab) => {
            const count = categoryCounts.get(tab.id) ?? 0;
            const isActive = tab.id === activeCategory;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveCategory(tab.id)}
                className={classNames(
                  'rounded-md px-2.5 py-1 text-[12px] transition',
                  isActive
                    ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                    : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
                )}
              >
                {tab.label}
                {count > 0 && (
                  <span className="ml-1 text-[10px] text-[color:var(--wb-text-dim)]">
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* View toggle: Preview / Source / Diff */}
        <div className="flex shrink-0 items-center gap-1 rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-0.5">
          {VIEW_TABS.map((tab) => {
            // Hide the Diff tab when there's nothing to diff.
            if (tab.id === 'diff' && !hasDiff) return null;
            const isActive = effectiveView === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveView(tab.id)}
                className={classNames(
                  'rounded px-2 py-0.5 text-[11px] transition',
                  isActive
                    ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                    : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
                )}
              >
                {tab.id === 'diff' && diffTargetVersion !== null
                  ? `Diff v${diffTargetVersion}`
                  : tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Artifact content */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {active ? (
          <div className="flex h-full min-h-0 flex-col">
            {/* Sub-navigation: artifact list within the filtered category */}
            {filtered.length > 1 && (
              <div className="flex items-center gap-1 overflow-x-auto border-b border-[color:var(--wb-border)] px-3 py-1.5">
                {filtered.map((artifact) => (
                  <button
                    key={artifact.id}
                    type="button"
                    onClick={() => setActiveArtifact(artifact.id)}
                    className={classNames(
                      'flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-[11px] transition',
                      artifact.id === active.id
                        ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                        : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
                    )}
                  >
                    {artifact.name}
                    {artifact.version > 1 && (
                      <span
                        className={classNames(
                          'rounded px-1 text-[9px] font-semibold',
                          'bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]'
                        )}
                      >
                        v{artifact.version}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            <div className="min-h-0 flex-1 overflow-auto p-4">
              {effectiveView === 'diff' && previousArtifact ? (
                <DiffView
                  oldSource={previousArtifact.source || previousArtifact.preview}
                  newSource={active.source || active.preview}
                />
              ) : effectiveView === 'source' ? (
                <SourceCodeView
                  source={active.source || active.preview}
                  language={active.language}
                  filename={filename}
                />
              ) : (
                <ArtifactPreviewBody artifact={active} />
              )}
            </div>
          </div>
        ) : (
          <EmptyPreviewState />
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Empty state — improved version
// ---------------------------------------------------------------------------

function EmptyPreviewState() {
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);

  if (buildStatus === 'running' || buildStatus === 'starting') {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[color:var(--wb-accent-weak)]">
          <Box className="h-5 w-5 animate-pulse text-[color:var(--wb-accent)]" />
        </div>
        <p className="text-[13px] font-medium text-[color:var(--wb-text)]">
          Generating artifacts...
        </p>
        <p className="text-[12px] leading-5 text-[color:var(--wb-text-dim)]">
          Each artifact will appear here as it is produced.
        </p>
      </div>
    );
  }

  return (
    <EmptyPreview
      title="Processes paused, click to wake up"
      description="Describe the agent you want on the left. The preview of each generated artifact will appear here."
    />
  );
}

// ---------------------------------------------------------------------------
// Artifact preview body
// ---------------------------------------------------------------------------

function ArtifactPreviewBody({
  artifact,
}: {
  artifact: {
    category: string;
    name: string;
    summary: string;
    preview: string;
    language: string;
  };
}) {
  if (artifact.language === 'markdown') {
    return (
      <article className="max-w-2xl text-[13px] leading-6">
        <h2 className="mb-2 text-[15px] font-semibold text-[color:var(--wb-text)]">
          {artifact.name}
        </h2>
        <pre className="whitespace-pre-wrap font-sans text-[13px] leading-6 text-[color:var(--wb-text-soft)]">
          {artifact.preview}
        </pre>
      </article>
    );
  }
  if (
    artifact.language === 'python' ||
    artifact.language === 'json' ||
    artifact.language === 'yaml'
  ) {
    return (
      <SourceCodeView
        source={artifact.preview}
        language={artifact.language}
        filename={artifact.name}
      />
    );
  }
  return (
    <div className="max-w-2xl">
      <h2 className="mb-2 text-[15px] font-semibold text-[color:var(--wb-text)]">
        {artifact.name}
      </h2>
      <p className="text-[13px] leading-6 text-[color:var(--wb-text-dim)]">
        {artifact.summary}
      </p>
      <pre className="mt-3 whitespace-pre-wrap rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3 font-mono text-[12px] text-[color:var(--wb-text-soft)]">
        {artifact.preview}
      </pre>
    </div>
  );
}
