import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import type { DimensionScores, LayeredDimensionScores, MetricLayer } from '../lib/types';
import { classNames } from '../lib/utils';

// ---------------------------------------------------------------------------
// Layer definitions
// ---------------------------------------------------------------------------

interface MetricDef {
  key: string;
  label: string;
  direction: 'maximize' | 'minimize';
  threshold?: number;
}

interface LayerDef {
  layer: MetricLayer;
  label: string;
  description: string;
  metrics: MetricDef[];
  defaultOpen: boolean;
}

const HARD_GATE_METRICS: MetricDef[] = [
  { key: 'safety_compliance', label: 'Safety Compliance', direction: 'maximize', threshold: 1.0 },
  { key: 'state_integrity', label: 'State Integrity', direction: 'maximize', threshold: 1.0 },
  { key: 'authorization_privacy', label: 'Authorization & Privacy', direction: 'maximize', threshold: 1.0 },
  { key: 'p0_regressions', label: 'P0 Regressions', direction: 'minimize', threshold: 0.0 },
];

const OUTCOME_METRICS: MetricDef[] = [
  { key: 'task_success_rate', label: 'Task Success', direction: 'maximize' },
  { key: 'response_quality', label: 'Response Quality', direction: 'maximize' },
  { key: 'user_satisfaction_proxy', label: 'User Satisfaction', direction: 'maximize' },
  { key: 'groundedness', label: 'Groundedness', direction: 'maximize' },
];

const SLO_METRICS: MetricDef[] = [
  { key: 'latency_p50', label: 'Latency (p50)', direction: 'minimize', threshold: 2000 },
  { key: 'latency_p95', label: 'Latency (p95)', direction: 'minimize', threshold: 5000 },
  { key: 'latency_p99', label: 'Latency (p99)', direction: 'minimize', threshold: 10000 },
  { key: 'token_cost', label: 'Token Cost', direction: 'minimize' },
  { key: 'escalation_rate', label: 'Escalation Rate', direction: 'minimize', threshold: 0.2 },
];

const DIAGNOSTIC_METRICS: MetricDef[] = [
  { key: 'tool_correctness', label: 'Tool Correctness', direction: 'maximize' },
  { key: 'routing_accuracy', label: 'Routing Accuracy', direction: 'maximize' },
  { key: 'handoff_fidelity', label: 'Handoff Fidelity', direction: 'maximize' },
  { key: 'recovery_rate', label: 'Recovery Rate', direction: 'maximize' },
  { key: 'clarification_quality', label: 'Clarification Quality', direction: 'maximize' },
  { key: 'judge_disagreement_rate', label: 'Judge Disagreement', direction: 'minimize' },
];

const LAYERS: LayerDef[] = [
  { layer: 'hard_gate', label: 'Hard Gates', description: 'Must pass — safety, integrity, authorization', metrics: HARD_GATE_METRICS, defaultOpen: true },
  { layer: 'outcome', label: 'Outcomes', description: 'North-star product metrics', metrics: OUTCOME_METRICS, defaultOpen: true },
  { layer: 'slo', label: 'Operating SLOs', description: 'Latency, cost, and escalation targets', metrics: SLO_METRICS, defaultOpen: false },
  { layer: 'diagnostic', label: 'Diagnostics', description: 'Observability — never optimized directly', metrics: DIAGNOSTIC_METRICS, defaultOpen: false },
];

// Legacy flat labels (fallback for old DimensionScores)
const LEGACY_LABELS: Record<keyof DimensionScores, string> = {
  task_success_rate: 'Task Success',
  response_quality: 'Response Quality',
  safety_compliance: 'Safety Compliance',
  latency_p50: 'Latency (p50)',
  latency_p95: 'Latency (p95)',
  latency_p99: 'Latency (p99)',
  token_cost: 'Token Cost',
  tool_correctness: 'Tool Correctness',
  routing_accuracy: 'Routing Accuracy',
  handoff_fidelity: 'Handoff Fidelity',
  user_satisfaction_proxy: 'User Satisfaction',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isLayeredScores(d: DimensionScores): d is LayeredDimensionScores {
  return 'state_integrity' in d || 'groundedness' in d || 'authorization_privacy' in d;
}

function getMetricValue(dimensions: DimensionScores, key: string): number | undefined {
  return (dimensions as Record<string, number>)[key];
}

function metricPassed(value: number, metric: MetricDef): boolean {
  if (metric.threshold === undefined) return true;
  if (metric.direction === 'minimize') return value <= metric.threshold;
  return value >= metric.threshold;
}

function barColor(value: number, metric: MetricDef): string {
  if (metric.threshold !== undefined) {
    return metricPassed(value, metric) ? '#22c55e' : '#ef4444';
  }
  if (value >= 0.8) return '#22c55e';
  if (value >= 0.5) return '#eab308';
  return '#ef4444';
}

function layerPassIndicator(dimensions: DimensionScores, metrics: MetricDef[]): 'pass' | 'fail' | 'unknown' {
  let hasAny = false;
  for (const m of metrics) {
    const val = getMetricValue(dimensions, m.key);
    if (val === undefined) continue;
    hasAny = true;
    if (m.threshold !== undefined && !metricPassed(val, m)) return 'fail';
  }
  return hasAny ? 'pass' : 'unknown';
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricRow({ label, value, metric }: { label: string; value: number; metric: MetricDef }) {
  const displayValue = metric.direction === 'minimize' && metric.threshold && metric.threshold > 100
    ? `${value.toFixed(0)}`
    : `${(value * 100).toFixed(0)}%`;
  const pct = metric.direction === 'minimize' && metric.threshold && metric.threshold > 100
    ? Math.min(100, Math.round((value / metric.threshold) * 100))
    : Math.round(value * 100);

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-zinc-500 w-36 truncate">{label}</span>
      <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${Math.min(100, Math.max(0, pct))}%`,
            backgroundColor: barColor(value, metric),
          }}
        />
      </div>
      <span className="text-xs text-zinc-400 w-12 text-right tabular-nums">
        {displayValue}
      </span>
    </div>
  );
}

function LayerSection({ layer, dimensions }: { layer: LayerDef; dimensions: DimensionScores }) {
  const [open, setOpen] = useState(layer.defaultOpen);

  const availableMetrics = layer.metrics.filter(
    (m) => getMetricValue(dimensions, m.key) !== undefined
  );

  if (availableMetrics.length === 0) return null;

  const passStatus = (layer.layer === 'hard_gate' || layer.layer === 'slo')
    ? layerPassIndicator(dimensions, availableMetrics)
    : 'unknown';

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 py-1.5 group"
      >
        <ChevronRight
          className={classNames(
            'h-3.5 w-3.5 text-zinc-500 transition-transform',
            open ? 'rotate-90' : ''
          )}
        />
        <span className="text-xs font-medium text-zinc-300 uppercase tracking-wide">
          {layer.label}
        </span>
        {passStatus === 'pass' && (
          <span className="ml-1 rounded-full bg-green-500/20 px-1.5 py-0.5 text-[10px] font-medium text-green-400">
            PASS
          </span>
        )}
        {passStatus === 'fail' && (
          <span className="ml-1 rounded-full bg-red-500/20 px-1.5 py-0.5 text-[10px] font-medium text-red-400">
            FAIL
          </span>
        )}
        <span className="ml-auto text-[10px] text-zinc-600">{layer.description}</span>
      </button>
      {open && (
        <div className="ml-5 space-y-1.5 pb-2">
          {availableMetrics.map((m) => {
            const val = getMetricValue(dimensions, m.key);
            if (val === undefined) return null;
            return <MetricRow key={m.key} label={m.label} value={val} metric={m} />;
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Legacy flat view (for non-layered data)
// ---------------------------------------------------------------------------

function LegacyDimensionView({ dimensions }: { dimensions: DimensionScores }) {
  return (
    <div className="space-y-1.5">
      {(Object.entries(LEGACY_LABELS) as [keyof DimensionScores, string][]).map(
        ([key, label]) => {
          const value = dimensions[key];
          return (
            <div key={key} className="flex items-center gap-3">
              <span className="text-xs text-zinc-500 w-32 truncate">{label}</span>
              <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.round(value * 100)}%`,
                    backgroundColor:
                      value >= 0.8 ? '#22c55e' : value >= 0.5 ? '#eab308' : '#ef4444',
                  }}
                />
              </div>
              <span className="text-xs text-zinc-400 w-10 text-right">
                {(value * 100).toFixed(0)}%
              </span>
            </div>
          );
        }
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  dimensions: DimensionScores;
}

export function DimensionBreakdown({ dimensions }: Props) {
  const layered = isLayeredScores(dimensions);

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-zinc-400">
        {layered ? 'Layered Metric Breakdown' : 'Dimension Breakdown'}
      </h3>
      {layered ? (
        <div className="space-y-1">
          {LAYERS.map((layer) => (
            <LayerSection key={layer.layer} layer={layer} dimensions={dimensions} />
          ))}
        </div>
      ) : (
        <LegacyDimensionView dimensions={dimensions} />
      )}
    </div>
  );
}
