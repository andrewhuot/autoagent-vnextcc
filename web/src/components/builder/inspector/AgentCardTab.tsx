import type { BuilderConfigDraft } from '../../../lib/builder-types';
import { getCompat } from '../../../lib/workbench-compat';

interface AgentCardTabProps {
  draft: BuilderConfigDraft | null;
}

function CompatPills({ name }: { name: string }) {
  const compat = getCompat(name);
  return (
    <span className="flex gap-1">
      {compat.adk ? (
        <span className="rounded bg-green-900/60 px-1.5 py-0.5 text-[10px] text-green-400">
          ADK ✓
        </span>
      ) : (
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-500">
          ADK —
        </span>
      )}
      {compat.cx ? (
        <span className="rounded bg-blue-900/60 px-1.5 py-0.5 text-[10px] text-blue-400">
          CX ✓
        </span>
      ) : (
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-500">
          CX —
        </span>
      )}
    </span>
  );
}

export function AgentCardTab({ draft }: AgentCardTabProps) {
  if (!draft) {
    return (
      <p className="rounded-md border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-500">
        No agent draft yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Identity */}
      <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Identity
        </p>
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-500">Name</span>
            <span className="text-xs font-medium text-slate-200">{draft.agent_name}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-500">Model</span>
            <span className="font-mono text-[11px] text-slate-300">{draft.model || '—'}</span>
          </div>
        </div>
      </div>

      {/* System Prompt */}
      <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          System Prompt
        </p>
        <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] text-slate-300">
          {draft.system_prompt || '(empty)'}
        </pre>
      </div>

      {/* Tools */}
      {draft.tools.length > 0 ? (
        <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Tools
          </p>
          <div className="flex flex-col gap-2">
            {draft.tools.map((tool, idx) => (
              <div key={tool.id ?? idx} className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-slate-200">{tool.name}</span>
                  <CompatPills name={tool.name} />
                </div>
                {tool.description ? (
                  <p className="text-[11px] text-slate-500">{tool.description}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Routing Rules */}
      {draft.routing_rules.length > 0 ? (
        <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Routing Rules
          </p>
          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] text-slate-300">
            {JSON.stringify(draft.routing_rules, null, 2)}
          </pre>
        </div>
      ) : null}

      {/* Policies */}
      {draft.policies.length > 0 ? (
        <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Policies
          </p>
          <div className="flex flex-col gap-2">
            {draft.policies.map((policy, idx) => (
              <div key={policy.id ?? idx} className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-slate-200">{policy.name}</span>
                  <div className="flex items-center gap-1">
                    {policy.scope ? (
                      <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                        {policy.scope}
                      </span>
                    ) : null}
                    <CompatPills name={policy.name} />
                  </div>
                </div>
                {policy.description ? (
                  <p className="text-[11px] text-slate-500">{policy.description}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
