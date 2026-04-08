import { useState } from 'react';
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  FlaskConical,
  Layers,
  Loader2,
  Play,
  Rocket,
  Sparkles,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react';
import { StatusBadge } from '../../components/StatusBadge';
import { classNames, scoreColor, formatTimestamp } from '../../lib/utils';
import { toastInfo, toastSuccess } from '../../lib/toast';
import type { EvalSetSummary, OptimizeMode, StudioCandidate } from './studio-types';
import {
  MOCK_CANDIDATES,
  MOCK_EVAL_SETS,
  MOCK_OPTIMIZE_MODE_CONFIGS,
  MOCK_OPTIMIZE_RUN,
} from './studio-mock';

// ─── Mode Selector ────────────────────────────────────────────────────────────

interface ModeSelectorProps {
  selected: OptimizeMode;
  onChange: (m: OptimizeMode) => void;
}

const modeIcons: Record<OptimizeMode, React.ComponentType<{ className?: string }>> = {
  basic: Zap,
  research: Sparkles,
  pro: Layers,
};

const modeColors: Record<OptimizeMode, { ring: string; bg: string; icon: string; badge: string }> = {
  basic: { ring: 'border-blue-400', bg: 'bg-blue-50', icon: 'text-blue-600', badge: 'bg-blue-100 text-blue-700' },
  research: { ring: 'border-violet-400', bg: 'bg-violet-50', icon: 'text-violet-600', badge: 'bg-violet-100 text-violet-700' },
  pro: { ring: 'border-indigo-500', bg: 'bg-indigo-50', icon: 'text-indigo-600', badge: 'bg-indigo-100 text-indigo-700' },
};

function ModeSelector({ selected, onChange }: ModeSelectorProps) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {MOCK_OPTIMIZE_MODE_CONFIGS.map((cfg) => {
        const Icon = modeIcons[cfg.mode];
        const colors = modeColors[cfg.mode];
        const isSelected = selected === cfg.mode;

        return (
          <button
            key={cfg.mode}
            onClick={() => onChange(cfg.mode)}
            className={classNames(
              'relative rounded-xl border-2 p-4 text-left transition-all',
              isSelected
                ? `${colors.ring} ${colors.bg} shadow-sm`
                : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
            )}
          >
            {isSelected && (
              <div className="absolute right-3 top-3">
                <Check className={classNames('h-4 w-4', colors.icon)} />
              </div>
            )}
            <div className={classNames('mb-2 inline-flex rounded-lg p-1.5', isSelected ? colors.bg : 'bg-gray-100')}>
              <Icon className={classNames('h-4 w-4', isSelected ? colors.icon : 'text-gray-500')} />
            </div>
            <div className="mb-1 flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-900">{cfg.label}</span>
              <span className={classNames('rounded px-1.5 py-0.5 text-[10px] font-medium', colors.badge)}>
                {cfg.estimated_duration}
              </span>
            </div>
            <p className="text-[12px] leading-relaxed text-gray-600">{cfg.description}</p>
            <div className="mt-2 flex items-center gap-3 text-[11px] text-gray-400">
              <span>{cfg.iterations} iteration{cfg.iterations !== 1 ? 's' : ''}</span>
              {cfg.uses_research && <span className="text-violet-500">+ research</span>}
              {cfg.uses_pareto && <span className="text-indigo-500">+ pareto</span>}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── Eval Set Picker ──────────────────────────────────────────────────────────

interface EvalSetPickerProps {
  sets: EvalSetSummary[];
  selected: string[];
  onToggle: (id: string) => void;
}

function EvalSetPicker({ sets, selected, onToggle }: EvalSetPickerProps) {
  return (
    <div className="space-y-2">
      {sets.map((s) => {
        const isSelected = selected.includes(s.eval_set_id);
        return (
          <button
            key={s.eval_set_id}
            onClick={() => onToggle(s.eval_set_id)}
            className={classNames(
              'flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-all',
              isSelected
                ? 'border-indigo-300 bg-indigo-50'
                : 'border-gray-200 bg-white hover:border-gray-300'
            )}
          >
            <div
              className={classNames(
                'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                isSelected ? 'border-indigo-500 bg-indigo-500' : 'border-gray-300'
              )}
            >
              {isSelected && <Check className="h-2.5 w-2.5 text-white" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-gray-900">{s.name}</span>
                <span className="shrink-0 text-xs text-gray-500">{s.num_cases} cases</span>
              </div>
              <p className="mt-0.5 text-xs text-gray-500 truncate">{s.description}</p>
              {s.pass_rate !== null && (
                <div className="mt-1 flex items-center gap-1.5">
                  <div className="h-1 flex-1 rounded-full bg-gray-200">
                    <div
                      className={classNames(
                        'h-1 rounded-full',
                        s.pass_rate >= 0.85 ? 'bg-green-500' : s.pass_rate >= 0.7 ? 'bg-amber-500' : 'bg-red-500'
                      )}
                      style={{ width: `${s.pass_rate * 100}%` }}
                    />
                  </div>
                  <span className={classNames('text-[11px] font-medium', scoreColor(s.pass_rate * 100))}>
                    {(s.pass_rate * 100).toFixed(0)}%
                  </span>
                </div>
              )}
              {s.last_run && (
                <p className="mt-0.5 text-[10px] text-gray-400">Last run {formatTimestamp(s.last_run)}</p>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── Candidate Score Row ──────────────────────────────────────────────────────

const SCORE_COLS = [
  { key: 'overall', label: 'Overall' },
  { key: 'task_success', label: 'Task Success' },
  { key: 'response_quality', label: 'Response Quality' },
  { key: 'safety', label: 'Safety' },
  { key: 'latency_score', label: 'Latency' },
  { key: 'cost_score', label: 'Cost' },
] as const;

type ScoreKey = (typeof SCORE_COLS)[number]['key'];

interface CandidateTableProps {
  candidates: StudioCandidate[];
  selectedId: string | null;
  recommendedId: string | null;
  onSelect: (id: string) => void;
}

function CandidateTable({ candidates, selectedId, recommendedId, onSelect }: CandidateTableProps) {
  const baseline = candidates.find((c) => c.is_baseline);

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            <th className="sticky left-0 bg-gray-50 px-4 py-2.5 text-left text-xs font-semibold text-gray-600">
              Candidate
            </th>
            {SCORE_COLS.map((col) => (
              <th key={col.key} className="px-3 py-2.5 text-center text-xs font-semibold text-gray-600">
                {col.label}
              </th>
            ))}
            <th className="px-3 py-2.5 text-center text-xs font-semibold text-gray-600">Status</th>
            <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600">Diff</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {candidates.map((c) => {
            const isSelected = c.candidate_id === selectedId;
            const isRecommended = c.candidate_id === recommendedId;

            return (
              <tr
                key={c.candidate_id}
                onClick={() => !c.is_baseline && onSelect(c.candidate_id)}
                className={classNames(
                  'transition-colors',
                  c.is_baseline ? 'bg-gray-50/50' : 'cursor-pointer hover:bg-indigo-50/40',
                  isSelected && !c.is_baseline ? 'bg-indigo-50' : ''
                )}
              >
                {/* Label */}
                <td className="sticky left-0 bg-inherit px-4 py-3">
                  <div className="flex items-center gap-2">
                    {isSelected && !c.is_baseline && (
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-indigo-500" />
                    )}
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium text-gray-900 text-[13px]">{c.label}</span>
                        {isRecommended && (
                          <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-indigo-700">
                            Recommended
                          </span>
                        )}
                        {c.is_baseline && (
                          <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[9px] font-medium text-gray-500">
                            baseline
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-[10px] text-gray-400">{formatTimestamp(c.created_at)}</div>
                    </div>
                  </div>
                </td>

                {/* Scores */}
                {SCORE_COLS.map((col) => {
                  const score = c.scores[col.key as ScoreKey];
                  const baseScore = baseline?.scores[col.key as ScoreKey] ?? 0;
                  const delta = c.is_baseline ? null : score - baseScore;

                  return (
                    <td key={col.key} className="px-3 py-3 text-center">
                      {c.status === 'running' ? (
                        <Loader2 className="mx-auto h-3.5 w-3.5 animate-spin text-gray-400" />
                      ) : (
                        <div>
                          <span className={classNames('font-semibold text-[13px]', scoreColor(score))}>
                            {score.toFixed(1)}
                          </span>
                          {delta !== null && delta !== 0 && (
                            <div
                              className={classNames(
                                'text-[10px] font-medium',
                                delta > 0 ? 'text-green-600' : 'text-red-500'
                              )}
                            >
                              {delta > 0 ? '+' : ''}{delta.toFixed(1)}
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                  );
                })}

                {/* Status */}
                <td className="px-3 py-3 text-center">
                  <StatusBadge
                    variant={
                      c.status === 'evaluated'
                        ? 'success'
                        : c.status === 'running'
                        ? 'running'
                        : c.status === 'promoted'
                        ? 'success'
                        : c.status === 'rejected'
                        ? 'error'
                        : 'pending'
                    }
                    label={c.status}
                  />
                </td>

                {/* Diff preview */}
                <td className="px-3 py-3">
                  {c.is_baseline ? (
                    <span className="text-[11px] text-gray-400">—</span>
                  ) : c.spec_diff_lines.length > 0 ? (
                    <span className="flex items-center gap-1 text-[11px]">
                      <span className="text-green-600">+{c.spec_diff_lines.filter((l) => l.type === 'added').length}</span>
                      <span className="text-gray-300">/</span>
                      <span className="text-red-500">-{c.spec_diff_lines.filter((l) => l.type === 'removed').length}</span>
                    </span>
                  ) : (
                    <span className="text-[11px] text-gray-400">pending</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Candidate Diff Detail ────────────────────────────────────────────────────

interface CandidateDiffDetailProps {
  candidate: StudioCandidate;
  onClose: () => void;
  onPromote: () => void;
  onReject: () => void;
}

function CandidateDiffDetail({ candidate, onClose, onPromote, onReject }: CandidateDiffDetailProps) {
  return (
    <div className="rounded-xl border border-indigo-200 bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 bg-indigo-50 px-5 py-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-indigo-600" />
          <span className="text-sm font-semibold text-gray-900">{candidate.label}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onReject}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-red-50 hover:border-red-200 hover:text-red-700 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
            Reject
          </button>
          <button
            onClick={onPromote}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 transition-colors shadow-sm"
          >
            <Rocket className="h-3.5 w-3.5" />
            Promote to spec
          </button>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:text-gray-600">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Score summary */}
      <div className="grid grid-cols-6 gap-px bg-gray-100">
        {SCORE_COLS.map((col) => {
          const score = candidate.scores[col.key as ScoreKey];
          return (
            <div key={col.key} className="bg-white px-4 py-3 text-center">
              <div className={classNames('text-xl font-bold tabular-nums', scoreColor(score))}>
                {score.toFixed(1)}
              </div>
              <div className="mt-0.5 text-[10px] text-gray-500">{col.label}</div>
            </div>
          );
        })}
      </div>

      {/* Spec diff */}
      {candidate.spec_diff_lines.length > 0 && (
        <div className="border-t border-gray-200">
          <div className="border-b border-gray-100 bg-gray-50 px-5 py-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
              Spec Changes
            </span>
          </div>
          <div className="overflow-x-auto font-mono text-[12px]">
            {candidate.spec_diff_lines.map((line, i) => (
              <div
                key={i}
                className={classNames(
                  'flex gap-3 px-5 py-0.5 min-h-[1.5rem]',
                  line.type === 'added' && 'bg-green-50 text-green-800',
                  line.type === 'removed' && 'bg-red-50 text-red-800',
                  line.type === 'context' && 'text-gray-500'
                )}
              >
                <span className="select-none w-4 shrink-0 text-gray-400">
                  {line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '}
                </span>
                <span className="whitespace-pre-wrap">{line.content}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── StudioOptimize ───────────────────────────────────────────────────────────

export function StudioOptimize() {
  const [selectedMode, setSelectedMode] = useState<OptimizeMode>('research');
  const [selectedEvalSets, setSelectedEvalSets] = useState<string[]>(['es-001']);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    MOCK_OPTIMIZE_RUN.recommended_candidate_id
  );
  const [isRunning, setIsRunning] = useState(false);
  const [hasRun, setHasRun] = useState(true); // show mock results by default

  const toggleEvalSet = (id: string) => {
    setSelectedEvalSets((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleRun = () => {
    setIsRunning(true);
    toastInfo('Optimization run started…');
    setTimeout(() => {
      setIsRunning(false);
      setHasRun(true);
      toastSuccess('Optimization complete — 2 candidates ready for review');
    }, 2500);
  };

  const selectedCandidate = hasRun
    ? MOCK_CANDIDATES.find((c) => c.candidate_id === selectedCandidateId && !c.is_baseline) ?? null
    : null;

  const handlePromote = () => {
    toastSuccess(`${selectedCandidate?.label ?? 'Candidate'} promoted — spec updated to v5`);
    setSelectedCandidateId(null);
  };

  const handleReject = () => {
    toastInfo('Candidate rejected');
    setSelectedCandidateId(null);
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-gray-50 p-5 space-y-5">
      {/* Config row */}
      <div className="grid grid-cols-[1fr_320px] gap-5">
        {/* Mode selector */}
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-800">Optimization Mode</h3>
          <ModeSelector selected={selectedMode} onChange={setSelectedMode} />
        </div>

        {/* Eval sets */}
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-gray-500" />
            Eval Sets
          </h3>
          <EvalSetPicker
            sets={MOCK_EVAL_SETS}
            selected={selectedEvalSets}
            onToggle={toggleEvalSet}
          />
        </div>
      </div>

      {/* Run button */}
      <div className="flex items-center gap-4">
        <button
          onClick={handleRun}
          disabled={isRunning || selectedEvalSets.length === 0}
          className={classNames(
            'flex items-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold transition-all shadow-sm',
            isRunning || selectedEvalSets.length === 0
              ? 'cursor-not-allowed bg-gray-100 text-gray-400'
              : 'bg-indigo-600 text-white hover:bg-indigo-700 active:scale-[0.98]'
          )}
        >
          {isRunning ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Running…
            </>
          ) : (
            <>
              <Play className="h-4 w-4" />
              Run {MOCK_OPTIMIZE_MODE_CONFIGS.find((m) => m.mode === selectedMode)?.label} Optimization
            </>
          )}
        </button>

        {selectedEvalSets.length === 0 && (
          <span className="text-xs text-amber-600">Select at least one eval set to run</span>
        )}

        {hasRun && !isRunning && (
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Check className="h-3.5 w-3.5 text-green-500" />
            Last run completed {formatTimestamp(MOCK_OPTIMIZE_RUN.completed_at!)}
            <span className="text-gray-300 mx-1">·</span>
            <span className="text-indigo-600 font-medium cursor-pointer hover:underline flex items-center gap-0.5">
              View log <ArrowUpRight className="h-3 w-3" />
            </span>
          </div>
        )}
      </div>

      {/* Candidate comparison table */}
      {hasRun && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-800">
              Candidates
              <span className="ml-2 text-xs font-normal text-gray-500">
                Click a row to inspect diff and promote
              </span>
            </h3>
            {MOCK_OPTIMIZE_RUN.recommended_candidate_id && (
              <span className="flex items-center gap-1.5 text-xs text-indigo-600">
                <Sparkles className="h-3.5 w-3.5" />
                Recommended: Candidate B
              </span>
            )}
          </div>

          <CandidateTable
            candidates={MOCK_CANDIDATES}
            selectedId={selectedCandidateId}
            recommendedId={MOCK_OPTIMIZE_RUN.recommended_candidate_id}
            onSelect={setSelectedCandidateId}
          />
        </div>
      )}

      {/* Candidate detail / review CTA */}
      {selectedCandidate && (
        <CandidateDiffDetail
          candidate={selectedCandidate}
          onClose={() => setSelectedCandidateId(null)}
          onPromote={handlePromote}
          onReject={handleReject}
        />
      )}

      {/* Run log tail */}
      {hasRun && (
        <div className="rounded-xl border border-gray-200 bg-gray-900 p-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
              Run Log
            </span>
            <span className="rounded bg-green-900/60 px-1.5 py-0.5 text-[10px] font-medium text-green-400">
              completed
            </span>
          </div>
          <div className="space-y-0.5 font-mono text-[11px] text-gray-400">
            {MOCK_OPTIMIZE_RUN.log_tail.map((line, i) => (
              <div key={i} className="flex gap-2">
                <span className="select-none text-gray-600">{String(i + 1).padStart(2, '0')}</span>
                <span
                  className={classNames(
                    line.includes('Error') || line.includes('failed')
                      ? 'text-red-400'
                      : line.includes('complete') || line.includes('Recommended')
                      ? 'text-green-400'
                      : line.includes('Hypothesis') || line.includes('generated')
                      ? 'text-indigo-300'
                      : 'text-gray-400'
                  )}
                >
                  {line}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
