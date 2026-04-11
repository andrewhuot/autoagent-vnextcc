import type { BuilderSessionPayload } from '../../lib/builder-chat-api';
import type { BuilderConfigDraft } from '../../lib/builder-types';
import type { WorkbenchInspectorTab } from '../../lib/workbench-store';
import { AgentCardTab } from './inspector/AgentCardTab';
import { CallbacksTab } from './inspector/CallbacksTab';
import { DeployTab } from './inspector/DeployTab';
import { EvalResultsTab } from './inspector/EvalResultsTab';
import { FilesTab } from './inspector/FilesTab';
import { GuardrailsTab } from './inspector/GuardrailsTab';
import { PreviewTab } from './inspector/PreviewTab';
import { SourceCodeTab } from './inspector/SourceCodeTab';
import { TestLiveTab } from './inspector/TestLiveTab';
import { ToolsTab } from './inspector/ToolsTab';
import { TraceViewerTab } from './inspector/TraceViewerTab';

export type WorkbenchInspectorTabId = WorkbenchInspectorTab;

const TABS: Array<{ id: WorkbenchInspectorTab; label: string }> = [
  { id: 'preview', label: 'Preview' },
  { id: 'agent_card', label: 'Agent Card' },
  { id: 'source_code', label: 'Source Code' },
  { id: 'tools', label: 'Tools' },
  { id: 'callbacks', label: 'Callbacks' },
  { id: 'guardrails', label: 'Guardrails' },
  { id: 'evals', label: 'Evals' },
  { id: 'trace', label: 'Trace' },
  { id: 'test_live', label: 'Test Live' },
  { id: 'deploy', label: 'Deploy' },
  { id: 'activity', label: 'Activity' },
];

interface ToolItem {
  id: string;
  name: string;
  description: string;
  attached: boolean;
}

interface GuardrailItem {
  id: string;
  name: string;
  scope: string;
}

function adaptToolsFromDraft(draft: BuilderConfigDraft | null): ToolItem[] {
  if (!draft) return [];
  return draft.tools.map((tool, idx) => ({
    id: tool.id ?? `tool-${idx}`,
    name: tool.name,
    description: tool.description ?? '',
    attached: true,
  }));
}

function adaptPoliciesFromDraft(draft: BuilderConfigDraft | null): GuardrailItem[] {
  if (!draft) return [];
  return draft.policies.map((policy, idx) => ({
    id: policy.id ?? `policy-${idx}`,
    name: policy.name,
    scope: policy.scope ?? 'global',
  }));
}

/** Convert a BuilderSessionPayload's config to a BuilderConfigDraft. */
function sessionPayloadToDraft(payload: BuilderSessionPayload | null): BuilderConfigDraft | null {
  if (!payload) return null;
  const cfg = payload.config;
  return {
    agent_name: cfg.agent_name,
    model: cfg.model,
    system_prompt: cfg.system_prompt,
    tools: cfg.tools.map((t, idx) => ({
      id: `tool-${idx}`,
      name: t.name,
      description: t.description,
    })),
    routing_rules: cfg.routing_rules.map((r) => r as unknown as Record<string, unknown>),
    policies: cfg.policies.map((p, idx) => ({
      id: `policy-${idx}`,
      name: p.name,
      description: p.description,
    })),
    eval_criteria: cfg.eval_criteria.map((e) => e as unknown as Record<string, unknown>),
    metadata: cfg.metadata,
  };
}

interface WorkbenchInspectorProps {
  activeTab: WorkbenchInspectorTab;
  onTabChange: (tab: WorkbenchInspectorTab) => void;
  sessionPayload?: BuilderSessionPayload | null;
  /** Legacy direct props — kept for backward compat */
  sessionId?: string | null;
  draft?: BuilderConfigDraft | null;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  /** Called with new collapsed state (used by Workbench.tsx) */
  onCollapsedChange?: (collapsed: boolean) => void;
  /** Tabs list (optional; TABS constant is used as fallback) */
  tabs?: WorkbenchInspectorTab[];
}

export function WorkbenchInspector({
  activeTab,
  onTabChange,
  sessionPayload,
  sessionId: sessionIdProp,
  draft: draftProp,
  collapsed = false,
  onToggleCollapsed,
  onCollapsedChange,
}: WorkbenchInspectorProps) {
  // Derive sessionId and draft from sessionPayload when provided.
  const sessionId: string | null =
    sessionIdProp !== undefined
      ? sessionIdProp
      : (sessionPayload?.session_id ?? null);

  const draft: BuilderConfigDraft | null =
    draftProp !== undefined
      ? draftProp
      : sessionPayloadToDraft(sessionPayload ?? null);

  const handleCollapse = () => {
    if (onToggleCollapsed) {
      onToggleCollapsed();
    } else if (onCollapsedChange) {
      onCollapsedChange(!collapsed);
    }
  };

  if (collapsed) {
    return (
      <aside className="flex h-full w-12 flex-col border-l border-slate-800 bg-slate-950">
        <button
          type="button"
          onClick={handleCollapse}
          className="m-2 rounded border border-slate-700 px-2 py-1 text-xs text-slate-400 transition hover:bg-slate-800"
          aria-label="Expand inspector"
        >
          ⇦
        </button>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-[420px] min-w-[420px] max-w-[420px] flex-col border-l border-slate-800 bg-slate-950/90">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <p className="text-xs font-semibold text-slate-300">Inspector</p>
        <button
          type="button"
          onClick={handleCollapse}
          className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-400 transition hover:bg-slate-800"
          aria-label="Collapse inspector"
        >
          ⇨
        </button>
      </div>

      {/* Tab switcher */}
      <div className="border-b border-slate-800 px-2 py-2">
        <div className="flex flex-wrap gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={
                activeTab === tab.id
                  ? 'rounded-md bg-slate-700 px-2 py-1 text-[11px] text-slate-100'
                  : 'rounded-md bg-slate-900 px-2 py-1 text-[11px] text-slate-500 transition hover:bg-slate-800 hover:text-slate-300'
              }
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {activeTab === 'preview' ? <PreviewTab sessionId={sessionId} /> : null}
        {activeTab === 'agent_card' ? <AgentCardTab draft={draft} /> : null}
        {activeTab === 'source_code' ? <SourceCodeTab sessionId={sessionId} /> : null}
        {activeTab === 'tools' ? <ToolsTab tools={adaptToolsFromDraft(draft)} /> : null}
        {activeTab === 'callbacks' ? <CallbacksTab /> : null}
        {activeTab === 'guardrails' ? (
          <GuardrailsTab guardrails={adaptPoliciesFromDraft(draft)} />
        ) : null}
        {activeTab === 'evals' ? <EvalResultsTab bundle={null} /> : null}
        {activeTab === 'trace' ? <TraceViewerTab bookmarks={[]} /> : null}
        {activeTab === 'test_live' ? <TestLiveTab sessionId={sessionId} /> : null}
        {activeTab === 'deploy' ? <DeployTab sessionId={sessionId} /> : null}
        {activeTab === 'activity' ? <FilesTab files={[]} /> : null}
      </div>
    </aside>
  );
}
