import { ChevronRight, GitBranch, Workflow, Target } from 'lucide-react';
import { useState } from 'react';
import { classNames } from '../../lib/utils';

interface Specialist {
  name: string;
  description: string;
  intents: string[];
}

interface RoutingRule {
  from: string;
  to: string;
  keywords: string[];
}

export interface AgentPreviewData {
  orchestrator: string;
  specialists: Specialist[];
  routing_rules: RoutingRule[];
  coverage_pct: number;
  intent_count: number;
  tool_count: number;
}

interface AgentPreviewCardProps {
  data: AgentPreviewData;
}

export function AgentPreviewCard({ data }: AgentPreviewCardProps) {
  const [routingOpen, setRoutingOpen] = useState(false);
  const [selectedSpecialist, setSelectedSpecialist] = useState<string | null>(null);

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-medium text-gray-900">Agent Configuration</h3>
          <p className="mt-1 text-xs text-gray-500">
            {data.specialists.length} specialists • {data.intent_count} intents • {data.tool_count} tools
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 rounded-md bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700">
            <Target className="h-3.5 w-3.5" />
            {data.coverage_pct}% coverage
          </span>
        </div>
      </div>

      {/* Agent Tree Visualization */}
      <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div className="flex items-center gap-2">
          <Workflow className="h-4 w-4 text-gray-400" />
          <span className="text-sm font-medium text-gray-700">{data.orchestrator}</span>
          <span className="text-xs text-gray-400">(orchestrator)</span>
        </div>

        <div className="ml-6 mt-3 space-y-2">
          {data.specialists.map((specialist) => (
            <div key={specialist.name} className="flex items-start gap-2">
              <GitBranch className="h-4 w-4 flex-shrink-0 text-gray-400 mt-0.5" />
              <div className="flex-1">
                <button
                  onClick={() => setSelectedSpecialist(selectedSpecialist === specialist.name ? null : specialist.name)}
                  className="flex items-center gap-2 text-left hover:text-gray-900"
                >
                  <span className="text-sm font-medium text-gray-700">{specialist.name}</span>
                  <ChevronRight
                    className={classNames(
                      'h-3.5 w-3.5 text-gray-400 transition-transform',
                      selectedSpecialist === specialist.name ? 'rotate-90' : ''
                    )}
                  />
                </button>
                <p className="mt-0.5 text-xs text-gray-500">{specialist.description}</p>

                {selectedSpecialist === specialist.name && (
                  <div className="mt-2 space-y-2">
                    <div>
                      <p className="text-xs font-medium text-gray-500">Handles intents:</p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {specialist.intents.map((intent) => (
                          <span
                            key={intent}
                            className="rounded-md bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                          >
                            {intent}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Routing Logic Summary */}
      <div className="mt-4 border-t border-gray-100 pt-4">
        <button
          onClick={() => setRoutingOpen(!routingOpen)}
          className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-500 hover:text-gray-700"
        >
          <ChevronRight
            className={classNames(
              'h-3.5 w-3.5 transition-transform',
              routingOpen ? 'rotate-90' : ''
            )}
          />
          Routing Logic ({data.routing_rules.length} rules)
        </button>

        {routingOpen && (
          <div className="mt-3 space-y-2">
            {data.routing_rules.map((rule, idx) => (
              <div key={idx} className="rounded-md bg-gray-50 p-3">
                <div className="flex items-center gap-2 text-xs">
                  <span className="font-medium text-gray-700">{rule.from}</span>
                  <span className="text-gray-400">→</span>
                  <span className="font-medium text-gray-900">{rule.to}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {rule.keywords.map((keyword) => (
                    <span
                      key={keyword}
                      className="rounded-md bg-white px-2 py-0.5 text-xs text-gray-600 border border-gray-200"
                    >
                      {keyword}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Stats Grid */}
      <div className="mt-4 grid grid-cols-3 gap-3 border-t border-gray-100 pt-4">
        <div>
          <p className="text-xs text-gray-500">Specialists</p>
          <p className="mt-1 text-lg font-semibold text-gray-900">{data.specialists.length}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Intents</p>
          <p className="mt-1 text-lg font-semibold text-gray-900">{data.intent_count}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Tools</p>
          <p className="mt-1 text-lg font-semibold text-gray-900">{data.tool_count}</p>
        </div>
      </div>
    </div>
  );
}
