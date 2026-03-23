import { useMemo, useState } from 'react';
import { MessageSquare } from 'lucide-react';
import { useConversations } from '../lib/api';
import { DataTable, type Column } from '../components/DataTable';
import { StatusBadge } from '../components/StatusBadge';
import { ConversationView } from '../components/ConversationView';
import { EmptyState } from '../components/EmptyState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { formatLatency, formatPercent, formatTimestamp, statusVariant, truncate } from '../lib/utils';
import type { ConversationRecord } from '../lib/types';

export function Conversations() {
  const [outcome, setOutcome] = useState('all');
  const [limit, setLimit] = useState(50);
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: conversations, isLoading, isError, refetch } = useConversations({
    outcome,
    limit,
    search,
  });

  const stats = useMemo(() => {
    if (!conversations || conversations.length === 0) {
      return { total: 0, successRate: 0, avgLatency: 0, avgTokens: 0 };
    }

    const successCount = conversations.filter((entry) => entry.outcome === 'success').length;
    const avgLatency =
      conversations.reduce((sum, entry) => sum + entry.latency_ms, 0) / conversations.length;
    const avgTokens =
      conversations.reduce((sum, entry) => sum + entry.token_count, 0) / conversations.length;

    return {
      total: conversations.length,
      successRate: successCount / conversations.length,
      avgLatency,
      avgTokens,
    };
  }, [conversations]);

  const columns: Column<ConversationRecord>[] = [
    {
      key: 'conversation_id',
      header: 'ID',
      render: (row) => <span className="font-mono text-xs text-gray-700">{row.conversation_id.slice(0, 8)}</span>,
    },
    {
      key: 'timestamp',
      header: 'Time',
      render: (row) => <span className="text-gray-600">{formatTimestamp(row.timestamp)}</span>,
    },
    {
      key: 'user_message',
      header: 'User Message',
      render: (row) => <span className="text-gray-700">{truncate(row.user_message, 72)}</span>,
    },
    {
      key: 'outcome',
      header: 'Outcome',
      render: (row) => <StatusBadge variant={statusVariant(row.outcome)} label={row.outcome} />,
    },
    {
      key: 'specialist',
      header: 'Specialist',
      render: (row) => <span className="text-gray-600">{row.specialist}</span>,
    },
    {
      key: 'latency',
      header: 'Latency',
      render: (row) => <span className="text-gray-600">{formatLatency(row.latency_ms)}</span>,
    },
  ];

  const expandedConversation =
    expandedId && conversations ? conversations.find((entry) => entry.conversation_id === expandedId) : null;

  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={4} />
        <LoadingSkeleton rows={8} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Conversations"
        description="Inspect production interactions, tool traces, and failure signals to guide optimization work."
        actions={
          <button
            onClick={() => refetch()}
            className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
          >
            Refresh
          </button>
        }
      />

      {isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load conversations.
        </div>
      )}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Visible Conversations</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{stats.total}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Success Rate</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{formatPercent(stats.successRate)}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Avg Latency</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{formatLatency(stats.avgLatency)}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Avg Tokens</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{Math.round(stats.avgTokens)}</p>
        </div>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">Outcome</label>
            <select
              value={outcome}
              onChange={(event) => setOutcome(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="all">All</option>
              <option value="success">Success</option>
              <option value="fail">Fail</option>
              <option value="error">Error</option>
              <option value="abandon">Abandon</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">Limit</label>
            <select
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">Search</label>
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search user or agent text"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>
      </section>

      {conversations && conversations.length > 0 ? (
        <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <DataTable
            columns={columns}
            data={conversations}
            keyExtractor={(row) => row.conversation_id}
            onRowClick={(row) => setExpandedId((current) => (current === row.conversation_id ? null : row.conversation_id))}
          />
        </section>
      ) : (
        <EmptyState
          icon={MessageSquare}
          title="No conversations found"
          description="Conversations appear here as the agent handles traffic. Try widening filters if you expected records."
        />
      )}

      {expandedConversation && (
        <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-mono text-sm text-gray-700">Conversation {expandedConversation.conversation_id.slice(0, 12)}</h3>
              <p className="mt-1 text-xs text-gray-500">
                {formatTimestamp(expandedConversation.timestamp)} · {expandedConversation.config_version || 'unversioned config'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge variant={statusVariant(expandedConversation.outcome)} label={expandedConversation.outcome} />
              <button
                onClick={() => setExpandedId(null)}
                className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>

          <ConversationView turns={expandedConversation.turns} outcome={expandedConversation.outcome} />

          {expandedConversation.safety_flags.length > 0 && (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              Safety flags: {expandedConversation.safety_flags.join(', ')}
            </div>
          )}

          {expandedConversation.error_message && (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              Error: {expandedConversation.error_message}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
