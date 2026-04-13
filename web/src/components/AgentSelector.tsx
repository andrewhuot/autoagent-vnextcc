import { Link } from 'react-router-dom';
import { Bot, ChevronsUpDown } from 'lucide-react';
import { useEffect } from 'react';
import { useAgents } from '../lib/api';
import { useActiveAgent } from '../lib/active-agent';
import { classNames } from '../lib/utils';
import type { AgentLibraryItem } from '../lib/types';

interface AgentSelectorProps {
  title?: string;
  description?: string;
  isResolving?: boolean;
  onChange?: (agent: AgentLibraryItem | null) => void;
}

const sourceLabel: Record<string, string> = {
  built: 'Built',
  imported: 'Imported',
  connected: 'Connected',
};

export function AgentSelector({
  title = 'Agent Library',
  description = 'Choose which saved agent this workflow should use.',
  isResolving = false,
  onChange,
}: AgentSelectorProps) {
  const { data: agents, isLoading } = useAgents();
  const { activeAgent, setActiveAgent, clearActiveAgent } = useActiveAgent();

  useEffect(() => {
    if (!activeAgent || !agents?.length) {
      return;
    }
    const refreshed = agents.find((agent) => agent.id === activeAgent.id);
    if (refreshed && refreshed.config_path !== activeAgent.config_path) {
      setActiveAgent(refreshed);
    }
  }, [activeAgent, agents, setActiveAgent]);

  function handleSelection(agentId: string) {
    if (!agentId) {
      clearActiveAgent();
      onChange?.(null);
      return;
    }

    const nextAgent = agents?.find((agent) => agent.id === agentId) ?? null;
    if (!nextAgent) {
      return;
    }

    setActiveAgent(nextAgent);
    onChange?.(nextAgent);
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-800">
              <Bot className="h-3.5 w-3.5" />
              Active agent
            </span>
            {activeAgent ? (
              <>
                <span className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-700">
                  {activeAgent.name}
                </span>
                <span className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500">
                  {activeAgent.model}
                </span>
                <span className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500">
                  {sourceLabel[activeAgent.source] ?? activeAgent.source}
                </span>
              </>
            ) : isResolving ? (
              <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                Resolving selected agent...
              </span>
            ) : (
              <span className="rounded-full border border-dashed border-gray-300 px-3 py-1 text-xs font-medium text-gray-500">
                No agent selected
              </span>
            )}
          </div>
          <h3 className="mt-3 text-sm font-semibold text-gray-900">{title}</h3>
          <p className="mt-1 text-sm text-gray-500">{description}</p>
        </div>

        <div className="w-full max-w-md">
          <label htmlFor="agent-selector" className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
            Select agent
          </label>
          <div className="relative">
            <select
              id="agent-selector"
              aria-label="Agent selector"
              aria-busy={isResolving}
              value={activeAgent?.id ?? ''}
              onChange={(event) => handleSelection(event.target.value)}
              className="w-full appearance-none rounded-xl border border-gray-300 bg-white px-3 py-2.5 pr-10 text-sm text-gray-900 focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-100"
            >
              <option value="">
                {isResolving ? 'Loading agent selection' : activeAgent ? 'Choose another agent' : 'No agent selected'}
              </option>
              {(agents ?? []).map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name} · {agent.model}
                </option>
              ))}
            </select>
            <ChevronsUpDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          </div>
          {activeAgent ? (
            <p className="mt-2 truncate text-xs text-gray-500">{activeAgent.config_path}</p>
          ) : null}
        </div>
      </div>

      {!activeAgent && !isLoading && !isResolving && (
        <div className="mt-4 rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-3">
          <p className="text-sm text-gray-600">
            Pick an agent from the library or create one first so Eval and Optimize can stay on the same config.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link
              to="/build"
              className={classNames(
                'rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50'
              )}
            >
              Open Build
            </Link>
            <Link
              to="/connect"
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              Open Connect
            </Link>
          </div>
        </div>
      )}
    </section>
  );
}
