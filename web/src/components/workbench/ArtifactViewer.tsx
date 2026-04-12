/**
 * Right pane — single active artifact with a Preview / Source code toggle
 * and a category tab bar along the top.
 *
 * Mirrors Image 2: "Configure environment / Source code" switcher on the
 * top-right, filename + content below. If no artifacts exist, falls back
 * to an EmptyPreview card.
 */

import { useMemo, useState } from 'react';
import { classNames } from '../../lib/utils';
import type { WorkbenchArtifactCategory } from '../../lib/workbench-api';
import {
  useWorkbenchStore,
  type ArtifactCategoryFilter,
  type ArtifactView,
  type WorkspaceTab,
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
  { id: 'other', label: 'Other' },
];

const PRIMARY_CATEGORY_IDS = new Set<ArtifactCategoryFilter>([
  'agent',
  'tool',
  'guardrail',
  'eval',
  'environment',
]);

const WORKSPACE_TABS: Array<{ id: WorkspaceTab; label: string }> = [
  { id: 'artifacts', label: 'Artifacts' },
  { id: 'agent', label: 'Agent Card' },
  { id: 'source', label: 'Source Code' },
  { id: 'evals', label: 'Evals' },
  { id: 'trace', label: 'Trace' },
  { id: 'activity', label: 'Activity' },
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
  const activeWorkspaceTab = useWorkbenchStore((s) => s.activeWorkspaceTab);
  const setActiveWorkspaceTab = useWorkbenchStore((s) => s.setActiveWorkspaceTab);
  return (
    <section className="flex h-full min-h-0 flex-col bg-[color:var(--wb-bg)]">
      <div className="flex items-center gap-1 overflow-x-auto border-b border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-3 py-2">
        {WORKSPACE_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveWorkspaceTab(tab.id)}
            className={classNames(
              'whitespace-nowrap rounded-md px-2.5 py-1 text-[12px] transition',
              activeWorkspaceTab === tab.id
                ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeWorkspaceTab === 'artifacts' && <ArtifactsWorkspace />}
      {activeWorkspaceTab === 'agent' && <AgentWorkspace />}
      {activeWorkspaceTab === 'source' && <SourceWorkspace />}
      {activeWorkspaceTab === 'evals' && <EvalsWorkspace />}
      {activeWorkspaceTab === 'trace' && <TraceWorkspace />}
      {activeWorkspaceTab === 'activity' && <ActivityWorkspace />}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Inline line-level diff
// ---------------------------------------------------------------------------

interface DiffLine {
  type: 'same' | 'added' | 'removed';
  content: string;
}

function buildLineDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split('\n');
  const newLines = newText.split('\n');
  const result: DiffLine[] = [];
  const max = Math.max(oldLines.length, newLines.length);
  let oi = 0;
  let ni = 0;
  while (oi < oldLines.length || ni < newLines.length) {
    if (oi < oldLines.length && ni < newLines.length && oldLines[oi] === newLines[ni]) {
      result.push({ type: 'same', content: oldLines[oi] });
      oi++;
      ni++;
    } else {
      // Consume removed lines until we find a match or exhaust old
      const lookAhead = Math.min(max, 4);
      let matchedOld = -1;
      let matchedNew = -1;
      for (let d = 1; d <= lookAhead; d++) {
        if (ni + d < newLines.length && oi < oldLines.length && oldLines[oi] === newLines[ni + d]) {
          matchedNew = ni + d;
          break;
        }
        if (oi + d < oldLines.length && ni < newLines.length && oldLines[oi + d] === newLines[ni]) {
          matchedOld = oi + d;
          break;
        }
      }
      if (matchedNew !== -1) {
        while (ni < matchedNew) {
          result.push({ type: 'added', content: newLines[ni] });
          ni++;
        }
      } else if (matchedOld !== -1) {
        while (oi < matchedOld) {
          result.push({ type: 'removed', content: oldLines[oi] });
          oi++;
        }
      } else {
        if (oi < oldLines.length) {
          result.push({ type: 'removed', content: oldLines[oi] });
          oi++;
        }
        if (ni < newLines.length) {
          result.push({ type: 'added', content: newLines[ni] });
          ni++;
        }
      }
    }
  }
  return result;
}

function DiffView({ oldSource, newSource }: { oldSource: string; newSource: string }) {
  const lines = useMemo(() => buildLineDiff(oldSource, newSource), [oldSource, newSource]);
  return (
    <pre className="font-mono text-[12px] leading-5">
      {lines.map((line, i) => (
        <div
          key={i}
          className={classNames(
            'px-3',
            line.type === 'added' && 'bg-[color:var(--wb-success-weak)] text-[color:var(--wb-success)]',
            line.type === 'removed' && 'bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)]',
            line.type === 'same' && 'text-[color:var(--wb-text-soft)]'
          )}
        >
          <span className="mr-2 inline-block w-4 select-none text-right text-[color:var(--wb-text-muted)]">
            {line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '}
          </span>
          {line.content}
        </div>
      ))}
    </pre>
  );
}

function ArtifactsWorkspace() {
  const artifacts = useWorkbenchStore((s) => s.artifacts);
  const activeCategory = useWorkbenchStore((s) => s.activeCategory);
  const setActiveCategory = useWorkbenchStore((s) => s.setActiveCategory);
  const activeView = useWorkbenchStore((s) => s.activeArtifactView);
  const setActiveView = useWorkbenchStore((s) => s.setActiveArtifactView);
  const setActiveArtifact = useWorkbenchStore((s) => s.setActiveArtifact);
  const activeArtifactId = useWorkbenchStore((s) => s.activeArtifactId);
  const previousVersionArtifacts = useWorkbenchStore((s) => s.previousVersionArtifacts);
  const diffTargetVersion = useWorkbenchStore((s) => s.diffTargetVersion);
  const iterationCount = useWorkbenchStore((s) => s.iterationCount);

  const filtered = useMemo(() => {
    if (activeCategory === 'all') return artifacts;
    if (activeCategory === 'other') {
      return artifacts.filter((a) => !PRIMARY_CATEGORY_IDS.has(a.category as ArtifactCategoryFilter));
    }
    return artifacts.filter((a) => a.category === activeCategory);
  }, [artifacts, activeCategory]);

  const active = useMemo(
    () =>
      activeArtifactId
        ? filtered.find((a) => a.id === activeArtifactId) ?? filtered[filtered.length - 1] ?? null
        : filtered[filtered.length - 1] ?? null,
    [filtered, activeArtifactId]
  );

  const previousArtifact = useMemo(() => {
    if (!active || previousVersionArtifacts.length === 0) return null;
    return previousVersionArtifacts.find(
      (a) => a.category === active.category && a.name === active.name
    ) ?? null;
  }, [active, previousVersionArtifacts]);

  const hasDiff = previousArtifact !== null && diffTargetVersion !== null;
  const effectiveView = activeView === 'diff' && !hasDiff ? 'preview' : activeView;

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const tab of CATEGORY_TABS) counts.set(tab.id, 0);
    for (const artifact of artifacts) {
      counts.set('all', (counts.get('all') ?? 0) + 1);
      if (PRIMARY_CATEGORY_IDS.has(artifact.category as ArtifactCategoryFilter)) {
        counts.set(artifact.category, (counts.get(artifact.category) ?? 0) + 1);
      } else {
        counts.set('other', (counts.get('other') ?? 0) + 1);
      }
    }
    return counts;
  }, [artifacts]);

  const filename = active ? defaultFilename(active) : '';

  const viewTabs: Array<{ id: ArtifactView; label: string }> = [
    { id: 'preview', label: 'Preview' },
    { id: 'source', label: 'Source code' },
    ...(hasDiff ? [{ id: 'diff' as const, label: 'Diff' }] : []),
  ];

  return (
    <div className="flex h-full min-h-0 flex-col bg-[color:var(--wb-bg)]">
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
                  <span className="ml-1 text-[10px] text-[color:var(--wb-text-dim)]">{count}</span>
                )}
              </button>
            );
          })}
        </div>
        <div className="flex shrink-0 items-center gap-1 rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-0.5">
          {viewTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveView(tab.id)}
              className={classNames(
                'rounded px-2 py-0.5 text-[11px] transition',
                effectiveView === tab.id
                  ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                  : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
              )}
            >
              {tab.label}
            </button>
          ))}
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
                        ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                        : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
                    )}
                  >
                    {artifact.name}
                    {iterationCount > 0 && (
                      <span className="ml-1 rounded bg-[color:var(--wb-accent-weak)] px-1 text-[9px] text-[color:var(--wb-accent)]">
                        v{iterationCount + 1}
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
          <EmptyPreview
            title="No artifacts yet"
            description="Generated artifacts will appear here as the run produces them."
          />
        )}
      </div>
    </div>
  );
}

function AgentWorkspace() {
  const model = useWorkbenchStore((s) => s.canonicalModel);
  const compatibility = useWorkbenchStore((s) => s.compatibility);
  if (!model || model.agents.length === 0) {
    return (
      <EmptyPreview
        title="No agent card yet"
        description="Run the builder so the canonical agent spec can appear here."
      />
    );
  }
  const root = model.agents[0];
  return (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      <div className="max-w-3xl space-y-5">
        <section>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[color:var(--wb-text-dim)]">
            Agent Card
          </p>
          <h2 className="mt-1 text-[18px] font-semibold text-[color:var(--wb-text)]">{root.name}</h2>
          <p className="mt-2 text-[13px] leading-6 text-[color:var(--wb-text-soft)]">{root.role}</p>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-[color:var(--wb-text-dim)]">
            <span className="rounded-md border border-[color:var(--wb-border)] px-2 py-1">{root.model}</span>
            <span className="rounded-md border border-[color:var(--wb-border)] px-2 py-1">
              {model.tools.length} tools
            </span>
            <span className="rounded-md border border-[color:var(--wb-border)] px-2 py-1">
              {model.guardrails.length} guardrails
            </span>
          </div>
        </section>

        <section>
          <h3 className="text-[12px] font-semibold text-[color:var(--wb-text)]">Instructions</h3>
          <pre className="mt-2 whitespace-pre-wrap rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3 font-sans text-[13px] leading-6 text-[color:var(--wb-text-soft)]">
            {root.instructions}
          </pre>
        </section>

        <section>
          <h3 className="text-[12px] font-semibold text-[color:var(--wb-text)]">Compatibility</h3>
          <div className="mt-2 space-y-2">
            {compatibility.map((item) => (
              <div
                key={`${item.object_id}-${item.target}`}
                className="rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[13px] font-medium text-[color:var(--wb-text)]">{item.label}</span>
                  <span className="rounded-md bg-[color:var(--wb-bg-active)] px-2 py-0.5 text-[11px] text-[color:var(--wb-text-soft)]">
                    {item.status}
                  </span>
                </div>
                <p className="mt-1 text-[12px] leading-5 text-[color:var(--wb-text-dim)]">{item.reason}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function SourceWorkspace() {
  const exports = useWorkbenchStore((s) => s.exports);
  const [target, setTarget] = useState<'adk' | 'cx'>('adk');
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const files = exports?.[target]?.files ?? {};
  const fileNames = Object.keys(files);
  const activeFile = selectedFile && files[selectedFile] ? selectedFile : fileNames[0];

  if (!exports || !activeFile) {
    return (
      <EmptyPreview
        title="No source generated yet"
        description="The builder will render ADK and CX export previews after it applies changes."
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-[color:var(--wb-border)] px-3 py-2">
        {(['adk', 'cx'] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => {
              setTarget(option);
              setSelectedFile(null);
            }}
            className={classNames(
              'rounded-md px-2.5 py-1 text-[12px] uppercase transition',
              target === option
                ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
            )}
          >
            {option}
          </button>
        ))}
        <div className="ml-2 flex min-w-0 gap-1 overflow-x-auto">
          {fileNames.map((filename) => (
            <button
              key={filename}
              type="button"
              onClick={() => setSelectedFile(filename)}
              className={classNames(
                'whitespace-nowrap rounded-md px-2 py-1 font-mono text-[11px] transition',
                filename === activeFile
                  ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                  : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
              )}
            >
              {filename}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <SourceCodeView source={files[activeFile]} language={languageFromFilename(activeFile)} filename={activeFile} />
      </div>
    </div>
  );
}

function EvalsWorkspace() {
  const model = useWorkbenchStore((s) => s.canonicalModel);
  const lastTest = useWorkbenchStore((s) => s.lastTest);
  const suites = model?.eval_suites ?? [];
  return (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      <div className="max-w-3xl space-y-4">
        <section className="rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3">
          <h2 className="text-[13px] font-semibold text-[color:var(--wb-text)]">Latest Harness Reflection</h2>
          <p className="mt-1 text-[12px] text-[color:var(--wb-text-dim)]">
            {lastTest ? `${lastTest.status} · ${lastTest.checks.length} checks` : 'No validation run yet.'}
          </p>
          {lastTest?.checks.map((check) => (
            <div key={check.name} className="mt-2 text-[12px] text-[color:var(--wb-text-soft)]">
              {check.passed ? 'Passed' : 'Failed'} · {check.name}: {check.detail}
            </div>
          ))}
        </section>
        {suites.map((suite) => (
          <section key={suite.id} className="rounded-md border border-[color:var(--wb-border)] p-3">
            <h3 className="text-[13px] font-semibold text-[color:var(--wb-text)]">{suite.name}</h3>
            <div className="mt-2 space-y-2">
              {suite.cases.map((testCase) => (
                <div key={testCase.id} className="text-[12px] leading-5 text-[color:var(--wb-text-soft)]">
                  <span className="font-mono text-[color:var(--wb-text-dim)]">{testCase.id}</span> {testCase.input}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function TraceWorkspace() {
  const activeRun = useWorkbenchStore((s) => s.activeRun);
  const lastTest = useWorkbenchStore((s) => s.lastTest);
  const events = activeRun?.events ?? [];
  return (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      <div className="max-w-3xl space-y-3">
        <h2 className="text-[13px] font-semibold text-[color:var(--wb-text)]">Run Trace</h2>
        {events.length === 0 && (
          <p className="text-[12px] text-[color:var(--wb-text-dim)]">No persisted run events yet.</p>
        )}
        {events.slice(-40).map((event) => {
          const telemetry = event.telemetry ?? (event.data?.telemetry as Record<string, unknown> | undefined);
          const reason =
            (telemetry?.failure_reason as string | undefined) ??
            (telemetry?.cancel_reason as string | undefined) ??
            (event.data?.failure_reason as string | undefined) ??
            (event.data?.cancel_reason as string | undefined);
          const tokenCount = Number(telemetry?.tokens_used ?? 0);
          const costUsd = Number(telemetry?.cost_usd ?? 0);
          const durationMs = Number(telemetry?.duration_ms ?? 0);
          return (
          <div key={event.sequence} className="rounded-md border border-[color:var(--wb-border)] px-3 py-2">
            <div className="flex items-center justify-between gap-3 text-[12px]">
              <span className="font-mono text-[color:var(--wb-text)]">{event.event}</span>
              <span className="text-[color:var(--wb-text-dim)]">
                {event.status} · {event.phase}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[color:var(--wb-text-dim)]">
              {event.created_at && <span>{new Date(event.created_at).toLocaleTimeString()}</span>}
              {telemetry?.run_id ? <span>run {String(telemetry.run_id)}</span> : null}
              {telemetry?.iteration_id ? <span>iter {String(telemetry.iteration_id)}</span> : null}
              {telemetry?.provider ? <span>{String(telemetry.provider)} / {String(telemetry.model ?? 'unknown')}</span> : null}
              {durationMs > 0 && <span>{durationMs}ms</span>}
              {tokenCount > 0 && <span>{tokenCount} tokens</span>}
              {costUsd > 0 && <span>${costUsd.toFixed(costUsd < 0.01 ? 4 : 2)}</span>}
              {reason && <span>{reason}</span>}
            </div>
          </div>
          );
        })}
        {lastTest?.trace.map((entry) => (
          <div key={`${entry.event}-${entry.status}`} className="text-[12px] text-[color:var(--wb-text-soft)]">
            Reflection · {entry.event}: {entry.status}
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivityWorkspace() {
  const activity = useWorkbenchStore((s) => s.activity);
  const presentationState = useWorkbenchStore((s) => s.presentation);
  const activeRun = useWorkbenchStore((s) => s.activeRun);
  const harnessState = useWorkbenchStore((s) => s.harnessState);
  const runSummary = useWorkbenchStore((s) => s.runSummary);
  const lastValidation = useWorkbenchStore((s) => s.lastValidation);
  const presentation = presentationState ?? activeRun?.presentation ?? null;
  const reviewGate = presentation?.review_gate ?? activeRun?.review_gate ?? null;
  const handoff = presentation?.handoff ?? activeRun?.handoff ?? harnessState?.latest_handoff ?? null;
  const handoffEvidence = handoff && 'evidence' in handoff ? handoff.evidence : null;
  const handoffText = handoff
    ? 'resume_prompt' in handoff && handoff.resume_prompt
      ? handoff.resume_prompt
      : 'next_action' in handoff
        ? handoff.next_action
        : handoff.next_operator_action
    : '';
  const handoffLastEvent = handoff
    ? 'last_event_sequence' in handoff
      ? handoff.last_event_sequence
      : handoff.last_event?.sequence ?? 'unknown'
    : 'unknown';
  const evidence =
    activeRun?.evidence_summary ??
    activeRun?.summary?.evidence_summary ??
    runSummary?.evidence_summary ??
    handoffEvidence ??
    null;
  return (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      <div className="max-w-3xl space-y-4">
        {(presentation || reviewGate || handoff || evidence || lastValidation) && (
          <section className="rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3">
            <h2 className="text-[13px] font-semibold text-[color:var(--wb-text)]">
              {presentation?.summary ?? runSummary?.recommended_action ?? 'Run evidence status'}
            </h2>
            {presentation?.next_actions?.length ? (
              <ul className="mt-2 space-y-1 text-[12px] text-[color:var(--wb-text-soft)]">
                {presentation.next_actions.map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            ) : null}
            {(evidence || lastValidation) && (
              <div className="mt-3 rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] p-3">
                <h3 className="text-[12px] font-semibold text-[color:var(--wb-text)]">Evidence status</h3>
                <div className="mt-2 space-y-1 text-[12px] text-[color:var(--wb-text-soft)]">
                  <p>structural_validation: {evidence?.structural_status ?? lastValidation?.status ?? 'unknown'}</p>
                  <p>improvement_evidence: {evidence?.improvement_status ?? 'unknown'}</p>
                  {evidence?.correction_status ? <p>correction: {evidence.correction_status}</p> : null}
                  {typeof evidence?.operations_applied === 'number' ? (
                    <p>operations_applied: {evidence.operations_applied}</p>
                  ) : null}
                </div>
              </div>
            )}
            {reviewGate && (
              <div className="mt-3 rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] p-3">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-[12px] font-semibold text-[color:var(--wb-text)]">Review gate</h3>
                  <span className="rounded-md bg-[color:var(--wb-bg-active)] px-2 py-0.5 text-[11px] text-[color:var(--wb-text-soft)]">
                    {reviewGate.status}
                  </span>
                </div>
                <div className="mt-2 space-y-1 text-[12px] text-[color:var(--wb-text-soft)]">
                  {reviewGate.checks.map((check) => (
                    <p key={check.name}>
                      {check.name}: {check.status}
                    </p>
                  ))}
                </div>
                {reviewGate.blocking_reasons.length > 0 && (
                  <ul className="mt-2 space-y-1 text-[12px] text-[color:var(--wb-error)]">
                    {reviewGate.blocking_reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {handoff && (
              <div className="mt-3 rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] p-3">
                <h3 className="text-[12px] font-semibold text-[color:var(--wb-text)]">Session handoff</h3>
                <p className="mt-1 text-[12px] leading-5 text-[color:var(--wb-text-soft)]">
                  {handoffText}
                </p>
                <p className="mt-2 font-mono text-[11px] text-[color:var(--wb-text-dim)]">
                  run {handoff.run_id} | event {handoffLastEvent}
                </p>
              </div>
            )}
          </section>
        )}
        {activity.map((entry) => (
          <section key={entry.id} className="rounded-md border border-[color:var(--wb-border)] p-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-[13px] font-semibold text-[color:var(--wb-text)]">{entry.summary}</h3>
              <span className="text-[11px] uppercase text-[color:var(--wb-text-dim)]">{entry.kind}</span>
            </div>
            {entry.diff.map((diff, index) => (
              <p key={`${entry.id}-${index}`} className="mt-2 text-[12px] text-[color:var(--wb-text-soft)]">
                {diff.field}: {String(diff.before)} → {String(diff.after)}
              </p>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}

function languageFromFilename(filename: string): string {
  if (filename.endsWith('.py')) return 'python';
  if (filename.endsWith('.json')) return 'json';
  if (filename.endsWith('.yaml') || filename.endsWith('.yml')) return 'yaml';
  return 'text';
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
      <article className="max-w-2xl text-[13px] leading-6">
        <h2 className="mb-2 text-[15px] font-semibold text-[color:var(--wb-text)]">{artifact.name}</h2>
        <pre className="whitespace-pre-wrap font-sans text-[13px] leading-6 text-[color:var(--wb-text-soft)]">
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
      <h2 className="mb-2 text-[15px] font-semibold text-[color:var(--wb-text)]">{artifact.name}</h2>
      <p className="text-[13px] leading-6 text-[color:var(--wb-text-dim)]">{artifact.summary}</p>
      <pre className="mt-3 whitespace-pre-wrap rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3 font-mono text-[12px] text-[color:var(--wb-text-soft)]">
        {artifact.preview}
      </pre>
    </div>
  );
}
