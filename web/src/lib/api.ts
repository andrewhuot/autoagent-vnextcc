import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  AdkAgent,
  AdkDeployResult,
  AdkExportResult,
  AdkImportResult,
  AutonomousLoopResult,
  ApplyInsightResult,
  AgentLibraryDetail,
  AgentLibraryItem,
  ArchiveEntry,
  AutoFixApplyOutcome,
  AutoFixHistoryEntry,
  AutoFixProposal,
  ChangeAuditDetail,
  ChangeAuditSummary,
  CanaryStatus,
  ChangeCard,
  ContextHealthReport,
  ContextSimulationResult,
  ContextTraceAnalysis,
  BuildArtifact,
  BuildArtifactSource,
  BuildArtifactStatus,
  BuildPreviewResult,
  BuildSaveResult,
  ConfigDiff,
  ConfigActivateResult,
  ConfigEditResult,
  ConfigImportResult,
  ConfigMigrateResult,
  ConfigShow,
  ConfigVersion,
  ConnectImportRequest,
  ConnectImportResult,
  ContinuityState,
  ConversationRecord,
  ConversationTurn,
  CxAuthResult,
  CxAgentSummary,
  CxCanaryState,
  CxImportResult,
  CxExportResult,
  CxDeployResult,
  CxDeployStatusResult,
  CxPreflightResult,
  CxWidgetResult,
  CurriculumBatchSummary,
  CurriculumDifficultyPoint,
  ExecutableSkill,
  DeployHistoryEntry,
  DeployResponse,
  DeployStatus,
  DiagnoseChatResponse,
  DiffLine,
  DeepResearchReport,
  EvalMode,
  EvalResult,
  EvalResultsDiff,
  EvalResultsRun,
  EvalResultsRunList,
  EvalRun,
  ExperimentCard,
  HealthReport,
  IntelligenceAnswer,
  JudgeCalibration,
  JudgeDriftReport,
  JudgeFeedbackRecord,
  JudgeOpsJudgeSummary,
  LoopStatus,
  KnowledgeAsset,
  NotificationHistoryEntry,
  NotificationSubscription,
  OptimizationAttempt,
  OptimizationOpportunity,
  OptimizeResult,
  PendingReview,
  PendingReviewActionResult,
  PairwiseComparison,
  PairwiseComparisonList,
  ParetoFrontier,
  ProjectMemory,
  PromptBuildArtifact,
  GeneratedAgentConfig,
  ChatRefineResponse,
  Runbook,
  SaveProviderKeysResponse,
  SaveAgentResult,
  GeneratedEvalSuiteSummary,
  SetupOverview,
  SkillLeaderboardEntry,
  SkillMarketplaceListing,
  SkillCompositionResult,
  DraftSkillReview,
  TaskStatus,
  Trace,
  TraceGraphData,
  TraceGrade,
  TraceEvent,
  PromoteTraceResult,
  TranscriptReport,
  TranscriptReportSummary,
  TestProviderKeyResponse,
  UnifiedReviewActionResult,
  UnifiedReviewItem,
  UnifiedReviewStats,
  UnifiedSkill,
} from './types';
import type { ArtifactRef, ArtifactType } from './builder-types';

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

/**
 * Convert a raw HTTP status code into a short, human-friendly description.
 * Used as a last-resort fallback so users never see "Request failed: 502".
 */
export function humanizeHttpStatus(status: number): string {
  if (status === 401 || status === 403) return 'Authentication required — check your API keys in Setup.';
  if (status === 404) return 'The requested resource was not found.';
  if (status === 408) return 'The request timed out. Try again in a moment.';
  if (status === 429) return 'Rate limited — wait a moment, then try again.';
  if (status >= 500 && status < 600) return 'The server is temporarily unavailable. Retrying usually resolves this.';
  return 'Something went wrong with the request. Try again or check Setup.';
}

/**
 * Extract a user-friendly error message from an API error response.
 * Avoids leaking raw JSON payloads or cryptic status codes to the UI.
 */
function extractErrorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const p = payload as Record<string, unknown>;
    if (typeof p.detail === 'string' && p.detail.trim()) return p.detail;
    if (typeof p.message === 'string' && p.message.trim()) return p.message;
  }
  return humanizeHttpStatus(status);
}

async function fetchApi<T>(path: string, options?: RequestOptions): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let errorMessage = humanizeHttpStatus(response.status);
    try {
      const payload = await response.json();
      errorMessage = extractErrorMessage(payload, response.status);
    } catch {
      const text = await response.text().catch(() => '');
      if (text && text.trim()) {
        errorMessage = text;
      }
    }
    throw new ApiRequestError(errorMessage, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

async function fetchApiText(path: string, options?: RequestOptions): Promise<string> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let errorMessage = humanizeHttpStatus(response.status);
    try {
      const payload = await response.json();
      errorMessage = extractErrorMessage(payload, response.status);
    } catch {
      const text = await response.text().catch(() => '');
      if (text && text.trim()) {
        errorMessage = text;
      }
    }
    throw new ApiRequestError(errorMessage, response.status);
  }

  return response.text();
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is string => typeof item === 'string' && item.length > 0);
}

function numberRecord(value: unknown): Record<string, number> {
  if (!isRecord(value)) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, numberValue(item)])
  );
}

function emitSettingsUpdated(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(new Event('agentlab:settings-updated'));
}

function normalizeContextHealthReport(payload: unknown): ContextHealthReport {
  const data = isRecord(payload) ? payload : {};

  return {
    traces_analyzed: numberValue(data.traces_analyzed),
    total_events: numberValue(data.total_events),
    average_utilization: numberValue(data.average_utilization, numberValue(data.utilization_ratio)),
    growth_pattern_counts: numberRecord(data.growth_pattern_counts),
    context_correlated_failure_traces: stringList(data.context_correlated_failure_traces),
    average_handoff_fidelity: numberValue(
      data.average_handoff_fidelity,
      numberValue(data.avg_handoff_fidelity)
    ),
    average_memory_staleness: numberValue(
      data.average_memory_staleness,
      numberValue(data.memory_staleness)
    ),
  };
}

function normalizeContextSimulationResult(
  payload: unknown,
  request: {
    trace_id: string;
    strategy: 'truncate_tail' | 'sliding_window' | 'summarize';
    token_budget: number;
    ttl_seconds: number;
    pin_keywords: string[];
  }
): ContextSimulationResult {
  const data = isRecord(payload) ? payload : {};
  const rawResults = Array.isArray(data.results) ? data.results : [];
  const strategyBudgets: Record<string, number> = {
    aggressive: 8000,
    balanced: 16000,
    conservative: 32000,
  };

  const primaryResult = rawResults.find((item) => isRecord(item)) ?? {};
  const primary = isRecord(primaryResult) ? primaryResult : {};
  const primaryAvgUtilization = numberValue(primary.avg_utilization);
  const peakTokens = numberValue(primary.peak_tokens, request.token_budget);
  const totalTokensLost = numberValue(primary.total_tokens_lost);

  const budgetComparison = rawResults
    .filter(isRecord)
    .map((item) => {
      const strategyName = typeof item.strategy_name === 'string' ? item.strategy_name : '';
      return {
        budget: strategyBudgets[strategyName] ?? request.token_budget,
        average_utilization: numberValue(item.avg_utilization),
        estimated_failure_rate: 0,
      };
    });

  return {
    trace_id: request.trace_id,
    strategy: request.strategy,
    token_budget: request.token_budget,
    baseline_average_utilization: primaryAvgUtilization,
    simulated_average_utilization: primaryAvgUtilization,
    estimated_failure_delta: 0,
    estimated_compaction_loss: peakTokens > 0 ? totalTokensLost / peakTokens : 0,
    memory_staleness: 0,
    ttl_seconds: request.ttl_seconds,
    pinned_memory_hits: request.pin_keywords.length,
    budget_comparison: budgetComparison.length > 0
      ? budgetComparison
      : [
          {
            budget: request.token_budget,
            average_utilization: primaryAvgUtilization,
            estimated_failure_rate: 0,
          },
        ],
    notes: [],
  };
}

function normalizeChangeAuditDetail(payload: unknown, id: string): ChangeAuditDetail {
  const data = isRecord(payload) ? payload : {};
  const dimensionBreakdown = isRecord(data.dimension_breakdown) ? data.dimension_breakdown : {};
  const gateResults = Array.isArray(data.gate_results) ? data.gate_results : [];
  const adversarialResults = isRecord(data.adversarial_results) ? data.adversarial_results : {};
  const compositeBreakdown = isRecord(data.composite_breakdown) ? data.composite_breakdown : {};
  const compositeSource = isRecord(compositeBreakdown.contributions)
    ? compositeBreakdown.contributions
    : compositeBreakdown;
  const timeline = Array.isArray(data.timeline) ? data.timeline : [];

  return {
    change_id: typeof data.card_id === 'string' ? data.card_id : id,
    status: typeof data.status === 'string' ? data.status : 'pending',
    score_deltas: Object.fromEntries(
      Object.entries(dimensionBreakdown).map(([key, value]) => {
        const row = isRecord(value) ? value : {};
        return [key, numberValue(row.delta)];
      })
    ),
    gate_decisions: gateResults
      .filter(isRecord)
      .map((gate) => ({
        gate: typeof gate.gate === 'string' ? gate.gate : 'unknown',
        passed: Boolean(gate.passed),
        reason: typeof gate.reason === 'string' ? gate.reason : '',
      })),
    adversarial_results: {
      executed: numberValue(
        adversarialResults.executed,
        numberValue(adversarialResults.num_cases)
      ),
      failures: numberValue(
        adversarialResults.failures,
        adversarialResults.passed === false ? 1 : 0
      ),
    },
    composite_breakdown: numberRecord(compositeSource),
    timeline: timeline
      .filter(isRecord)
      .map((item, index) => ({
        stage: typeof item.stage === 'string'
          ? item.stage
          : typeof item.phase === 'string'
            ? item.phase
            : `step_${index + 1}`,
        timestamp: numberValue(item.timestamp),
        detail: typeof item.detail === 'string'
          ? item.detail
          : typeof item.status === 'string'
            ? item.status
            : '',
      })),
    failure_reason: typeof data.rejection_reason === 'string' ? data.rejection_reason : '',
  };
}

function normalizeChangeAuditSummary(payload: unknown): ChangeAuditSummary {
  const data = isRecord(payload) ? payload : {};
  const topRejectionReasons = Array.isArray(data.top_rejection_reasons)
    ? data.top_rejection_reasons
    : [];
  const improvementTrend = Array.isArray(data.improvement_trend) ? data.improvement_trend : [];

  return {
    total_changes: numberValue(data.total_changes),
    accepted_changes: numberValue(data.accepted_changes, numberValue(data.accepted)),
    rejected_changes: numberValue(data.rejected_changes, numberValue(data.rejected)),
    accept_rate: numberValue(data.accept_rate),
    top_rejection_reasons: topRejectionReasons
      .filter(isRecord)
      .map((entry) => ({
        reason: typeof entry.reason === 'string' ? entry.reason : 'unknown',
        count: numberValue(entry.count),
      })),
    improvement_trend: improvementTrend
      .filter(isRecord)
      .map((entry) => ({
        change_id: typeof entry.change_id === 'string' ? entry.change_id : '',
        created_at: numberValue(entry.created_at),
        composite_delta: numberValue(entry.composite_delta),
      })),
    change_ids: stringList(data.change_ids),
  };
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

interface RawChangeCard {
  card_id: string;
  title: string;
  why: string;
  status: 'pending' | 'applied' | 'rejected';
  diff_hunks: Array<{
    hunk_id: string;
    surface: string;
    old_value: string;
    new_value: string;
    status: 'pending' | 'accepted' | 'rejected';
  }>;
  metrics_before: Record<string, number>;
  metrics_after: Record<string, number>;
  confidence?: {
    p_value?: number;
    effect_size?: number;
    judge_agreement?: number;
  };
  risk_class?: 'low' | 'medium' | 'high';
  rollout_plan?: string;
  created_at?: number;
}

function buildHunkContent(oldValue: string, newValue: string): string {
  const lines: string[] = ['@@'];
  if (oldValue) {
    lines.push(...oldValue.split('\n').map((line) => `- ${line}`));
  }
  if (newValue) {
    lines.push(...newValue.split('\n').map((line) => `+ ${line}`));
  }
  return lines.join('\n');
}

function mapChangeCard(raw: RawChangeCard): ChangeCard {
  const pValue = raw.confidence?.p_value ?? 1;
  const effectSize = raw.confidence?.effect_size ?? 0;
  const judgeAgreement = raw.confidence?.judge_agreement ?? 0;
  const confidenceScore = Math.max(0, Math.min(1, 1 - pValue));

  return {
    id: raw.card_id,
    title: raw.title,
    why: raw.why,
    status: raw.status,
    diff_hunks: raw.diff_hunks.map((hunk, index) => ({
      hunk_id: hunk.hunk_id,
      file_path: hunk.surface || `config.surface.${index + 1}`,
      old_start: index + 1,
      old_count: hunk.old_value ? Math.max(hunk.old_value.split('\n').length, 1) : 0,
      new_start: index + 1,
      new_count: hunk.new_value ? Math.max(hunk.new_value.split('\n').length, 1) : 0,
      content: buildHunkContent(hunk.old_value, hunk.new_value),
      status: hunk.status,
    })),
    metrics_before: raw.metrics_before ?? {},
    metrics_after: raw.metrics_after ?? {},
    confidence: {
      score: confidenceScore,
      explanation: raw.why,
      evidence: [
        `p-value ${pValue.toFixed(4)}`,
        `effect size ${effectSize.toFixed(4)}`,
        judgeAgreement > 0 ? `judge agreement ${(judgeAgreement * 100).toFixed(0)}%` : 'judge agreement unavailable',
      ],
    },
    risk: raw.risk_class ?? 'low',
    rollout_plan: raw.rollout_plan ?? '',
    created_at: fromEpoch(raw.created_at),
    updated_at: fromEpoch(raw.created_at),
  };
}

interface EvalResultRaw {
  run_id: string;
  mode?: string | null;
  quality: number;
  safety: number;
  latency: number;
  cost: number;
  composite: number;
  safety_failures: number;
  total_cases: number;
  passed_cases: number;
  warnings?: string[];
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
  status: 'pending' | 'running' | 'completed' | 'failed' | 'interrupted';
  progress: number;
  result: unknown;
  error: string | null;
  created_at: string;
  updated_at: string;
  continuity?: ContinuityState;
  continuity_state?: string;
  state_label?: string;
  state_detail?: string;
}

function normalizeEvalMode(value: unknown, warnings: unknown = []): EvalMode | undefined {
  if (value === 'mock' || value === 'live' || value === 'mixed') {
    return value;
  }

  const warningText = Array.isArray(warnings)
    ? warnings.filter((item): item is string => typeof item === 'string').join(' ').toLowerCase()
    : '';
  if (warningText.includes('falling back') || warningText.includes('fallback to mock')) {
    return 'mixed';
  }
  if (warningText.includes('mock mode') || warningText.includes('simulated') || warningText.includes('mock_agent_response')) {
    return 'mock';
  }
  return undefined;
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
    continuity: task.continuity,
    continuity_state: task.continuity_state,
    state_label: task.state_label,
    state_detail: task.state_detail,
  };
}

function mapEvalTask(task: TaskStatusRaw): EvalRun {
  const result = (task.result || {}) as Partial<EvalResultRaw>;
  return {
    run_id: task.task_id,
    timestamp: task.created_at,
    status: task.status,
    progress: task.progress,
    mode: normalizeEvalMode(result.mode, result.warnings),
    composite_score: percent(result.composite),
    total_cases: result.total_cases || 0,
    passed_cases: result.passed_cases || 0,
    error: task.error,
    continuity: task.continuity,
  };
}

function mapEvalResult(raw: EvalResultRaw, status: TaskStatusRaw['status'] = 'completed', progress = 100): EvalResult {
  return {
    run_id: raw.run_id,
    status,
    progress,
    timestamp: raw.completed_at || new Date().toISOString(),
    mode: normalizeEvalMode(raw.mode, raw.warnings),
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

  return useMutation<
    { task_id: string; message: string },
    ApiRequestError,
    {
      config_path?: string;
      category?: string;
      require_live?: boolean;
      generated_suite_id?: string;
      dataset_path?: string;
      split?: 'train' | 'test' | 'all';
    }
  >({
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

// Auto-eval generation
export function useGenerateEvals() {
  const queryClient = useQueryClient();

  return useMutation<
    { suite_id: string; status: string; total_cases: number; message: string },
    ApiRequestError,
    { agent_config: Record<string, unknown>; agent_name?: string }
  >({
    mutationFn: (params) =>
      fetchApi('/eval/generate', {
        method: 'POST',
        body: JSON.stringify(params),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['generatedSuite'] });
      queryClient.invalidateQueries({ queryKey: ['generatedSuites'] });
    },
  });
}

export function useGeneratedSuites(limit = 20) {
  return useQuery<GeneratedEvalSuiteSummary[]>({
    queryKey: ['generatedSuites', limit],
    queryFn: async () => {
      const payload = await fetchApi<{ suites: GeneratedEvalSuiteSummary[]; count: number }>(
        `/evals/generated?limit=${limit}`,
      );
      return payload.suites;
    },
  });
}

export function useGeneratedSuite(suiteId: string | undefined) {
  return useQuery<import('./types').GeneratedEvalSuite>({
    queryKey: ['generatedSuite', suiteId],
    enabled: Boolean(suiteId),
    queryFn: () => fetchApi(`/eval/generated/${suiteId}`),
  });
}

export function useAcceptSuite() {
  const queryClient = useQueryClient();

  return useMutation<
    { suite_id: string; status: string; total_cases: number; message: string },
    ApiRequestError,
    string
  >({
    mutationFn: (suiteId) =>
      fetchApi(`/eval/generated/${suiteId}/accept`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['generatedSuite'] });
      queryClient.invalidateQueries({ queryKey: ['generatedSuites'] });
    },
  });
}

export function useUpdateGeneratedCase() {
  const queryClient = useQueryClient();

  return useMutation<
    import('./types').GeneratedEvalCase,
    ApiRequestError,
    { suiteId: string; caseId: string; updates: Record<string, unknown> }
  >({
    mutationFn: ({ suiteId, caseId, updates }) =>
      fetchApi(`/eval/generated/${suiteId}/cases/${caseId}`, {
        method: 'PATCH',
        body: JSON.stringify(updates),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['generatedSuite'] });
      queryClient.invalidateQueries({ queryKey: ['generatedSuites'] });
    },
  });
}

export function useDeleteGeneratedCase() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiRequestError, { suiteId: string; caseId: string }>({
    mutationFn: ({ suiteId, caseId }) =>
      fetchApi(`/eval/generated/${suiteId}/cases/${caseId}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['generatedSuite'] });
      queryClient.invalidateQueries({ queryKey: ['generatedSuites'] });
    },
  });
}

export function usePairwiseComparisons(limit = 20) {
  return useQuery<PairwiseComparisonList>({
    queryKey: ['pairwiseComparisons', limit],
    queryFn: () => fetchApi(`/evals/compare?limit=${limit}`),
    refetchInterval: 5000,
  });
}

export function usePairwiseComparison(comparisonId: string | undefined) {
  return useQuery<PairwiseComparison>({
    queryKey: ['pairwiseComparison', comparisonId],
    enabled: Boolean(comparisonId),
    queryFn: () => {
      if (!comparisonId) {
        throw new ApiRequestError('Missing comparison ID', 400);
      }
      return fetchApi(`/evals/compare/${comparisonId}`);
    },
  });
}

export function useStartPairwiseComparison() {
  const queryClient = useQueryClient();

  return useMutation<
    { comparison_id: string; message: string; summary: PairwiseComparisonList['comparisons'][number] },
    ApiRequestError,
    {
      config_a_path?: string;
      config_b_path?: string;
      dataset_path?: string;
      split?: 'train' | 'test' | 'all';
      label_a?: string;
      label_b?: string;
      judge_strategy?: 'metric_delta' | 'llm_judge' | 'human_preference';
    }
  >({
    mutationFn: (body) =>
      fetchApi('/evals/compare', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: (payload) => {
      queryClient.invalidateQueries({ queryKey: ['pairwiseComparisons'] });
      queryClient.invalidateQueries({ queryKey: ['pairwiseComparison', payload.comparison_id] });
    },
  });
}

export function useResultRuns(limit = 20) {
  return useQuery<EvalResultsRunList>({
    queryKey: ['resultRuns', limit],
    queryFn: () => fetchApi(`/evals/results?limit=${limit}`),
    refetchInterval: 5000,
  });
}

export function useResultsRun(runId: string | undefined) {
  return useQuery<EvalResultsRun>({
    queryKey: ['resultsRun', runId],
    enabled: Boolean(runId),
    queryFn: () => {
      if (!runId) {
        throw new ApiRequestError('Missing run ID', 400);
      }
      return fetchApi(`/evals/results/${runId}`);
    },
  });
}

export function useResultsDiff(
  baselineRunId: string | undefined,
  candidateRunId: string | undefined
) {
  return useQuery<EvalResultsDiff>({
    queryKey: ['resultsDiff', baselineRunId, candidateRunId],
    enabled: Boolean(baselineRunId && candidateRunId),
    queryFn: () => {
      if (!baselineRunId || !candidateRunId) {
        throw new ApiRequestError('Both run IDs are required for a diff', 400);
      }
      return fetchApi(
        `/evals/results/${baselineRunId}/diff?candidate_run_id=${encodeURIComponent(candidateRunId)}`
      );
    },
  });
}

export function useAddResultAnnotation() {
  const queryClient = useQueryClient();

  return useMutation<
    EvalResultsRun['examples'][number],
    ApiRequestError,
    {
      runId: string;
      exampleId: string;
      author: string;
      type: string;
      content: string;
      score_override: number | null;
    }
  >({
    mutationFn: ({ runId, exampleId, ...body }) =>
      fetchApi(`/evals/results/${runId}/examples/${exampleId}/annotate`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: (_payload, variables) => {
      queryClient.invalidateQueries({ queryKey: ['resultsRun', variables.runId] });
      queryClient.invalidateQueries({ queryKey: ['resultRuns'] });
    },
  });
}

export function useExportEvalResults() {
  return useMutation<
    string,
    ApiRequestError,
    { runId: string; format: 'json' | 'csv' | 'markdown' }
  >({
    mutationFn: ({ runId, format }) =>
      fetchApiText(`/evals/results/${runId}/export?format=${encodeURIComponent(format)}`),
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
          timestamp: number | string;
          change_description: string;
          config_diff: string;
          config_section: string;
          status: OptimizationAttempt['status'];
          score_before: number;
          score_after: number;
          significance_p_value?: number;
          significance_delta?: number;
          significance_n?: number;
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
        significance_p_value: row.significance_p_value ?? 1,
        significance_delta: percent(row.significance_delta ?? row.score_after - row.score_before),
        significance_n: row.significance_n ?? 0,
        health_context: row.health_context,
      }));
    },
  });
}

export function usePendingReviews(poll = false) {
  return useQuery<PendingReview[]>({
    queryKey: ['optimizePendingReviews'],
    queryFn: async () => {
      const rows = await fetchApi<
        Array<{
          attempt_id: string;
          proposed_config: Record<string, unknown>;
          current_config: Record<string, unknown>;
          config_diff: string;
          score_before: number;
          score_after: number;
          change_description: string;
          reasoning: string;
          created_at: string;
          strategy: string;
          selected_operator_family?: string | null;
          governance_notes?: string[];
          deploy_scores?: Record<string, unknown>;
          deploy_strategy: string;
        }>
      >('/optimize/pending');

      return rows.map((row) => ({
        attempt_id: row.attempt_id,
        proposed_config: row.proposed_config ?? {},
        current_config: row.current_config ?? {},
        config_diff: row.config_diff ?? '',
        score_before: percent(row.score_before),
        score_after: percent(row.score_after),
        change_description: row.change_description ?? '',
        reasoning: row.reasoning ?? '',
        created_at: fromEpoch(row.created_at),
        strategy: row.strategy ?? 'simple',
        selected_operator_family: row.selected_operator_family ?? null,
        governance_notes: Array.isArray(row.governance_notes)
          ? row.governance_notes.filter((note): note is string => typeof note === 'string')
          : [],
        deploy_scores: row.deploy_scores ?? {},
        deploy_strategy: row.deploy_strategy ?? 'immediate',
      }));
    },
    refetchInterval: poll ? 10000 : false,
  });
}

export function useApproveReview() {
  const queryClient = useQueryClient();

  return useMutation<
    PendingReviewActionResult,
    ApiRequestError,
    { attemptId: string }
  >({
    mutationFn: ({ attemptId }) =>
      fetchApi(`/optimize/pending/${encodeURIComponent(attemptId)}/approve`, {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['optimizePendingReviews'] });
      queryClient.invalidateQueries({ queryKey: ['optimizeHistory'] });
    },
  });
}

export function useRejectReview() {
  const queryClient = useQueryClient();

  return useMutation<
    PendingReviewActionResult,
    ApiRequestError,
    { attemptId: string }
  >({
    mutationFn: ({ attemptId }) =>
      fetchApi(`/optimize/pending/${encodeURIComponent(attemptId)}/reject`, {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['optimizePendingReviews'] });
      queryClient.invalidateQueries({ queryKey: ['optimizeHistory'] });
    },
  });
}

export function useStartOptimize() {
  const queryClient = useQueryClient();

  return useMutation<
    OptimizeResult,
    ApiRequestError,
    {
      window: number;
      force: boolean;
      require_human_approval: boolean;
      config_path?: string;
      eval_run_id?: string;
      require_eval_evidence?: boolean;
      mode: 'standard' | 'advanced' | 'research';
      objective: string;
      guardrails: string[];
      research_algorithm: string;
      budget_cycles: number;
      budget_dollars: number;
    }
  >({
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

export function useAgents() {
  return useQuery<AgentLibraryItem[]>({
    queryKey: ['agents'],
    queryFn: async () => {
      const payload = await fetchApi<{ agents: AgentLibraryItem[] }>('/agents');
      return (payload.agents ?? []).slice().sort((a, b) => b.created_at.localeCompare(a.created_at));
    },
  });
}

export function useAgent(agentId: string | null | undefined) {
  return useQuery<AgentLibraryDetail>({
    queryKey: ['agents', agentId],
    enabled: Boolean(agentId),
    queryFn: () => fetchApi<AgentLibraryDetail>(`/agents/${encodeURIComponent(agentId || '')}`),
  });
}

export function useSaveAgent() {
  const queryClient = useQueryClient();

  return useMutation<
    SaveAgentResult,
    ApiRequestError,
    {
      source: 'built' | 'imported' | 'connected';
      build_source?: 'prompt' | 'transcript' | 'builder_chat';
      name?: string;
      config?: object;
      session_id?: string;
      config_path?: string;
      prompt_used?: string;
      transcript_report_id?: string;
      builder_session_id?: string;
    }
  >({
    mutationFn: (params) =>
      fetchApi('/agents', {
        method: 'POST',
        body: JSON.stringify(params),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
      queryClient.invalidateQueries({ queryKey: ['configs'] });
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

export function useSetupOverview() {
  return useQuery<SetupOverview>({
    queryKey: ['setupOverview'],
    queryFn: () => fetchApi('/setup/overview'),
    refetchInterval: 15000,
  });
}

export function useSaveProviderKeys() {
  const queryClient = useQueryClient();

  return useMutation<
    SaveProviderKeysResponse,
    ApiRequestError,
    {
      openai_api_key?: string;
      anthropic_api_key?: string;
      google_api_key?: string;
    }
  >({
    mutationFn: (payload) =>
      fetchApi('/settings/keys', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['setupOverview'] });
      emitSettingsUpdated();
    },
  });
}

export function useTestProviderKey() {
  return useMutation<
    TestProviderKeyResponse,
    ApiRequestError,
    {
      provider: 'openai' | 'anthropic' | 'google';
      api_key?: string;
      model?: string;
    }
  >({
    mutationFn: (payload) =>
      fetchApi('/settings/test-key', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
  });
}

export function useSetRuntimeMode() {
  const queryClient = useQueryClient();

  return useMutation<
    {
      preferred_mode: string;
      effective_mode: string;
      mode_source: string;
      message: string;
      real_provider_configured: boolean;
    },
    ApiRequestError,
    { mode: 'mock' | 'auto' | 'live' }
  >({
    mutationFn: (payload) =>
      fetchApi('/settings/mode', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['setupOverview'] });
      emitSettingsUpdated();
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

export function useNaturalLanguageConfigEdit() {
  const queryClient = useQueryClient();

  return useMutation<
    ConfigEditResult,
    ApiRequestError,
    { description: string; dry_run: boolean }
  >({
    mutationFn: (body) =>
      fetchApi('/edit', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: (result, body) => {
      if (body.dry_run || !result.applied) {
        return;
      }

      queryClient.invalidateQueries({ queryKey: ['configs'] });
      queryClient.invalidateQueries({ queryKey: ['configShow'] });
      queryClient.invalidateQueries({ queryKey: ['configDiff'] });
      queryClient.invalidateQueries({ queryKey: ['deployStatus'] });
      queryClient.invalidateQueries({ queryKey: ['optimizeHistory'] });
    },
  });
}

export function useActivateConfig() {
  const queryClient = useQueryClient();

  return useMutation<ConfigActivateResult, ApiRequestError, { version: number }>({
    mutationFn: ({ version }) =>
      fetchApi('/config/activate', {
        method: 'POST',
        body: JSON.stringify({ version }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['configs'] });
      queryClient.invalidateQueries({ queryKey: ['configShow'] });
      queryClient.invalidateQueries({ queryKey: ['setupOverview'] });
    },
  });
}

export function useImportConfig() {
  const queryClient = useQueryClient();

  return useMutation<ConfigImportResult, ApiRequestError, { file_path: string }>({
    mutationFn: ({ file_path }) =>
      fetchApi('/config/import', {
        method: 'POST',
        body: JSON.stringify({ file_path }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['configs'] });
      queryClient.invalidateQueries({ queryKey: ['setupOverview'] });
    },
  });
}

export function useMigrateConfig() {
  return useMutation<
    ConfigMigrateResult,
    ApiRequestError,
    { input_file: string; output_file?: string }
  >({
    mutationFn: ({ input_file, output_file }) =>
      fetchApi('/config/migrate', {
        method: 'POST',
        body: JSON.stringify({ input_file, output_file }),
      }),
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
      return fetchApi('/deploy', {
        method: 'POST',
        body: JSON.stringify({ version, strategy }),
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

export function usePromoteCanary() {
  const queryClient = useQueryClient();

  return useMutation<DeployResponse, ApiRequestError, { version?: number } | void>({
    mutationFn: (params) =>
      fetchApi('/deploy/promote', {
        method: 'POST',
        body: JSON.stringify(params ?? {}),
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

export function useTraceGrades(traceId: string | undefined) {
  return useQuery<TraceGrade[]>({
    queryKey: ['traces', 'grades', traceId],
    enabled: Boolean(traceId),
    queryFn: async () => {
      if (!traceId) throw new ApiRequestError('Missing trace ID', 400);
      const payload = await fetchApi<{ trace_id: string; grades: TraceGrade[] }>(`/traces/${traceId}/grades`);
      return payload.grades ?? [];
    },
  });
}

export function useTraceGraph(traceId: string | undefined) {
  return useQuery<TraceGraphData>({
    queryKey: ['traces', 'graph', traceId],
    enabled: Boolean(traceId),
    queryFn: async () => {
      if (!traceId) throw new ApiRequestError('Missing trace ID', 400);
      return fetchApi<TraceGraphData>(`/traces/${traceId}/graph`);
    },
  });
}

export function usePromoteTrace() {
  return useMutation<PromoteTraceResult, ApiRequestError, { traceId: string; eval_cases_dir?: string }>({
    mutationFn: ({ traceId, eval_cases_dir }) =>
      fetchApi(`/traces/${encodeURIComponent(traceId)}/promote`, {
        method: 'POST',
        body: JSON.stringify({ eval_cases_dir }),
      }),
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
      const payload = await fetchApi<{ history?: AutoFixHistoryEntry[]; proposals?: AutoFixHistoryEntry[] }>(`/autofix/history?limit=${limit}`);
      return payload.history ?? payload.proposals ?? [];
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

export function useRejectAutoFix() {
  const queryClient = useQueryClient();

  return useMutation<AutoFixApplyOutcome, ApiRequestError, { proposal_id: string }>({
    mutationFn: ({ proposal_id }) =>
      fetchApi(`/autofix/reject/${proposal_id}`, {
        method: 'POST',
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
      const payload = await fetchApi<unknown>(`/context/report?${qs.toString()}`);
      return normalizeContextHealthReport(payload);
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
    mutationFn: async (payload) => {
      const response = await fetchApi<unknown>('/context/simulate', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      return normalizeContextSimulationResult(response, payload);
    },
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

export interface UnifiedEvent {
  id: string;
  event_type: string;
  timestamp: number;
  source: 'system' | 'builder' | string;
  source_label?: string;
  continuity_state?: string;
  session_id?: string | null;
  payload: Record<string, unknown>;
}

export interface UnifiedEventsResponse {
  events: UnifiedEvent[];
  count: number;
  sources?: Record<string, { included: boolean; durable: boolean; label: string }>;
  continuity?: {
    state: string;
    label: string;
    detail: string;
  };
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

export function useUnifiedEvents(
  params: { limit?: number; source?: 'system' | 'builder' | 'all'; session_id?: string } = {}
) {
  return useQuery<UnifiedEventsResponse>({
    queryKey: ['events', 'unified', params],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (params.limit !== undefined) qs.set('limit', String(params.limit));
      if (params.source && params.source !== 'all') qs.set('source', params.source);
      if (params.session_id) qs.set('session_id', params.session_id);
      const query = qs.toString() ? `?${qs.toString()}` : '';
      const payload = await fetchApi<UnifiedEventsResponse>(`/events/unified${query}`);
      return {
        events: payload.events ?? [],
        count: payload.count ?? payload.events?.length ?? 0,
        sources: payload.sources,
        continuity: payload.continuity,
      };
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
// Curriculum
// ---------------------------------------------------------------------------

interface CurriculumBatchesResponse {
  batches: CurriculumBatchSummary[];
  count: number;
  progression: CurriculumDifficultyPoint[];
}

interface RawCurriculumBatchSummary {
  batch_id: string;
  created_at?: number | null;
  generated_at?: number | null;
  prompt_count?: number | null;
  num_prompts?: number | null;
  applied_count?: number | null;
  difficulty_distribution?: Record<string, unknown> | null;
  tier_distribution?: Record<string, unknown> | null;
}

interface RawCurriculumDifficultyPoint {
  batch_id: string;
  created_at?: number | null;
  generated_at?: number | null;
  average_difficulty?: number | null;
}

interface RawCurriculumBatchesResponse {
  batches?: RawCurriculumBatchSummary[];
  count?: number;
  progression?: RawCurriculumDifficultyPoint[];
}

interface RawGenerateCurriculumResponse {
  batch_id: string;
  prompt_count?: number | null;
  num_prompts?: number | null;
}

interface RawApplyCurriculumResponse {
  batch_id: string;
  applied_count?: number | null;
  num_prompts?: number | null;
}

const CURRICULUM_DIFFICULTY_WEIGHTS: Record<string, number> = {
  easy: 0.25,
  medium: 0.5,
  hard: 0.75,
  adversarial: 1,
};

function averageCurriculumDifficulty(distribution: Record<string, number>): number {
  let total = 0;
  let weighted = 0;

  for (const [tier, count] of Object.entries(distribution)) {
    const numericCount = numberValue(count);
    total += numericCount;
    weighted += (CURRICULUM_DIFFICULTY_WEIGHTS[tier] ?? 0) * numericCount;
  }

  return total > 0 ? weighted / total : 0;
}

function mapCurriculumBatchSummary(raw: RawCurriculumBatchSummary): CurriculumBatchSummary {
  return {
    batch_id: raw.batch_id,
    created_at: numberValue(raw.created_at ?? raw.generated_at),
    prompt_count: numberValue(raw.prompt_count ?? raw.num_prompts),
    applied_count: numberValue(raw.applied_count),
    difficulty_distribution: numberRecord(raw.difficulty_distribution ?? raw.tier_distribution),
  };
}

function mapCurriculumDifficultyPoint(raw: RawCurriculumDifficultyPoint): CurriculumDifficultyPoint {
  return {
    batch_id: raw.batch_id,
    created_at: numberValue(raw.created_at ?? raw.generated_at),
    average_difficulty: numberValue(raw.average_difficulty),
  };
}

function normalizeCurriculumBatchesResponse(
  raw: RawCurriculumBatchesResponse
): CurriculumBatchesResponse {
  const batches = Array.isArray(raw.batches) ? raw.batches.map(mapCurriculumBatchSummary) : [];
  const progression = Array.isArray(raw.progression)
    ? raw.progression.map(mapCurriculumDifficultyPoint)
    : batches.map((batch) => ({
        batch_id: batch.batch_id,
        created_at: batch.created_at,
        average_difficulty: averageCurriculumDifficulty(batch.difficulty_distribution),
      }));

  return {
    batches,
    count: numberValue(raw.count, batches.length),
    progression,
  };
}

export function useCurriculumBatches(limit = 20) {
  return useQuery<CurriculumBatchesResponse>({
    queryKey: ['curriculum', 'batches', limit],
    queryFn: async () => {
      const payload = await fetchApi<RawCurriculumBatchesResponse>(`/curriculum/batches?limit=${limit}`);
      return normalizeCurriculumBatchesResponse(payload);
    },
    refetchInterval: 10000,
  });
}

export function useGenerateCurriculum() {
  const queryClient = useQueryClient();
  return useMutation<
    { batch: { batch_id: string; prompt_count: number } },
    ApiRequestError,
    {
      clusters?: Array<Record<string, unknown>>;
      historical_pass_rates?: Record<string, number>;
      prompts_per_cluster?: number;
    }
  >({
    mutationFn: async (body) => {
      const payload = await fetchApi<RawGenerateCurriculumResponse>('/curriculum/generate', {
        method: 'POST',
        body: JSON.stringify(body || {}),
      });
      return {
        batch: {
          batch_id: payload.batch_id,
          prompt_count: numberValue(payload.prompt_count ?? payload.num_prompts),
        },
      };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['curriculum', 'batches'] });
    },
  });
}

export function useApplyCurriculum() {
  const queryClient = useQueryClient();
  return useMutation<{ batch_id: string; applied_count: number }, ApiRequestError, { batch_id: string }>({
    mutationFn: async (body) => {
      const payload = await fetchApi<RawApplyCurriculumResponse>('/curriculum/apply', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      return {
        batch_id: payload.batch_id,
        applied_count: numberValue(payload.applied_count ?? payload.num_prompts),
      };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['curriculum', 'batches'] });
      queryClient.invalidateQueries({ queryKey: ['evalRuns'] });
    },
  });
}

// ---------------------------------------------------------------------------
// Change Review (Proposed Change Cards)
// ---------------------------------------------------------------------------

export function useChanges() {
  return useQuery<ChangeCard[]>({
    queryKey: ['changes'],
    queryFn: async () => {
      const payload = await fetchApi<{ cards?: RawChangeCard[]; changes?: RawChangeCard[] }>('/changes?status=all');
      const cards = payload.cards ?? payload.changes ?? [];
      return cards.map(mapChangeCard);
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
      const payload = await fetchApi<{ card?: RawChangeCard; change?: RawChangeCard }>(
        `/changes/${encodeURIComponent(id)}`
      );
      const raw = payload.card ?? payload.change;
      if (!raw) {
        throw new ApiRequestError('Missing change payload', 500);
      }
      return mapChangeCard(raw);
    },
  });
}

export function useChangeAudit(id: string | null) {
  return useQuery<ChangeAuditDetail>({
    queryKey: ['changes', 'audit', id],
    enabled: Boolean(id),
    queryFn: async () => {
      if (!id) throw new ApiRequestError('Missing change ID', 400);
      const payload = await fetchApi<unknown>(`/changes/${encodeURIComponent(id)}/audit`);
      return normalizeChangeAuditDetail(payload, id);
    },
  });
}

export function useChangeAuditSummary() {
  return useQuery<ChangeAuditSummary>({
    queryKey: ['changes', 'audit-summary'],
    queryFn: async () => {
      const payload = await fetchApi<unknown>('/changes/audit-summary');
      return normalizeChangeAuditSummary(payload);
    },
    refetchInterval: 10000,
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
        body: JSON.stringify({ updates: [{ hunk_id: hunkId, status }] }),
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
// Unified Review Surface
// ---------------------------------------------------------------------------

export function useUnifiedReviews(poll = true) {
  return useQuery<UnifiedReviewItem[]>({
    queryKey: ['unifiedReviews', 'pending'],
    queryFn: async () => {
      const items = await fetchApi<
        Array<{
          id: string;
          source: string;
          status: string;
          title: string;
          description: string;
          score_before: number;
          score_after: number;
          score_delta: number;
          risk_class: string;
          diff_summary: string;
          created_at: string;
          strategy: string | null;
          operator_family: string | null;
          has_detailed_audit: boolean;
          patch_bundle?: Record<string, unknown> | null;
        }>
      >('/reviews/pending');
      return items.map((item) => ({
        id: item.id,
        source: item.source as UnifiedReviewItem['source'],
        status: item.status,
        title: item.title || 'Untitled proposal',
        description: item.description || '',
        score_before: item.score_before ?? 0,
        score_after: item.score_after ?? 0,
        score_delta: item.score_delta ?? 0,
        risk_class: (item.risk_class ?? 'medium') as UnifiedReviewItem['risk_class'],
        diff_summary: item.diff_summary ?? '',
        created_at: item.created_at ?? '',
        strategy: item.strategy ?? null,
        operator_family: item.operator_family ?? null,
        has_detailed_audit: item.has_detailed_audit ?? false,
        patch_bundle: item.patch_bundle ?? null,
      }));
    },
    refetchInterval: poll ? 8000 : false,
  });
}

export function useUnifiedReviewStats(poll = true) {
  return useQuery<UnifiedReviewStats>({
    queryKey: ['unifiedReviews', 'stats'],
    queryFn: () => fetchApi<UnifiedReviewStats>('/reviews/stats'),
    refetchInterval: poll ? 10000 : false,
  });
}

export function useApproveUnifiedReview() {
  const queryClient = useQueryClient();

  return useMutation<
    UnifiedReviewActionResult,
    ApiRequestError,
    { id: string; source: string }
  >({
    mutationFn: ({ id, source }) =>
      fetchApi(`/reviews/${encodeURIComponent(id)}/approve`, {
        method: 'POST',
        body: JSON.stringify({ source }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['unifiedReviews'] });
      queryClient.invalidateQueries({ queryKey: ['optimizePendingReviews'] });
      queryClient.invalidateQueries({ queryKey: ['optimizeHistory'] });
      queryClient.invalidateQueries({ queryKey: ['changes'] });
    },
  });
}

export function useRejectUnifiedReview() {
  const queryClient = useQueryClient();

  return useMutation<
    UnifiedReviewActionResult,
    ApiRequestError,
    { id: string; source: string; reason?: string }
  >({
    mutationFn: ({ id, source, reason }) =>
      fetchApi(`/reviews/${encodeURIComponent(id)}/reject`, {
        method: 'POST',
        body: JSON.stringify({ source, reason: reason ?? '' }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['unifiedReviews'] });
      queryClient.invalidateQueries({ queryKey: ['optimizePendingReviews'] });
      queryClient.invalidateQueries({ queryKey: ['optimizeHistory'] });
      queryClient.invalidateQueries({ queryKey: ['changes'] });
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
      const payload = await fetchApi<{ runbook: Runbook }>(`/runbooks/${encodeURIComponent(name)}`);
      return payload.runbook;
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

export function useCreateRunbook() {
  const queryClient = useQueryClient();

  return useMutation<{ name: string; version: number }, ApiRequestError, Record<string, unknown>>({
    mutationFn: (body) =>
      fetchApi('/runbooks', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runbooks'] });
    },
  });
}

// ---------------------------------------------------------------------------
// Project Memory (AGENTLAB.md)
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
// Intelligence Studio
// ---------------------------------------------------------------------------

export function useTranscriptReports(enabled = true) {
  return useQuery<TranscriptReportSummary[]>({
    queryKey: ['intelligence', 'reports'],
    queryFn: async () => {
      const payload = await fetchApi<{ reports: TranscriptReportSummary[] }>('/intelligence/reports');
      return payload.reports ?? [];
    },
    enabled,
  });
}

export function useTranscriptReport(reportId: string | undefined) {
  return useQuery<TranscriptReport>({
    queryKey: ['intelligence', 'report', reportId],
    enabled: Boolean(reportId),
    queryFn: async () => {
      if (!reportId) {
        throw new ApiRequestError('Missing report ID', 400);
      }
      return fetchApi<TranscriptReport>(`/intelligence/reports/${encodeURIComponent(reportId)}`);
    },
  });
}

export function useImportTranscriptArchive() {
  const queryClient = useQueryClient();
  return useMutation<TranscriptReport, ApiRequestError, { archive_name: string; archive_base64: string }>({
    mutationFn: (body) =>
      fetchApi('/intelligence/archive', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['intelligence', 'reports'] });
    },
  });
}

export function useAskTranscriptReport() {
  return useMutation<IntelligenceAnswer, ApiRequestError, { reportId: string; question: string }>({
    mutationFn: ({ reportId, question }) =>
      fetchApi(`/intelligence/reports/${encodeURIComponent(reportId)}/ask`, {
        method: 'POST',
        body: JSON.stringify({ question }),
      }),
  });
}

export function useApplyTranscriptInsight() {
  const queryClient = useQueryClient();
  return useMutation<ApplyInsightResult, ApiRequestError, { reportId: string; insight_id: string }>({
    mutationFn: ({ reportId, insight_id }) =>
      fetchApi(`/intelligence/reports/${encodeURIComponent(reportId)}/apply`, {
        method: 'POST',
        body: JSON.stringify({ insight_id }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changes'] });
    },
  });
}

export function useKnowledgeAsset(assetId: string | undefined) {
  return useQuery<KnowledgeAsset>({
    queryKey: ['intelligence', 'knowledge', assetId],
    enabled: Boolean(assetId),
    queryFn: async () => {
      if (!assetId) {
        throw new ApiRequestError('Missing knowledge asset ID', 400);
      }
      return fetchApi<KnowledgeAsset>(`/intelligence/knowledge/${encodeURIComponent(assetId)}`);
    },
  });
}

export function useDeepResearchReport() {
  return useMutation<DeepResearchReport, ApiRequestError, { reportId: string; question: string }>({
    mutationFn: ({ reportId, question }) =>
      fetchApi(`/intelligence/reports/${encodeURIComponent(reportId)}/deep-research`, {
        method: 'POST',
        body: JSON.stringify({ question }),
      }),
  });
}

export function useRunAutonomousLoop() {
  const queryClient = useQueryClient();
  return useMutation<AutonomousLoopResult, ApiRequestError, { reportId: string; auto_ship: boolean }>({
    mutationFn: ({ reportId, auto_ship }) =>
      fetchApi(`/intelligence/reports/${encodeURIComponent(reportId)}/autonomous-loop`, {
        method: 'POST',
        body: JSON.stringify({ auto_ship }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changes'] });
    },
  });
}

export function useBuildAgentArtifact() {
  const queryClient = useQueryClient();
  return useMutation<PromptBuildArtifact, ApiRequestError, { prompt: string; connectors: string[] }>({
    mutationFn: (body) =>
      fetchApi('/intelligence/build', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['build-artifacts'] });
    },
  });
}

export function useBuilderArtifacts(params?: {
  taskId?: string;
  sessionId?: string;
  artifactType?: ArtifactType;
  enabled?: boolean;
}) {
  const query = new URLSearchParams();
  if (params?.taskId) query.set('task_id', params.taskId);
  if (params?.sessionId) query.set('session_id', params.sessionId);
  if (params?.artifactType) query.set('artifact_type', params.artifactType);
  const qs = query.toString();

  return useQuery<ArtifactRef[]>({
    queryKey: ['builder', 'artifacts', params?.taskId || null, params?.sessionId || null, params?.artifactType || null],
    queryFn: async () => fetchApi<ArtifactRef[]>(`/builder/artifacts${qs ? `?${qs}` : ''}`),
    enabled: params?.enabled ?? true,
  });
}

export function useGenerateAgent() {
  const queryClient = useQueryClient();
  return useMutation<
    GeneratedAgentConfig,
    ApiRequestError,
    {
      prompt: string;
      transcript_report_id?: string;
      instruction_xml?: string;
      requested_model?: string;
      requested_agent_name?: string;
      tool_hints?: string[];
    }
  >({
    mutationFn: (body) =>
      fetchApi('/intelligence/generate-agent', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['build-artifacts'] });
    },
  });
}

interface SharedBuildArtifactRecord {
  id: string;
  source: BuildArtifactSource;
  status: BuildArtifactStatus;
  created_at: string;
  updated_at: string;
  config_yaml: string;
  prompt_used?: string;
  transcript_report_id?: string;
  builder_session_id?: string;
  eval_draft?: string;
  starter_config_path?: string;
  metadata?: Record<string, unknown>;
}

function mapSharedBuildArtifact(record: SharedBuildArtifactRecord): BuildArtifact {
  const metadata = record.metadata ?? {};
  const title =
    (typeof metadata.title === 'string' && metadata.title.trim()) ||
    record.prompt_used ||
    'Saved Build Artifact';
  const summary =
    (typeof metadata.summary === 'string' && metadata.summary.trim()) ||
    'Persisted build artifact from the shared Build workspace.';

  return {
    artifact_id: record.id,
    title,
    summary,
    source: record.source,
    status: record.status,
    created_at: record.created_at,
    updated_at: record.updated_at,
    config_yaml: record.config_yaml,
    prompt_used: record.prompt_used,
    transcript_report_id: record.transcript_report_id,
    builder_session_id: record.builder_session_id,
    eval_draft: record.eval_draft,
    starter_config_path: record.starter_config_path,
    api_artifact_id: record.id,
  };
}

export function useSavedBuildArtifacts(enabled = true) {
  return useQuery<BuildArtifact[]>({
    queryKey: ['build-artifacts'],
    enabled,
    queryFn: async () => {
      const payload = await fetchApi<{ artifacts: SharedBuildArtifactRecord[] }>('/intelligence/build-artifacts');
      return (payload.artifacts ?? []).map(mapSharedBuildArtifact);
    },
  });
}

export function useChatRefine() {
  return useMutation<ChatRefineResponse, ApiRequestError, { message: string; config: GeneratedAgentConfig }>({
    mutationFn: (body) =>
      fetchApi('/intelligence/chat', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  });
}

export function saveGeneratedAgent(body: {
  config: GeneratedAgentConfig;
  source: BuildArtifactSource;
  prompt_used?: string;
  transcript_report_id?: string;
  builder_session_id?: string;
}) {
  return fetchApi<BuildSaveResult>('/intelligence/save-agent', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function previewGeneratedAgent(body: {
  message: string;
  config: GeneratedAgentConfig;
}) {
  return fetchApi<BuildPreviewResult>('/intelligence/preview-agent', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// CX Agent Studio
// ---------------------------------------------------------------------------

export function useConnectImport() {
  const qc = useQueryClient();
  return useMutation<ConnectImportResult, ApiRequestError, ConnectImportRequest>({
    mutationFn: (body) => fetchApi('/connect/import', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['configs'] }),
  });
}

export function useCxAgents(project: string, location: string, credentialsPath?: string) {
  return useQuery<CxAgentSummary[]>({
    queryKey: ['cx-agents', project, location, credentialsPath],
    queryFn: () => {
      const params = new URLSearchParams({
        project,
        location,
      });
      if (credentialsPath) {
        params.set('credentials_path', credentialsPath);
      }
      return fetchApi(`/cx/agents?${params.toString()}`);
    },
    enabled: !!project,
  });
}

export function useCxAuth() {
  return useMutation<CxAuthResult, ApiRequestError, {
    credentials_path?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/auth', { method: 'POST', body: JSON.stringify(body) }),
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
    credentials_path?: string;
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
    credentials_path?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/export', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxDiff() {
  return useMutation<CxExportResult, ApiRequestError, {
    project: string;
    location: string;
    agent_id: string;
    config: Record<string, unknown>;
    snapshot_path: string;
    credentials_path?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/diff', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxSync() {
  return useMutation<CxExportResult, ApiRequestError, {
    project: string;
    location: string;
    agent_id: string;
    config: Record<string, unknown>;
    snapshot_path: string;
    conflict_strategy?: string;
    credentials_path?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/sync', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxPreflight() {
  return useMutation<CxPreflightResult, ApiRequestError, {
    config: Record<string, unknown>;
    export_matrix?: Record<string, unknown> | null;
  }>({
    mutationFn: (body) => fetchApi('/cx/preflight', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxDeploy() {
  return useMutation<CxDeployResult, ApiRequestError, {
    project: string;
    location: string;
    agent_id: string;
    environment?: string;
    strategy?: string;
    traffic_pct?: number;
    credentials_path?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/deploy', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxPromote() {
  return useMutation<CxDeployResult, ApiRequestError, {
    project: string;
    location: string;
    agent_id: string;
    canary: CxCanaryState;
    credentials_path?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/promote', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxRollback() {
  return useMutation<CxDeployResult, ApiRequestError, {
    project: string;
    location: string;
    agent_id: string;
    canary: CxCanaryState;
    credentials_path?: string;
  }>({
    mutationFn: (body) => fetchApi('/cx/rollback', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useCxDeployStatus(project: string, location: string, agentId: string) {
  return useQuery<CxDeployStatusResult>({
    queryKey: ['cx-deploy-status', project, location, agentId],
    queryFn: () => {
      const params = new URLSearchParams({ project, location, agent_id: agentId });
      return fetchApi<CxDeployStatusResult>(`/cx/status?${params}`);
    },
    enabled: !!project && !!agentId,
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

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------

export function useSkills(category?: string, platform?: string) {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  if (platform) params.set('platform', platform);
  const qs = params.toString();
  return useQuery<{ skills: ExecutableSkill[]; count: number }>({
    queryKey: ['skills', category, platform],
    queryFn: () => fetchApi<{ skills: ExecutableSkill[]; count: number }>(
      `/skills${qs ? `?${qs}` : ''}`
    ),
  });
}

export function useSkill(name: string | null) {
  return useQuery<{ skill: ExecutableSkill }>({
    queryKey: ['skill', name],
    queryFn: () => fetchApi<{ skill: ExecutableSkill }>(`/skills/${name}`),
    enabled: !!name,
  });
}

export function useSkillRecommendations() {
  return useQuery<{ skills: ExecutableSkill[]; count: number }>({
    queryKey: ['skills', 'recommend'],
    queryFn: () => fetchApi<{ skills: ExecutableSkill[]; count: number }>('/skills/recommend'),
  });
}

export function useSkillStats() {
  return useQuery<{ leaderboard: SkillLeaderboardEntry[]; count: number }>({
    queryKey: ['skills', 'stats'],
    queryFn: () => fetchApi<{ leaderboard: SkillLeaderboardEntry[]; count: number }>('/skills/stats'),
  });
}

export function useApplySkill() {
  const queryClient = useQueryClient();
  return useMutation<{ status: string; message: string }, ApiRequestError, string>({
    mutationFn: (name) =>
      fetchApi<{ status: string; message: string }>(`/skills/${encodeURIComponent(name)}/apply`, {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
    },
  });
}

export function useUnifiedSkills(params?: {
  kind?: 'build' | 'runtime';
  domain?: string;
  tags?: string[];
}) {
  const query = new URLSearchParams();
  if (params?.kind) query.set('kind', params.kind);
  if (params?.domain) query.set('domain', params.domain);
  if (params?.tags && params.tags.length > 0) query.set('tags', params.tags.join(','));
  const qs = query.toString();
  return useQuery<{ skills: UnifiedSkill[]; count: number }>({
    queryKey: ['skills', 'unified', params?.kind, params?.domain, (params?.tags || []).join(',')],
    queryFn: () =>
      fetchApi<{ skills: UnifiedSkill[]; count: number }>(
        `/skills${qs ? `?${qs}` : ''}`
      ),
  });
}

export function useSkillDrafts(limit = 100) {
  return useQuery<{ drafts: DraftSkillReview[]; count: number }>({
    queryKey: ['skills', 'drafts', limit],
    queryFn: () => fetchApi(`/skills/drafts?limit=${limit}`),
    refetchInterval: 10000,
  });
}

export function useEditDraftSkill() {
  const queryClient = useQueryClient();
  return useMutation<{ skill: UnifiedSkill }, ApiRequestError, {
    id: string;
    updates: Record<string, unknown>;
  }>({
    mutationFn: ({ id, updates }) =>
      fetchApi(`/skills/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify(updates),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills', 'drafts'] });
      queryClient.invalidateQueries({ queryKey: ['skills', 'unified'] });
    },
  });
}

export function usePromoteSkill() {
  const queryClient = useQueryClient();
  return useMutation<{ skill: UnifiedSkill }, ApiRequestError, {
    id: string;
    approved_by?: string;
    change_notes?: string;
  }>({
    mutationFn: ({ id, approved_by, change_notes }) =>
      fetchApi(`/skills/${encodeURIComponent(id)}/promote`, {
        method: 'POST',
        body: JSON.stringify({ approved_by, change_notes }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills', 'drafts'] });
      queryClient.invalidateQueries({ queryKey: ['skills', 'unified'] });
    },
  });
}

export function useArchiveSkill() {
  const queryClient = useQueryClient();
  return useMutation<{ skill: UnifiedSkill }, ApiRequestError, {
    id: string;
    reason: string;
    reviewed_by?: string;
  }>({
    mutationFn: ({ id, reason, reviewed_by }) =>
      fetchApi(`/skills/${encodeURIComponent(id)}/archive`, {
        method: 'POST',
        body: JSON.stringify({ reason, reviewed_by }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills', 'drafts'] });
      queryClient.invalidateQueries({ queryKey: ['skills', 'unified'] });
    },
  });
}

export function useCreateSkill() {
  const queryClient = useQueryClient();
  return useMutation<{ skill: UnifiedSkill }, ApiRequestError, Partial<UnifiedSkill>>({
    mutationFn: (body) =>
      fetchApi<{ skill: UnifiedSkill }>('/skills', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills', 'unified'] });
    },
  });
}

export function useUpdateSkill() {
  const queryClient = useQueryClient();
  return useMutation<{ skill: UnifiedSkill }, ApiRequestError, { id: string; updates: Record<string, unknown> }>({
    mutationFn: ({ id, updates }) =>
      fetchApi<{ skill: UnifiedSkill }>(`/skills/${encodeURIComponent(id)}`, {
        method: 'PUT',
        body: JSON.stringify(updates),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills', 'unified'] });
    },
  });
}

export function useDeleteSkill() {
  const queryClient = useQueryClient();
  return useMutation<{ deleted: boolean }, ApiRequestError, string>({
    mutationFn: (id) =>
      fetchApi<{ deleted: boolean }>(`/skills/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills', 'unified'] });
    },
  });
}

export function useTestSkill() {
  const queryClient = useQueryClient();
  return useMutation<{
    skill_id: string;
    results: Array<{ name: string; passed: boolean; message: string }>;
    passed: boolean;
    pass_rate: number;
  }, ApiRequestError, string>({
    mutationFn: (id) =>
      fetchApi(`/skills/${encodeURIComponent(id)}/test`, {
        method: 'POST',
      }),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['skills', 'unified'] });
      queryClient.invalidateQueries({ queryKey: ['skills', 'effectiveness', id] });
    },
  });
}

export function useComposeSkills() {
  return useMutation<SkillCompositionResult, ApiRequestError, { skills: string[] }>({
    mutationFn: (body) =>
      fetchApi<SkillCompositionResult>('/skills/compose', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  });
}

export function useSkillMarketplace(params?: { kind?: 'build' | 'runtime' }) {
  const query = new URLSearchParams();
  if (params?.kind) query.set('kind', params.kind);
  const qs = query.toString();
  return useQuery<{ listings: SkillMarketplaceListing[]; count: number }>({
    queryKey: ['skills', 'marketplace', params?.kind || 'all'],
    queryFn: () =>
      fetchApi<{ listings: SkillMarketplaceListing[]; count: number }>(
        `/skills/marketplace${qs ? `?${qs}` : ''}`
      ),
  });
}

export function useInstallMarketplaceSkill() {
  const queryClient = useQueryClient();
  return useMutation<{ installed: UnifiedSkill; name: string }, ApiRequestError, { name: string }>({
    mutationFn: (body) =>
      fetchApi<{ installed: UnifiedSkill; name: string }>('/skills/install', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills', 'unified'] });
      queryClient.invalidateQueries({ queryKey: ['skills', 'marketplace'] });
    },
  });
}

export function useSkillEffectiveness(skillId: string | null) {
  return useQuery<{
    effectiveness: {
      skill_id: string;
      metrics: Record<string, unknown>;
      history: Array<Record<string, unknown>>;
    };
  }>({
    queryKey: ['skills', 'effectiveness', skillId],
    queryFn: () => fetchApi(`/skills/${encodeURIComponent(skillId || '')}/effectiveness`),
    enabled: !!skillId,
  });
}

// ---------------------------------------------------------------------------
// ADK Integration
// ---------------------------------------------------------------------------

export function useAdkStatus(path: string) {
  return useQuery<{ agent: AdkAgent }>({
    queryKey: ['adk-status', path],
    queryFn: () => fetchApi(`/adk/status?path=${encodeURIComponent(path)}`),
    enabled: !!path,
  });
}

export function useAdkImport() {
  const qc = useQueryClient();
  return useMutation<AdkImportResult, ApiRequestError, {
    path: string;
    output_dir?: string;
  }>({
    mutationFn: (body) => fetchApi('/adk/import', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['configs'] }),
  });
}

export function useAdkExport() {
  return useMutation<AdkExportResult, ApiRequestError, {
    config_path: string;
    output_path?: string;
  }>({
    mutationFn: (body) => fetchApi('/adk/export', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useAdkDeploy() {
  return useMutation<AdkDeployResult, ApiRequestError, {
    path: string;
    target: 'cloud-run' | 'vertex-ai';
    project: string;
    region?: string;
  }>({
    mutationFn: (body) => fetchApi('/adk/deploy', { method: 'POST', body: JSON.stringify(body) }),
  });
}

export function useAdkDiff(configPath: string, snapshotPath: string) {
  return useQuery<{ diff: string; changes: Array<{ file: string; field: string; action: string }> }>({
    queryKey: ['adk-diff', configPath, snapshotPath],
    queryFn: () => fetchApi(`/adk/diff?config_path=${encodeURIComponent(configPath)}&snapshot_path=${encodeURIComponent(snapshotPath)}`),
    enabled: !!configPath && !!snapshotPath,
  });
}

// Diagnosis Chat
export function useDiagnoseChat() {
  return useMutation({
    mutationFn: (data: { message: string; session_id?: string }) =>
      fetchApi<DiagnoseChatResponse>('/diagnose/chat', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
  });
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

export function useNotificationSubscriptions() {
  return useQuery<{ subscriptions: NotificationSubscription[] }>({
    queryKey: ['notifications', 'subscriptions'],
    queryFn: () => fetchApi<{ subscriptions: NotificationSubscription[] }>('/notifications/subscriptions'),
  });
}

export function useNotificationHistory(limit = 100) {
  return useQuery<{ history: NotificationHistoryEntry[] }>({
    queryKey: ['notifications', 'history', limit],
    queryFn: () => fetchApi<{ history: NotificationHistoryEntry[] }>(`/notifications/history?limit=${limit}`),
  });
}

export function useRegisterWebhook() {
  const queryClient = useQueryClient();
  return useMutation<
    { subscription_id: string; status: string },
    ApiRequestError,
    { url: string; events: string[]; filters?: Record<string, string> }
  >({
    mutationFn: (data) =>
      fetchApi<{ subscription_id: string; status: string }>('/notifications/webhook', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications', 'subscriptions'] });
    },
  });
}

export function useRegisterSlack() {
  const queryClient = useQueryClient();
  return useMutation<
    { subscription_id: string; status: string },
    ApiRequestError,
    { webhook_url: string; events: string[]; filters?: Record<string, string> }
  >({
    mutationFn: (data) =>
      fetchApi<{ subscription_id: string; status: string }>('/notifications/slack', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications', 'subscriptions'] });
    },
  });
}

export function useRegisterEmail() {
  const queryClient = useQueryClient();
  return useMutation<
    { subscription_id: string; status: string },
    ApiRequestError,
    { address: string; events: string[]; filters?: Record<string, string>; smtp_config?: Record<string, string> }
  >({
    mutationFn: (data) =>
      fetchApi<{ subscription_id: string; status: string }>('/notifications/email', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications', 'subscriptions'] });
    },
  });
}

export function useDeleteSubscription() {
  const queryClient = useQueryClient();
  return useMutation<{ status: string }, ApiRequestError, string>({
    mutationFn: (subscriptionId) =>
      fetchApi<{ status: string }>(`/notifications/subscriptions/${subscriptionId}`, {
        method: 'DELETE',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications', 'subscriptions'] });
    },
  });
}

export function useTestSubscription() {
  return useMutation<{ status: string; message: string }, ApiRequestError, string>({
    mutationFn: (subscriptionId) =>
      fetchApi<{ status: string; message: string }>(`/notifications/test/${subscriptionId}`, {
        method: 'POST',
      }),
  });
}
