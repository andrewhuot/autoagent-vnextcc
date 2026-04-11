/**
 * Right pane — single active artifact with a Preview / Source code toggle
 * and a category tab bar along the top.
 *
 * Mirrors Image 2: "Configure environment / Source code" switcher on the
 * top-right, filename + content below. If no artifacts exist, falls back
 * to an EmptyPreview card.
 */

import { useMemo } from 'react';
import { classNames } from '../../lib/utils';
import type { WorkbenchArtifactCategory } from '../../lib/workbench-api';
import {
  useWorkbenchStore,
  type ArtifactCategoryFilter,
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
  if (artifact.category === 'tool') return `${base}.${extensionForLanguage(artifact.language)}`;
  return `${base}.${extensionForLanguage(artifact.language)}`;
}

export function ArtifactViewer() {
  const artifacts = useWorkbenchStore((s) => s.artifacts);
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
    () => (activeCategory === 'all' ? artifacts : artifacts.filter((a) => a.category === activeCategory)),
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
                    ? 'bg-white/[0.06] text-neutral-100'
                    : 'text-neutral-500 hover:text-neutral-300'
                )}
              >
                {tab.label}
                {count > 0 && (
                  <span className="ml-1 text-[10px] text-neutral-500">{count}</span>
                )}
              </button>
            );
          })}
        </div>
        <div className="flex shrink-0 items-center gap-1 rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-0.5">
          <button
            type="button"
            onClick={() => setActiveView('preview')}
            className={classNames(
              'rounded px-2 py-0.5 text-[11px] transition',
              activeView === 'preview'
                ? 'bg-white/[0.08] text-neutral-100'
                : 'text-neutral-500 hover:text-neutral-300'
            )}
          >
            Preview
          </button>
          <button
            type="button"
            onClick={() => setActiveView('source')}
            className={classNames(
              'rounded px-2 py-0.5 text-[11px] transition',
              activeView === 'source'
                ? 'bg-white/[0.08] text-neutral-100'
                : 'text-neutral-500 hover:text-neutral-300'
            )}
          >
            Source code
          </button>
        </div>
      </div>

      {/* Artifact content */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {active ? (
          <div className="flex h-full min-h-0 flex-col">
            {filtered.length > 1 && (
              <div className="flex items-center gap-1 overflow-x-auto border-b border-[color:var(--wb-border)] px-3 py-1.5">
                {filtered.map((artifact) => (
                  <button
                    key={artifact.id}
                    type="button"
                    onClick={() => setActiveArtifact(artifact.id)}
                    className={classNames(
                      'whitespace-nowrap rounded-md px-2 py-1 text-[11px] transition',
                      artifact.id === active.id
                        ? 'bg-white/[0.06] text-neutral-100'
                        : 'text-neutral-500 hover:text-neutral-300'
                    )}
                  >
                    {artifact.name}
                  </button>
                ))}
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-auto p-4">
              {activeView === 'source' ? (
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
          <EmptyPreview
            title="Processes paused, click to wake up"
            description="Describe the agent you want on the left. The preview of each generated artifact will appear here."
          />
        )}
      </div>
    </section>
  );
}

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
      <article className="prose prose-invert max-w-2xl text-[13px] leading-6">
        <h2 className="mb-2 text-[15px] font-semibold text-neutral-100">{artifact.name}</h2>
        <pre className="whitespace-pre-wrap font-sans text-[13px] leading-6 text-neutral-300">
          {artifact.preview}
        </pre>
      </article>
    );
  }
  if (artifact.language === 'python' || artifact.language === 'json' || artifact.language === 'yaml') {
    return (
      <SourceCodeView source={artifact.preview} language={artifact.language} filename={artifact.name} />
    );
  }
  return (
    <div className="max-w-2xl">
      <h2 className="mb-2 text-[15px] font-semibold text-neutral-100">{artifact.name}</h2>
      <p className="text-[13px] leading-6 text-neutral-400">{artifact.summary}</p>
      <pre className="mt-3 whitespace-pre-wrap rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3 font-mono text-[12px] text-neutral-300">
        {artifact.preview}
      </pre>
    </div>
  );
}
