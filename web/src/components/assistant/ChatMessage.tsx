import { useState } from 'react';
import { ChevronDown, ChevronRight, User, Bot, Loader2 } from 'lucide-react';
import type {
  AssistantMessage,
  AssistantThinkingStep,
  AssistantCard,
  AgentPreviewCardData,
  DiagnosisCardData,
  DiffCardData,
  MetricsCardData,
  ConversationCardData,
  ProgressCardData,
  DeployCardData,
  ClusterCardData,
} from '../../lib/types';
import { classNames, formatTimestamp } from '../../lib/utils';
import { StatusBadge } from '../StatusBadge';
import { ConversationView } from '../ConversationView';

interface ChatMessageProps {
  message: AssistantMessage;
  isUser?: boolean;
  isStreaming?: boolean;
}

function ThinkingSteps({ steps }: { steps: AssistantThinkingStep[] }) {
  const [expanded, setExpanded] = useState(false);

  if (steps.length === 0) return null;

  const allCompleted = steps.every((s) => s.completed);
  const currentStep = steps.find((s) => !s.completed) || steps[steps.length - 1];

  return (
    <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 text-left text-sm text-blue-900"
      >
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <Loader2 className={classNames('h-4 w-4', allCompleted ? '' : 'animate-spin')} />
        <span className="font-medium">{currentStep.step}</span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-2">
          {steps.map((step, index) => (
            <div key={index} className="flex items-start gap-2 text-xs text-blue-800">
              <div className="mt-1">
                {step.completed ? (
                  <div className="h-2 w-2 rounded-full bg-green-500" />
                ) : (
                  <Loader2 className="h-3 w-3 animate-spin" />
                )}
              </div>
              <div className="flex-1">
                <div className="font-medium">{step.step}</div>
                {step.details !== undefined && (
                  <pre className="mt-1 overflow-x-auto rounded bg-blue-100 p-2 font-mono text-[10px] text-blue-900">
                    {typeof step.details === 'object' ? JSON.stringify(step.details, null, 2) : String(step.details)}
                  </pre>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentPreviewCard({ data }: { data: AgentPreviewCardData }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">Agent Configuration</h3>

      <div className="mb-4 grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-gray-50 p-3">
          <p className="text-xs text-gray-500">Coverage</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{data.coverage_pct}%</p>
        </div>
        <div className="rounded-lg bg-gray-50 p-3">
          <p className="text-xs text-gray-500">Intents</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{data.intent_count}</p>
        </div>
        <div className="rounded-lg bg-gray-50 p-3">
          <p className="text-xs text-gray-500">Tools</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{data.tool_count}</p>
        </div>
      </div>

      <div className="mb-3">
        <h4 className="mb-2 text-xs font-medium text-gray-700">Specialist Agents</h4>
        <div className="space-y-2">
          {data.specialists.map((specialist, index) => (
            <div key={index} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-900">{specialist.name}</p>
                  <p className="mt-1 text-xs text-gray-600">{specialist.description}</p>
                </div>
                <span className="ml-2 text-xs text-gray-500">{specialist.coverage_pct}%</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg bg-blue-50 p-3">
        <p className="text-xs font-medium text-blue-900">Routing Summary</p>
        <p className="mt-1 text-xs text-blue-700">{data.routing_summary}</p>
      </div>
    </div>
  );
}

function DiagnosisCard({ data }: { data: DiagnosisCardData }) {
  const trendColor =
    data.trend === 'increasing' ? 'text-red-600' : data.trend === 'decreasing' ? 'text-green-600' : 'text-gray-600';

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <h3 className="mb-2 text-sm font-semibold text-amber-900">{data.title}</h3>
      <p className="mb-3 text-sm text-amber-800">{data.description}</p>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-white p-3">
          <p className="text-xs text-gray-500">Impact Score</p>
          <p className="mt-1 text-xl font-semibold text-gray-900">{data.impact_score.toFixed(1)}</p>
        </div>
        <div className="rounded-lg bg-white p-3">
          <p className="text-xs text-gray-500">Affected Conversations</p>
          <p className="mt-1 text-xl font-semibold text-gray-900">{data.affected_conversations}</p>
        </div>
      </div>

      {data.trend && (
        <div className="mt-3 text-xs">
          <span className="text-gray-600">Trend: </span>
          <span className={classNames('font-medium', trendColor)}>{data.trend}</span>
        </div>
      )}
    </div>
  );
}

function DiffCard({ data }: { data: DiffCardData }) {
  const riskColor =
    data.risk_level === 'high' ? 'border-red-200 bg-red-50' : data.risk_level === 'medium' ? 'border-amber-200 bg-amber-50' : 'border-green-200 bg-green-50';

  return (
    <div className={classNames('rounded-lg border p-4', riskColor)}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Configuration Change</h3>
        <StatusBadge
          variant={data.risk_level === 'high' ? 'error' : data.risk_level === 'medium' ? 'warning' : 'success'}
          label={`${data.risk_level} risk`}
        />
      </div>

      <p className="mb-3 text-sm text-gray-700">{data.description}</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-3">
          <p className="mb-2 text-xs font-medium text-gray-500">Before</p>
          <pre className="overflow-x-auto text-xs text-gray-900">{data.before}</pre>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-3">
          <p className="mb-2 text-xs font-medium text-gray-500">After</p>
          <pre className="overflow-x-auto text-xs text-gray-900">{data.after}</pre>
        </div>
      </div>
    </div>
  );
}

function MetricsCard({ data }: { data: MetricsCardData }) {
  const metrics = Object.keys(data.before);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">Metrics Comparison</h3>

      <div className="space-y-3">
        {metrics.map((metric) => {
          const before = data.before[metric];
          const after = data.after[metric];
          const delta = after - before;
          const deltaPercent = before !== 0 ? (delta / before) * 100 : 0;
          const improved = delta > 0;

          return (
            <div key={metric} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700">{metric}</span>
                <span className={classNames('text-xs font-medium', improved ? 'text-green-600' : 'text-red-600')}>
                  {improved ? '+' : ''}
                  {deltaPercent.toFixed(1)}%
                </span>
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs text-gray-600">
                <span>Before: {before.toFixed(3)}</span>
                <span>→</span>
                <span>After: {after.toFixed(3)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {data.p_value !== undefined && (
        <div className="mt-3 rounded-lg bg-blue-50 p-3 text-xs text-blue-800">
          Statistical significance: p = {data.p_value.toFixed(4)}
        </div>
      )}
    </div>
  );
}

function ConversationCard({ data }: { data: ConversationCardData }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Conversation Example</h3>
        <span className="font-mono text-xs text-gray-500">{data.conversation_id.slice(0, 8)}</span>
      </div>

      <ConversationView turns={data.turns} outcome={data.outcome} />
    </div>
  );
}

function ProgressCard({ data }: { data: ProgressCardData }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="space-y-2">
        {data.steps.map((step, index) => (
          <div key={index} className="flex items-start gap-2">
            <div className="mt-1">
              {step.status === 'completed' ? (
                <div className="h-2 w-2 rounded-full bg-green-500" />
              ) : step.status === 'running' ? (
                <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
              ) : step.status === 'failed' ? (
                <div className="h-2 w-2 rounded-full bg-red-500" />
              ) : (
                <div className="h-2 w-2 rounded-full bg-gray-300" />
              )}
            </div>
            <div className="flex-1">
              <p className="text-sm text-gray-900">{step.name}</p>
              {step.details !== undefined && <p className="mt-1 text-xs text-gray-600">{step.details}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DeployCard({ data }: { data: DeployCardData }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Deployment Status</h3>
        <StatusBadge
          variant={
            data.status === 'deployed' ? 'success' : data.status === 'failed' ? 'error' : data.status === 'deploying' ? 'running' : 'pending'
          }
          label={data.status}
        />
      </div>

      {data.canary_progress !== undefined && (
        <div className="mb-3">
          <div className="mb-1 flex items-center justify-between text-xs text-gray-600">
            <span>Canary Progress</span>
            <span>{data.canary_progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full rounded-full bg-blue-500 transition-all"
              style={{ width: `${data.canary_progress}%` }}
            />
          </div>
        </div>
      )}

      {data.can_rollback && (
        <button className="w-full rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50">
          Rollback
        </button>
      )}
    </div>
  );
}

function ClusterCard({ data }: { data: ClusterCardData }) {
  const trendColor =
    data.trend === 'increasing' ? 'text-red-600' : data.trend === 'decreasing' ? 'text-green-600' : 'text-gray-600';

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-2 flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-100 text-xs font-semibold text-blue-700">
            {data.rank}
          </span>
          <h3 className="text-sm font-semibold text-gray-900">{data.title}</h3>
        </div>
        <span className={classNames('text-xs font-medium', trendColor)}>{data.trend}</span>
      </div>

      <p className="mb-3 text-sm text-gray-700">{data.description}</p>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-gray-50 p-2">
          <p className="text-xs text-gray-500">Conversations</p>
          <p className="mt-1 text-lg font-semibold text-gray-900">{data.count}</p>
        </div>
        <div className="rounded-lg bg-gray-50 p-2">
          <p className="text-xs text-gray-500">Impact</p>
          <p className="mt-1 text-lg font-semibold text-gray-900">{data.impact.toFixed(1)}</p>
        </div>
      </div>
    </div>
  );
}

function CardRenderer({ card }: { card: AssistantCard }) {
  switch (card.type) {
    case 'agent_preview':
      return <AgentPreviewCard data={card.data as AgentPreviewCardData} />;
    case 'diagnosis':
      return <DiagnosisCard data={card.data as DiagnosisCardData} />;
    case 'diff':
      return <DiffCard data={card.data as DiffCardData} />;
    case 'metrics':
      return <MetricsCard data={card.data as MetricsCardData} />;
    case 'conversation':
      return <ConversationCard data={card.data as ConversationCardData} />;
    case 'progress':
      return <ProgressCard data={card.data as ProgressCardData} />;
    case 'deploy':
      return <DeployCard data={card.data as DeployCardData} />;
    case 'cluster':
      return <ClusterCard data={card.data as ClusterCardData} />;
    default:
      return null;
  }
}

export function ChatMessage({ message, isUser = false, isStreaming = false }: ChatMessageProps) {
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg bg-blue-600 px-4 py-3 text-white">
          <div className="flex items-start gap-3">
            <div className="flex-1">
              <p className="whitespace-pre-wrap text-sm">{message.content}</p>
            </div>
            <User className="h-5 w-5 flex-shrink-0" />
          </div>
          <p className="mt-2 text-right text-xs text-blue-200">{formatTimestamp(message.timestamp)}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] space-y-3">
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-900">
            <Bot className="h-5 w-5 text-white" />
          </div>
          <div className="flex-1 space-y-3">
            {message.thinking_steps && message.thinking_steps.length > 0 && (
              <ThinkingSteps steps={message.thinking_steps} />
            )}

            {message.content && (
              <div className="rounded-lg bg-gray-100 px-4 py-3 text-gray-900">
                <p className="whitespace-pre-wrap text-sm">{message.content}</p>
              </div>
            )}

            {message.cards && message.cards.length > 0 && (
              <div className="space-y-3">
                {message.cards.map((card, index) => (
                  <CardRenderer key={index} card={card} />
                ))}
              </div>
            )}

            {isStreaming && !message.content && (!message.cards || message.cards.length === 0) && (
              <div className="rounded-lg bg-gray-100 px-4 py-3">
                <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
              </div>
            )}
          </div>
        </div>

        <p className="ml-11 text-xs text-gray-500">{formatTimestamp(message.timestamp)}</p>
      </div>
    </div>
  );
}
