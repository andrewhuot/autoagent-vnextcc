import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  ArchiveEntry,
  AutoFixApplyOutcome,
  AutoFixHistoryEntry,
  AutoFixProposal,
  CanaryStatus,
  ChangeCard,
  ContextHealthReport,
  ContextSimulationResult,
  ContextTraceAnalysis,
  ConfigDiff,
  ConfigShow,
  ConfigVersion,
  ConversationRecord,
  ConversationTurn,
  CxAgentSummary,
  CxImportResult,
  CxExportResult,
  CxDeployResult,
  CxWidgetResult,
  CxChange,
  DeployHistoryEntry,
  DeployResponse,
  DeployStatus,
  DiffLine,
  EvalResult,
  EvalRun,
  ExperimentCard,
  JudgeCalibration,
  JudgeDriftReport,
  JudgeFeedbackRecord,
  JudgeOpsJudgeSummary,
  ParetoFrontier,
  Runbook,
  ProjectMemory,
  HealthReport,
  LoopStatus,
  OptimizationAttempt,
  OptimizationOpportunity,
  OptimizeResult,
  TaskStatus,
  Trace,
  TraceEvent,
} from './types';

const API_BASE = '/api';

export class ApiRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = 'ApiRequestError';
  }
}

type RequestOptions = RequestInit;

async function fetchApi<T>(path: string, options?: RequestOptions): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let errorMessage = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      errorMessage = payload?.detail || payload?.message || JSON.stringify(payload);
    } catch {
      const text = await response.text().catch(() => 'Unknown error');
      errorMessage = text || errorMessage;
    }
    throw new ApiRequestError(errorMessage, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function fromEpoch(value: number | string | null | undefined): string {
  if (value === null || value === undefined) {
    return new Date().toISOString();
  }
  if (typeof value === 'number') {
    return new Date(value * 1000).toISOString();
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? new Date().toISOString() : new Date(parsed).toISOString();
}

function percent(value: number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return value * 100;
}

function parseDiffLines(diff: string): DiffLine[] {
  if (!diff.trim()) return [];

  const lines = diff.split('\n');
  const parsed: DiffLine[] = [];
  let leftLine = 1;
  let rightLine = 1;

  for (const line of lines) {
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')) {
      continue;
    }

    if (line.startsWith('+')) {
      parsed.push({
        type: 'added',
        content: line.slice(1),
        line_a: null,
        line_b: rightLine,
      });
      rightLine += 1;
      continue;
    }

    if (line.startsWith('-')) {
      parsed.push({
        type: 'removed',
        content: line.slice(1),
        line_a: leftLine,
        line_b: null,
      });
      leftLine += 1;
      continue;
    }

    parsed.push({
      type: 'unchanged',
      content: line,
      line_a: leftLine,
      line_b: rightLine,
    });
    leftLine += 1;
    rightLine += 1;
  }

  return parsed;
}

interface EvalResultRaw {
  run_id: string;
  quality: number;
  safety: number;
  latency: number;
  cost: number;
  composite: number;
  safety_failures: number;
  total_cases: number;
  passed_cases: number;
  cases: Array<{
    case_id: string;
    category: string;
    passed: boolean;
    quality_score: number;
    safety_passed: boolean;
    latency_ms: number;
    token_count: number;
    details: string;
  }>;
  completed_at: string | null;
}

interface TaskStatusRaw {
  task_id: string;
  task_type: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  result: unknown;
  error: string | null;
  created_at: string;
  updated_at: string;
}

function mapTask(task: TaskStatusRaw): TaskStatus {
  return {
    task_id: task.task_id,
    task_type: task.task_type,
    status: task.status,
    progress: task.progress,
    result: task.result,
    error: task.error,
    created_at: task.created_at,
    updated_at: task.updated_at,
  };
}

function mapEvalTask(task: TaskStatusRaw): EvalRun {
  const result = (task.result || {}) as Partial<EvalResultRaw>;
  return {
    run_id: task.task_id,
    timestamp: task.created_at,
    status: task.status,
    progress: task.progress,
    composite_score: percent(result.composite),
    total_cases: result.total_cases || 0,
    passed_cases: result.passed_cases || 0,
  };
}

function mapEvalResult(raw: EvalResultRaw, status: TaskStatusRaw['status'] = 'completed', progress = 100): EvalResult {
  return {
    run_id: raw.run_id,
    status,
    progress,
    timestamp: raw.completed_at || new Date().toISOString(),
    composite_score: {
      overall: percent(raw.composite),
      quality: percent(raw.quality),
      safety: percent(raw.safety),
      latency: percent(raw.latency),
      cost: percent(raw.cost),
    },
    total_cases: raw.total_cases,
    passed_cases: raw.passed_cases,
    failed_cases: raw.total_cases - raw.passed_cases,
    safety_failures: raw.safety_failures,
    cases: raw.cases.map((entry) => ({
      case_id: entry.case_id,
      category: entry.category,
      passed: entry.passed,
      quality_score: percent(entry.quality_score),
      safety_passed: entry.safety_passed,
      latency_ms: entry.latency_ms,
      token_count: entry.token_count,
      details: entry.details,
    })),
  };
}

function toConversationTurns(record: {
  user_message: string;
  agent_response: string;
  tool_calls: Array<Record<string, unknown>>;
  timestamp: number;
}): ConversationTurn[] {
  const turns: ConversationTurn[] = [
    {
      role: 'user',
      content: record.user_message,
      timestamp: fromEpoch(record.timestamp),
    },
    {
      role: 'agent',
      content: record.agent_response,
      timestamp: fromEpoch(record.timestamp),
    },
  ];

  for (const toolCall of record.tool_calls || []) {
    const toolName =
      typeof toolCall.name === 'string'
        ? toolCall.name
        : typeof toolCall.tool_name === 'string'
          ? toolCall.tool_name
          : 'tool_call';
    const input = toolCall.input ?? toolCall.arguments ?? toolCall.tool_input;
    const output = toolCall.output ?? toolCall.result ?? toolCall.tool_output;

    turns.push({
      role: 'tool',
      content: `${toolName}`,
      tool_name: toolName,
      tool_input: input ? JSON.stringify(input, null, 2) : undefined,
      tool_output: output ? JSON.stringify(output, null, 2) : undefined,
      timestamp: fromEpoch(record.timestamp),
    });
  }

  return turns;
}

// Health
export function useHealth() {
  return useQuery<HealthReport>({
    queryKey: ['health'],
    queryFn: () => fetchApi('/health'),
  });
}

// Eval
export function useEvalRuns() {
  return useQuery<EvalRun[]>({
    queryKey: ['evalRuns'],
    queryFn: async () => {
      const tasks = await fetchApi<TaskStatusRaw[]>('/eval/runs');
      return tasks.map(mapEvalTask);
    },
    refetchInterval: 5000,
  });
}

export function useEvalDetail(runId: string | undefined) {
  return useQuery<EvalResult>({
    queryKey: ['evalDetail', runId],
    enabled: Boolean(runId),
    queryFn: async () => {
      if (!runId) {
        throw new ApiRequestError('Missing run ID', 400);
      }

      try {
        const raw = await fetchApi<EvalResultRaw>(`/eval/runs/${runId}`);
        return mapEvalResult(raw, 'completed', 100);
      } catch (error) {
        if (error instanceof ApiRequestError && error.status === 409) {
          const tasks = await fetchApi<TaskStatusRaw[]>('/eval/runs');
          const task = tasks.find((entry) => entry.task_id === runId);
          if (!task) {
            throw new ApiRequestError(`Eval run not found: ${runId}`, 404);
          }

          const partial = (task.result || {
            run_id: task.task_id,
            quality: 0,
            safety: 0,
            latency: 0,
            cost: 0,
            composite: 0,
            safety_failures: 0,
            total_cases: 0,
            passed_cases: 0,
            cases: [],
            completed_at: null,
          }) as EvalResultRaw;

          return mapEvalResult(partial, task.status, task.progress);
        }
        throw error;
      }
    },
    refetchInterval: (query) => {
      if (query.state.data?.status === 'completed') return false;
      return 3000;
    },
  });
}

export function useStartEval() {
  const queryClient = useQueryClient();

  return useMutation<{ task_id: string; message: string }, ApiRequestError, { config_path?: string; category?: string }>({
    mutationFn: (params) =>
      fetchApi('/eval/run', {
        method: 'POST',
        body: JSON.stringify(params),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evalRuns'] });
    },
  });
}

// Optimize
export function useOptimizeHistory() {
  return useQuery<OptimizationAttempt[]>({
    queryKey: ['optimizeHistory'],
    queryFn: async () => {
      const rows = await fetchApi<
        Array<{
          attempt_id: string;
          timestamp: number;
          change_description: string;
          config_diff: string;
          config_section: string;
          status: OptimizationAttempt['status'];
          score_before: number;
          score_after: number;
          health_context: string;
        }>
      >('/optimize/history');

      return rows.map((row) => ({
        attempt_id: row.attempt_id,
        timestamp: fromEpoch(row.timestamp),
        change_description: row.change_description,
        config_diff: row.config_diff,
        config_section: row.config_section,
        status: row.status,
        score_before: percent(row.score_before),
        score_after: percent(row.score_after),
        score_delta: percent(row.score_after - row.score_before),
        health_context: row.health_context,
      }));
    },
  });
}

export function useStartOptimize() {
  const queryClient = useQueryClient();

  return useMutation<OptimizeResult, ApiRequestError, { window: number; force: boolean }>({
    mutationFn: (params) =>
      fetchApi('/optimize/run', {
        method: 'POST',
        body: JSON.stringify(params),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['optimizeHistory'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
    },
  });
}

// Config
export function useConfigs() {
  return useQuery<ConfigVersion[]>({
    queryKey: ['configs'],
    queryFn: async () => {
      const payload = await fetchApi<{
        versions: Array<{
          version: number;
          config_hash: string;
          filename: string;
          timestamp: number;
          scores: Record<string, number>;
          status: ConfigVersion['status'];
        }>;
      }>('/config/list');

      return payload.versions
        .slice()
        .sort((a, b) => b.version - a.version)
        .map((version) => ({
          version: version.version,
          config_hash: version.config_hash,
          filename: version.filename,
          timestamp: fromEpoch(version.timestamp),
          status: version.status,
          composite_score:
            typeof version.scores?.composite === 'number'
              ? percent(version.scores.composite)
              : null,
        }));
    },
  });
}

export function useConfigShow(version: number | null) {
  return useQuery<ConfigShow>({
    queryKey: ['configShow', version],
    enabled: version !== null,
    queryFn: () => fetchApi(`/config/show/${version}`),
  });
}

export function useConfigDiff(versionA: number | null, versionB: number | null) {
  return useQuery<ConfigDiff>({
    queryKey: ['configDiff', versionA, versionB],
    enabled: versionA !== null && versionB !== null,
    queryFn: async () => {
      const payload = await fetchApi<{ version_a: number; version_b: number; diff: string }>(
        `/config/diff?a=${versionA}&b=${versionB}`
      );

      return {
        version_a: payload.version_a,
        version_b: payload.version_b,
        diff: payload.diff,
        diff_lines: parseDiffLines(payload.diff),
      };
    },
  });
}

// Conversations
export function useConversations(filters: {
  outcome?: string;
  limit?: number;
  search?: string;
}) {
  return useQuery<ConversationRecord[]>({
    queryKey: ['conversations', filters],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (filters.limit) params.set('limit', String(filters.limit));
      if (filters.outcome && filters.outcome !== 'all') params.set('outcome', filters.outcome);

      const response = await fetchApi<{
        conversations: Array<{
          conversation_id: string;
          user_message: string;
          agent_response: string;
          tool_calls: Array<Record<string, unknown>>;
          latency_ms: number;
          token_count: number;
          outcome: string;
          safety_flags: string[];
          error_message: string;
          specialist_used: string;
          config_version: string;
          timestamp: number;
        }>;
      }>(`/conversations?${params.toString()}`);

      const mapped = response.conversations.map((record) => ({
        conversation_id: record.conversation_id,
        timestamp: fromEpoch(record.timestamp),
        user_message: record.user_message,
        agent_response: record.agent_response,
        outcome: record.outcome,
        specialist: record.specialist_used || 'unassigned',
        latency_ms: record.latency_ms,
        token_count: record.token_count,
        safety_flags: record.safety_flags,
        error_message: record.error_message,
        config_version: record.config_version,
        tool_calls: record.tool_calls,
        turns: toConversationTurns(record),
      }));

      if (!filters.search?.trim()) {
        return mapped;
      }

      const term = filters.search.toLowerCase();
      return mapped.filter(
        (conversation) =>
          conversation.user_message.toLowerCase().includes(term) ||
          conversation.agent_response.toLowerCase().includes(term)
      );
    },
  });
}

// Deploy
function mapDeployHistory(entries: Array<Record<string, unknown>>): DeployHistoryEntry[] {
  return entries
    .slice()
    .sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0))
    .map((entry) => ({
      version: Number(entry.version || 0),
      config_hash: String(entry.config_hash || ''),
      filename: String(entry.filename || ''),
      timestamp: fromEpoch(Number(entry.timestamp || 0)),
      scores: (entry.scores || {}) as Record<string, number>,
      status: String(entry.status || 'unknown'),
    }));
}

function mapCanaryStatus(payload: Record<string, unknown> | null): CanaryStatus | null {
  if (!payload) return null;
  return {
    is_active: Boolean(payload.is_active),
    canary_version: Number(payload.canary_version || 0),
    baseline_version:
      payload.baseline_version === null || payload.baseline_version === undefined
        ? null
        : Number(payload.baseline_version),
    canary_conversations: Number(payload.canary_conversations || 0),
    canary_success_rate: Number(payload.canary_success_rate || 0),
    baseline_success_rate: Number(payload.baseline_success_rate || 0),
    started_at: fromEpoch(Number(payload.started_at || 0)),
    verdict: String(payload.verdict || 'pending'),
  };
}

export function useDeployStatus() {
  return useQuery<DeployStatus>({
    queryKey: ['deployStatus'],
    queryFn: async () => {
      const payload = await fetchApi<{
        active_version: number | null;
        canary_version: number | null;
        total_versions: number;
        canary_status: Record<string, unknown> | null;
        history: Array<Record<string, unknown>>;
      }>('/deploy/status');

      return {
        active_version: payload.active_version,
        canary_version: payload.canary_version,
        total_versions: payload.total_versions,
        canary_status: mapCanaryStatus(payload.canary_status),
        history: mapDeployHistory(payload.history || []),
      };
    },
    refetchInterval: 5000,
  });
}

export function useCanaryStatus() {
  return useQuery<CanaryStatus | null>({
    queryKey: ['deployStatus', 'canary'],
    queryFn: async () => {
      const payload = await fetchApi<{
        canary_status: Record<string, unknown> | null;
      }>('/deploy/status');
      return mapCanaryStatus(payload.canary_status);
    },
    refetchInterval: 5000,
  });
}

export function useDeployHistory() {
  return useQuery<DeployHistoryEntry[]>({
    queryKey: ['deployHistory'],
    queryFn: async () => {
      const payload = await fetchApi<{ history: Array<Record<string, unknown>> }>('/deploy/status');
      return mapDeployHistory(payload.history || []);
    },
  });
}

export function useDeploy() {
  const queryClient = useQueryClient();

  return useMutation<DeployResponse, ApiRequestError, { version: number; strategy: 'canary' | 'immediate' }>({
    mutationFn: async ({ version, strategy }) => {
      if (strategy === 'immediate') {
        return fetchApi('/deploy', {
          method: 'POST',
          body: JSON.stringify({ version, strategy: 'immediate' }),
        });
      }

      const config = await fetchApi<ConfigShow>(`/config/show/${version}`);
      return fetchApi('/deploy', {
        method: 'POST',
        body: JSON.stringify({ config: config.config, strategy: 'canary' }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deployStatus'] });
      queryClient.invalidateQueries({ queryKey: ['deployHistory'] });
      queryClient.invalidateQueries({ queryKey: ['configs'] });
    },
  });
}

export function useRollback() {
  const queryClient = useQueryClient();

  return useMutation<DeployResponse, ApiRequestError, void>({
    mutationFn: () =>
      fetchApi('/deploy/rollback', {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deployStatus'] });
      queryClient.invalidateQueries({ queryKey: ['deployHistory'] });
      queryClient.invalidateQueries({ queryKey: ['configs'] });
    },
  });
}

// Loop
export function useLoopStatus() {
  return useQuery<LoopStatus>({
    queryKey: ['loopStatus'],
    queryFn: () => fetchApi('/loop/status'),
    refetchInterval: 3000,
  });
}

export function useStartLoop() {
  const queryClient = useQueryClient();

  return useMutation<LoopStatus, ApiRequestError, { cycles: number; delay: number; window: number }>({
    mutationFn: (params) =>
      fetchApi('/loop/start', {
        method: 'POST',
        body: JSON.stringify(params),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['loopStatus'] });
    },
  });
}

export function useStopLoop() {
  const queryClient = useQueryClient();

  return useMutation<LoopStatus, ApiRequestError, void>({
    mutationFn: () =>
      fetchApi('/loop/stop', {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['loopStatus'] });
    },
  });
}

// Generic background task helpers
export function useTaskStatus(taskId: string | null) {
  return useQuery<TaskStatus>({
    queryKey: ['taskStatus', taskId],
    enabled: Boolean(taskId),
    queryFn: async () => {
      const payload = await fetchApi<TaskStatusRaw>(`/tasks/${taskId}`);
      return mapTask(payload);
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || status === 'running' || status === 'pending') return 2000;
      return false;
    },
  });
}

export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const payload = await fetchApi<TaskStatusRaw>(`/tasks/${taskId}`);
  return mapTask(payload);
}

// Traces

interface TraceEventsResponse {
  events: TraceEvent[];
  message?: string;
}

interface TraceDetailResponse {
  trace_id: string;
  events: TraceEvent[];
  spans: unknown[];
  message?: string;
}

export function useRecentTraces() {
  return useQuery<TraceEvent[]>({
    queryKey: ['traces', 'recent'],
    queryFn: async () => {
      const payload = await fetchApi<TraceEventsResponse>('/traces/recent');
      return payload.events ?? [];
    },
    refetchInterval: 5000,
  });
}

export function useTraceDetail(traceId: string | undefined) {
  return useQuery<Trace>({
    queryKey: ['traces', 'detail', traceId],
    enabled: Boolean(traceId),
    queryFn: async () => {
      if (!traceId) throw new ApiRequestError('Missing trace ID', 400);
      const payload = await fetchApi<TraceDetailResponse>(`/traces/${traceId}`);
      return {
        trace_id: payload.trace_id,
        events: payload.events ?? [],
      };
    },
  });
}

export function useTraceSearch(params: {
  event_type?: string;
  agent_path?: string;
  since?: number;
  limit?: number;
}) {
  return useQuery<TraceEvent[]>({
    queryKey: ['traces', 'search', params],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (params.event_type) qs.set('event_type', params.event_type);
      if (params.agent_path) qs.set('agent_path', params.agent_path);
      if (params.since !== undefined) qs.set('since', String(params.since));
      if (params.limit !== undefined) qs.set('limit', String(params.limit));
      const payload = await fetchApi<TraceEventsResponse>(`/traces/search?${qs.toString()}`);
      return payload.events ?? [];
    },
  });
}

export function useTraceErrors() {
  return useQuery<TraceEvent[]>({
    queryKey: ['traces', 'errors'],
    queryFn: async () => {
      const payload = await fetchApi<TraceEventsResponse>('/traces/errors');
      return payload.events ?? [];
    },
    refetchInterval: 10000,
  });
}

// Opportunities

interface OpportunitiesResponse {
  opportunities: OptimizationOpportunity[];
}

interface OpportunityCountResponse {
  open: number;
}

interface UpdateOpportunityStatusParams {
  opportunity_id: string;
  status: string;
  resolution_experiment_id?: string;
}

interface UpdateOpportunityStatusResponse {
  opportunity_id: string;
  status: string;
}

export function useOpportunities(statusFilter = 'open') {
  return useQuery<OptimizationOpportunity[]>({
    queryKey: ['opportunities', statusFilter],
    queryFn: async () => {
      const qs = new URLSearchParams({ status: statusFilter });
      const payload = await fetchApi<OpportunitiesResponse>(`/opportunities?${qs.toString()}`);
      return payload.opportunities ?? [];
    },
    refetchInterval: 10000,
  });
}

export function useOpportunityCount() {
  return useQuery<OpportunityCountResponse>({
    queryKey: ['opportunities', 'count'],
    queryFn: () => fetchApi<OpportunityCountResponse>('/opportunities/count'),
    refetchInterval: 10000,
  });
}

export function useOpportunityDetail(id: string | undefined) {
  return useQuery<OptimizationOpportunity>({
    queryKey: ['opportunities', 'detail', id],
    enabled: Boolean(id),
    queryFn: async () => {
      if (!id) throw new ApiRequestError('Missing opportunity ID', 400);
      return fetchApi<OptimizationOpportunity>(`/opportunities/${id}`);
    },
  });
}

export function useUpdateOpportunityStatus() {
  const queryClient = useQueryClient();

  return useMutation<UpdateOpportunityStatusResponse, ApiRequestError, UpdateOpportunityStatusParams>({
    mutationFn: ({ opportunity_id, status, resolution_experiment_id }) =>
      fetchApi(`/opportunities/${opportunity_id}/status`, {
        method: 'POST',
        body: JSON.stringify({ status, resolution_experiment_id }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunities'] });
    },
  });
}

// Experiments

interface ExperimentsResponse {
  experiments: ExperimentCard[];
}

interface ExperimentStatsResponse {
  counts: Record<string, number>;
}

export function useExperiments(statusFilter?: string) {
  return useQuery<ExperimentCard[]>({
    queryKey: ['experiments', statusFilter ?? 'all'],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (statusFilter) qs.set('status', statusFilter);
      const query = qs.toString() ? `?${qs.toString()}` : '';
      const payload = await fetchApi<ExperimentsResponse>(`/experiments${query}`);
      return payload.experiments ?? [];
    },
    refetchInterval: 10000,
  });
}

export function useExperimentDetail(id: string | undefined) {
  return useQuery<ExperimentCard>({
    queryKey: ['experiments', 'detail', id],
    enabled: Boolean(id),
    queryFn: async () => {
      if (!id) throw new ApiRequestError('Missing experiment ID', 400);
      return fetchApi<ExperimentCard>(`/experiments/${id}`);
    },
  });
}

export function useExperimentStats() {
  return useQuery<ExperimentStatsResponse>({
    queryKey: ['experiments', 'stats'],
    queryFn: () => fetchApi<ExperimentStatsResponse>('/experiments/stats'),
    refetchInterval: 10000,
  });
}

export function useParetoFrontier() {
  return useQuery<ParetoFrontier>({
    queryKey: ['pareto', 'frontier'],
    queryFn: () => fetchApi<ParetoFrontier>('/experiments/pareto'),
    refetchInterval: 15000,
  });
}

// Archive

export function useArchiveEntries() {
  return useQuery<ArchiveEntry[]>({
    queryKey: ['experiments', 'archive'],
    queryFn: async () => {
      const payload = await fetchApi<{ entries: ArchiveEntry[] }>('/experiments/archive');
      return payload.entries ?? [];
    },
    refetchInterval: 15000,
  });
}

// AutoFix

export function useAutoFixProposals(limit = 100) {
  return useQuery<AutoFixProposal[]>({
    queryKey: ['autofix', 'proposals', limit],
    queryFn: async () => {
      const payload = await fetchApi<{ proposals: AutoFixProposal[] }>(`/autofix/proposals?limit=${limit}`);
      return payload.proposals ?? [];
    },
    refetchInterval: 5000,
  });
}

export function useAutoFixHistory(limit = 100) {
  return useQuery<AutoFixHistoryEntry[]>({
    queryKey: ['autofix', 'history', limit],
    queryFn: async () => {
      const payload = await fetchApi<{ history: AutoFixHistoryEntry[] }>(`/autofix/history?limit=${limit}`);
      return payload.history ?? [];
    },
    refetchInterval: 5000,
  });
}

export function useSuggestAutoFix() {
  const queryClient = useQueryClient();

  return useMutation<{ proposals: AutoFixProposal[] }, ApiRequestError, { opportunities?: Record<string, unknown>[] } | void>({
    mutationFn: (params) =>
      fetchApi('/autofix/suggest', {
        method: 'POST',
        body: JSON.stringify(params || {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['autofix', 'proposals'] });
    },
  });
}

export function useApplyAutoFix() {
  const queryClient = useQueryClient();

  return useMutation<AutoFixApplyOutcome, ApiRequestError, { proposal_id: string; current_config?: Record<string, unknown> }>({
    mutationFn: ({ proposal_id, current_config }) =>
      fetchApi(`/autofix/apply/${proposal_id}`, {
        method: 'POST',
        body: JSON.stringify({ current_config: current_config || {} }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['autofix', 'proposals'] });
      queryClient.invalidateQueries({ queryKey: ['autofix', 'history'] });
    },
  });
}

// Judge Calibration

export function useJudgeCalibration() {
  return useQuery<JudgeCalibration>({
    queryKey: ['experiments', 'judge-calibration'],
    queryFn: () => fetchApi<JudgeCalibration>('/experiments/judge-calibration'),
    refetchInterval: 30000,
  });
}

// Judge Ops

export function useJudgeOpsJudges() {
  return useQuery<JudgeOpsJudgeSummary[]>({
    queryKey: ['judges', 'list'],
    queryFn: async () => {
      const payload = await fetchApi<{ judges: JudgeOpsJudgeSummary[] }>('/judges');
      return payload.judges ?? [];
    },
    refetchInterval: 10000,
  });
}

export function useJudgeOpsCalibration(sample = 50, judgeId?: string) {
  return useQuery<{ agreement_rate: number; disagreement_queue: JudgeFeedbackRecord[]; total_feedback: number }>({
    queryKey: ['judges', 'calibration', sample, judgeId ?? 'all'],
    queryFn: async () => {
      const qs = new URLSearchParams({ sample: String(sample) });
      if (judgeId) qs.set('judge_id', judgeId);
      const payload = await fetchApi<{
        agreement_rate: number;
        disagreement_queue: JudgeFeedbackRecord[];
        total_feedback: number;
      }>(`/judges/calibration?${qs.toString()}`);
      return {
        agreement_rate: payload.agreement_rate ?? 0,
        disagreement_queue: payload.disagreement_queue ?? [],
        total_feedback: payload.total_feedback ?? 0,
      };
    },
    refetchInterval: 10000,
  });
}

export function useJudgeOpsDrift() {
  return useQuery<JudgeDriftReport[]>({
    queryKey: ['judges', 'drift'],
    queryFn: async () => {
      const payload = await fetchApi<{ reports: JudgeDriftReport[] }>('/judges/drift');
      return payload.reports ?? [];
    },
    refetchInterval: 10000,
  });
}

export function useSubmitJudgeFeedback() {
  const queryClient = useQueryClient();

  return useMutation<
    { stored: boolean; feedback: JudgeFeedbackRecord },
    ApiRequestError,
    {
      case_id: string;
      judge_id: string;
      judge_score: number;
      human_score: number;
      comment?: string;
      rubric_dimension?: string;
      promote_to_regression?: boolean;
    }
  >({
    mutationFn: (payload) =>
      fetchApi('/judges/feedback', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['judges'] });
    },
  });
}

// Context Workbench

export function useContextAnalysis(traceId: string | undefined, tokenBudget = 8000) {
  return useQuery<ContextTraceAnalysis>({
    queryKey: ['context', 'analysis', traceId, tokenBudget],
    enabled: Boolean(traceId),
    queryFn: async () => {
      if (!traceId) throw new ApiRequestError('Missing trace ID', 400);
      const qs = new URLSearchParams({ token_budget: String(tokenBudget) });
      return fetchApi<ContextTraceAnalysis>(`/context/analysis/${encodeURIComponent(traceId)}?${qs.toString()}`);
    },
  });
}

export function useContextReport(limit = 1000, tokenBudget = 8000) {
  return useQuery<ContextHealthReport>({
    queryKey: ['context', 'report', limit, tokenBudget],
    queryFn: async () => {
      const qs = new URLSearchParams({
        limit: String(limit),
        token_budget: String(tokenBudget),
      });
      return fetchApi<ContextHealthReport>(`/context/report?${qs.toString()}`);
    },
    refetchInterval: 15000,
  });
}

export function useRunContextSimulation() {
  const queryClient = useQueryClient();

  return useMutation<
    ContextSimulationResult,
    ApiRequestError,
    {
      trace_id: string;
      strategy: 'truncate_tail' | 'sliding_window' | 'summarize';
      token_budget: number;
      ttl_seconds: number;
      pin_keywords: string[];
    }
  >({
    mutationFn: (payload) =>
      fetchApi('/context/simulate', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['context', 'report'] });
    },
  });
}

// ---------------------------------------------------------------------------
// Human Control (pause/resume/pin/unpin/reject)
// ---------------------------------------------------------------------------

interface ControlState {
  paused: boolean;
  immutable_surfaces: string[];
  rejected_experiments: string[];
  last_injected_mutation: string | null;
  updated_at: string | null;
}

export function useControlState() {
  return useQuery<ControlState>({
    queryKey: ['control', 'state'],
    queryFn: () => fetchApi<ControlState>('/control/state'),
    refetchInterval: 5000,
  });
}

export function usePauseControl() {
  const queryClient = useQueryClient();

  return useMutation<ControlState, ApiRequestError, void>({
    mutationFn: () =>
      fetchApi('/control/pause', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['control'] });
    },
  });
}

export function useResumeControl() {
  const queryClient = useQueryClient();

  return useMutation<ControlState, ApiRequestError, void>({
    mutationFn: () =>
      fetchApi('/control/resume', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['control'] });
    },
  });
}

export function usePinSurface() {
  const queryClient = useQueryClient();

  return useMutation<ControlState, ApiRequestError, { surface: string }>({
    mutationFn: ({ surface }) =>
      fetchApi(`/control/pin/${encodeURIComponent(surface)}`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['control'] });
    },
  });
}

export function useUnpinSurface() {
  const queryClient = useQueryClient();

  return useMutation<ControlState, ApiRequestError, { surface: string }>({
    mutationFn: ({ surface }) =>
      fetchApi(`/control/unpin/${encodeURIComponent(surface)}`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['control'] });
    },
  });
}

export function useRejectExperimentControl() {
  const queryClient = useQueryClient();

  return useMutation<ControlState & { rollback: string | null }, ApiRequestError, { experiment_id: string }>({
    mutationFn: ({ experiment_id }) =>
      fetchApi(`/control/reject/${encodeURIComponent(experiment_id)}`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['control'] });
      queryClient.invalidateQueries({ queryKey: ['experiments'] });
    },
  });
}

// ---------------------------------------------------------------------------
// Cost Health
// ---------------------------------------------------------------------------

interface CostHealthSummary {
  total_spend: number;
  total_improvement: number;
  cost_per_improvement: number;
  today_spend: number;
}

interface CostHealthResponse {
  summary: CostHealthSummary;
  budgets: {
    per_cycle_dollars: number;
    daily_dollars: number;
    stall_threshold_cycles: number;
  };
  recent_cycles: Array<{
    cycle_id: string;
    timestamp: number;
    spent_dollars: number;
    improvement_delta: number;
    cumulative_spend: number;
    running_cost_per_improvement: number;
  }>;
  stall_detected: boolean;
}

export function useCostHealth(limit = 30) {
  return useQuery<CostHealthResponse>({
    queryKey: ['health', 'cost', limit],
    queryFn: () => fetchApi<CostHealthResponse>(`/health/cost?limit=${limit}`),
    refetchInterval: 10000,
  });
}

// ---------------------------------------------------------------------------
// Eval Set Health
// ---------------------------------------------------------------------------

interface EvalSetHealthResponse {
  analysis: Record<string, number>;
  difficulty_distribution: Record<string, number>;
}

export function useEvalSetHealth() {
  return useQuery<EvalSetHealthResponse>({
    queryKey: ['health', 'eval-set'],
    queryFn: () => fetchApi<EvalSetHealthResponse>('/health/eval-set'),
    refetchInterval: 30000,
  });
}

// ---------------------------------------------------------------------------
// System Events (append-only event log)
// ---------------------------------------------------------------------------

interface SystemEvent {
  id: number;
  event_type: string;
  timestamp: number;
  cycle_id?: string;
  experiment_id?: string;
  payload: Record<string, unknown>;
}

export function useSystemEvents(params: { limit?: number; event_type?: string } = {}) {
  return useQuery<SystemEvent[]>({
    queryKey: ['events', params],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (params.limit !== undefined) qs.set('limit', String(params.limit));
      if (params.event_type) qs.set('event_type', params.event_type);
      const query = qs.toString() ? `?${qs.toString()}` : '';
      const payload = await fetchApi<{ events: SystemEvent[] }>(`/events${query}`);
      return payload.events ?? [];
    },
    refetchInterval: 5000,
  });
}

// ---------------------------------------------------------------------------
// Scorecard (2-gate + 4-metric)
// ---------------------------------------------------------------------------

interface ScorecardResponse {
  gates: {
    safety: { passed: boolean; safety_violation_rate: number };
    regression: { passed: boolean; latest_attempt_status: string };
  };
  metrics: {
    task_success_rate: number;
    response_quality: number;
    latency_p95_ms: number;
    cost_per_conversation: number;
  };
  diagnostics: {
    tool_correctness: number;
    routing_accuracy: number;
    handoff_fidelity: number;
    failure_buckets: Record<string, number>;
  };
}

export function useScorecard(window = 100) {
  return useQuery<ScorecardResponse>({
    queryKey: ['health', 'scorecard', window],
    queryFn: () => fetchApi<ScorecardResponse>(`/health/scorecard?window=${window}`),
    refetchInterval: 10000,
  });
}

// ---------------------------------------------------------------------------
// Change Review (Proposed Change Cards)
// ---------------------------------------------------------------------------

export function useChanges() {
  return useQuery<ChangeCard[]>({
    queryKey: ['changes'],
    queryFn: async () => {
      const payload = await fetchApi<{ changes: ChangeCard[] }>('/changes');
      return payload.changes ?? [];
    },
    refetchInterval: 5000,
  });
}

export function useChangeDetail(id: string | undefined) {
  return useQuery<ChangeCard>({
    queryKey: ['changes', 'detail', id],
    enabled: Boolean(id),
    queryFn: async () => {
      if (!id) throw new ApiRequestError('Missing change ID', 400);
      return fetchApi<ChangeCard>(`/changes/${encodeURIComponent(id)}`);
    },
  });
}

export function useApplyChange() {
  const queryClient = useQueryClient();

  return useMutation<{ status: string; message: string }, ApiRequestError, { id: string }>({
    mutationFn: ({ id }) =>
      fetchApi(`/changes/${encodeURIComponent(id)}/apply`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changes'] });
    },
  });
}

export function useRejectChange() {
  const queryClient = useQueryClient();

  return useMutation<{ status: string; message: string }, ApiRequestError, { id: string; reason: string }>({
    mutationFn: ({ id, reason }) =>
      fetchApi(`/changes/${encodeURIComponent(id)}/reject`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changes'] });
    },
  });
}

export function useUpdateHunkStatus() {
  const queryClient = useQueryClient();
  return useMutation<unknown, ApiRequestError, { cardId: string; hunkId: string; status: string }>({
    mutationFn: ({ cardId, hunkId, status }) =>
      fetchApi(`/changes/${encodeURIComponent(cardId)}/hunks`, {
        method: 'PATCH',
        body: JSON.stringify({ hunk_id: hunkId, status }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changes'] });
    },
  });
}

export function useExportChange(id: string | undefined) {
  return useQuery<{ markdown: string }>({
    queryKey: ['changes', 'export', id],
    enabled: false, // only fetch on demand
    queryFn: async () => {
      if (!id) throw new ApiRequestError('Missing change ID', 400);
      return fetchApi<{ markdown: string }>(`/changes/${encodeURIComponent(id)}/export`);
    },
  });
}

// ---------------------------------------------------------------------------
// Runbooks
// ---------------------------------------------------------------------------

export function useRunbooks() {
  return useQuery<Runbook[]>({
    queryKey: ['runbooks'],
    queryFn: async () => {
      const payload = await fetchApi<{ runbooks: Runbook[] }>('/runbooks');
      return payload.runbooks ?? [];
    },
    refetchInterval: 10000,
  });
}

export function useRunbookDetail(name: string | undefined) {
  return useQuery<Runbook>({
    queryKey: ['runbooks', 'detail', name],
    enabled: Boolean(name),
    queryFn: async () => {
      if (!name) throw new ApiRequestError('Missing runbook name', 400);
      return fetchApi<Runbook>(`/runbooks/${encodeURIComponent(name)}`);
    },
  });
}

export function useApplyRunbook() {
  const queryClient = useQueryClient();

  return useMutation<{ status: string; message: string }, ApiRequestError, { name: string }>({
    mutationFn: ({ name }) =>
      fetchApi(`/runbooks/${encodeURIComponent(name)}/apply`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runbooks'] });
    },
  });
}

// ---------------------------------------------------------------------------
// Project Memory (AUTOAGENT.md)
// ---------------------------------------------------------------------------

export function useProjectMemory() {
  return useQuery<ProjectMemory>({
    queryKey: ['memory'],
    queryFn: () => fetchApi<ProjectMemory>('/memory'),
  });
}

export function useUpdateMemory() {
  const queryClient = useQueryClient();

  return useMutation<ProjectMemory, ApiRequestError, ProjectMemory>({
    mutationFn: (data) =>
      fetchApi('/memory', {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memory'] });
    },
  });
}

export function useAddMemoryNote() {
  const queryClient = useQueryClient();

  return useMutation<{ status: string }, ApiRequestError, { section: string; note: string }>({
    mutationFn: ({ section, note }) =>
      fetchApi('/memory/note', {
        method: 'POST',
        body: JSON.stringify({ section, note }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memory'] });
    },
  });
}

// ---------------------------------------------------------------------------
// CX Agent Studio
// ---------------------------------------------------------------------------

export function useCxAgents(project: string, location: string) {
  return useQuery<CxAgentSummary[]>({
    queryKey: ['cx-agents', project, location],
    queryFn: () => fetchApi(`/cx/agents?project=${encodeURIComponent(project)}&location=${encodeURIComponent(location)}`),
    enabled: !!project,
  });
}

export function useCxImport() {
  const qc = useQueryClient();
  return useMutation<CxImportResult, ApiRequestError, {
    project: string;
    location: string;
    agent_id: string;
    output_dir?: string;
    include_test_cases?: boolean;
  }>({
    mutationFn: (body) => fetchApi('/cx/import', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['configs'] }),
  });
}

export function useCxExport() {
  return useMutation<CxExportResult, ApiRequestError, {
    project: string;
    location: string;
    agent_id: string;
    config: Record<string, unknown>;
    snapshot_path: string;
    dry_run?: boolean;
  }>({
    mutationFn: (body) => fetchApi('/cx/export', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxDeploy() {
  return useMutation<CxDeployResult, ApiRequestError, {
    project: string;
    location: string;
    agent_id: string;
    environment?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/deploy', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxWidget() {
  return useMutation<CxWidgetResult, ApiRequestError, {
    project_id: string;
    agent_id: string;
    location?: string;
    chat_title?: string;
    primary_color?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/widget', { method: 'POST', body: JSON.stringify(body) }),
  });
}
