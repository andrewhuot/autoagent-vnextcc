import { AlertTriangle } from 'lucide-react';
import type { JudgeCalibration } from '../lib/types';

interface Props {
  calibration?: JudgeCalibration;
}

interface CalibrationMetric {
  key: keyof JudgeCalibration;
  label: string;
  format: (v: number) => string;
  direction: 'higher-better' | 'lower-better';
}

const METRICS: CalibrationMetric[] = [
  { key: 'agreement_rate', label: 'Agreement Rate', format: (v) => `${(v * 100).toFixed(1)}%`, direction: 'higher-better' },
  { key: 'drift', label: 'Drift', format: (v) => v.toFixed(3), direction: 'lower-better' },
  { key: 'position_bias', label: 'Position Bias', format: (v) => v.toFixed(3), direction: 'lower-better' },
  { key: 'verbosity_bias', label: 'Verbosity Bias', format: (v) => v.toFixed(3), direction: 'lower-better' },
  { key: 'disagreement_rate', label: 'Disagreement Rate', format: (v) => `${(v * 100).toFixed(1)}%`, direction: 'lower-better' },
];

function metricColor(metric: CalibrationMetric, value: number): string {
  if (metric.direction === 'higher-better') {
    if (value >= 0.8) return 'text-green-600';
    if (value >= 0.5) return 'text-amber-600';
    return 'text-red-600';
  }
  // lower-better
  if (value <= 0.05) return 'text-green-600';
  if (value <= 0.1) return 'text-amber-600';
  return 'text-red-600';
}

export function JudgeCalibrationView({ calibration }: Props) {
  if (!calibration) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
        No judge calibration data available.
      </div>
    );
  }

  const lowAgreement = calibration.agreement_rate < 0.7;
  const highDrift = calibration.drift > 0.1;

  return (
    <div className="space-y-3">
      {(lowAgreement || highDrift) && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" />
          <div className="text-xs text-amber-800">
            {lowAgreement && (
              <p>Judge agreement rate is below 70% ({(calibration.agreement_rate * 100).toFixed(1)}%). Consider recalibrating judges.</p>
            )}
            {highDrift && (
              <p>Judge drift exceeds 0.1 threshold ({calibration.drift.toFixed(3)}). Scores may be unreliable.</p>
            )}
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {METRICS.map((metric) => {
          const value = calibration[metric.key];
          return (
            <div key={metric.key} className="rounded-lg border border-gray-200 bg-white p-3">
              <p className="text-xs text-gray-500">{metric.label}</p>
              <p className={`mt-1 text-lg font-semibold tabular-nums ${metricColor(metric, value)}`}>
                {metric.format(value)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
