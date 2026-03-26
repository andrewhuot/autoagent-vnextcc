import { AlertTriangle, CheckCircle, Info } from 'lucide-react';
import { classNames } from '../../lib/utils';

export interface DiffData {
  file_path: string;
  before: string;
  after: string;
  change_description: string;
  risk_level: 'low' | 'medium' | 'high';
  expected_impact?: {
    success_rate_delta?: number;
    latency_delta_ms?: number;
    cost_delta?: number;
  };
}

interface DiffCardProps {
  data: DiffData;
}

export function DiffCard({ data }: DiffCardProps) {
  const riskColor = (risk: string): string => {
    if (risk === 'high') return 'bg-red-50 text-red-700 border-red-200';
    if (risk === 'medium') return 'bg-amber-50 text-amber-700 border-amber-200';
    return 'bg-green-50 text-green-700 border-green-200';
  };

  const riskIcon = (risk: string) => {
    if (risk === 'high') return <AlertTriangle className="h-4 w-4" />;
    if (risk === 'medium') return <Info className="h-4 w-4" />;
    return <CheckCircle className="h-4 w-4" />;
  };

  const renderDiff = () => {
    const beforeLines = data.before.split('\n');
    const afterLines = data.after.split('\n');

    // Simple line-by-line diff visualization
    const maxLines = Math.max(beforeLines.length, afterLines.length);
    const rows: Array<{ before: string; after: string; type: 'same' | 'changed' | 'added' | 'removed' }> = [];

    for (let i = 0; i < maxLines; i++) {
      const beforeLine = beforeLines[i];
      const afterLine = afterLines[i];

      if (beforeLine === afterLine) {
        rows.push({ before: beforeLine || '', after: afterLine || '', type: 'same' });
      } else if (!beforeLine && afterLine) {
        rows.push({ before: '', after: afterLine, type: 'added' });
      } else if (beforeLine && !afterLine) {
        rows.push({ before: beforeLine, after: '', type: 'removed' });
      } else {
        rows.push({ before: beforeLine || '', after: afterLine || '', type: 'changed' });
      }
    }

    return rows;
  };

  const diffRows = renderDiff();

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-200 bg-gray-50 px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-gray-900">Configuration Change</h3>
              <span className={classNames('inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium', riskColor(data.risk_level))}>
                {riskIcon(data.risk_level)}
                {data.risk_level} risk
              </span>
            </div>
            <p className="mt-1 text-xs font-mono text-gray-500">{data.file_path}</p>
            <p className="mt-2 text-sm text-gray-600">{data.change_description}</p>
          </div>
        </div>
      </div>

      {/* Diff View */}
      <div className="border-b border-gray-200">
        <div className="grid grid-cols-2 border-b border-gray-200 bg-gray-50">
          <div className="px-4 py-2 text-xs font-medium text-gray-500 border-r border-gray-200">
            Before
          </div>
          <div className="px-4 py-2 text-xs font-medium text-gray-500">
            After
          </div>
        </div>
        <div className="max-h-96 overflow-auto">
          <div className="grid grid-cols-2 font-mono text-xs">
            <div className="border-r border-gray-200">
              {diffRows.map((row, i) => (
                <div
                  key={`before-${i}`}
                  className={classNames(
                    'px-4 py-1 min-h-[1.5rem]',
                    row.type === 'removed' && 'bg-red-50 text-red-800',
                    row.type === 'changed' && 'bg-red-50 text-red-800',
                    row.type === 'added' && 'invisible'
                  )}
                >
                  <span className="whitespace-pre">
                    {row.type === 'removed' || row.type === 'changed' ? `- ${row.before}` : `  ${row.before}`}
                  </span>
                </div>
              ))}
            </div>
            <div>
              {diffRows.map((row, i) => (
                <div
                  key={`after-${i}`}
                  className={classNames(
                    'px-4 py-1 min-h-[1.5rem]',
                    row.type === 'added' && 'bg-green-50 text-green-800',
                    row.type === 'changed' && 'bg-green-50 text-green-800',
                    row.type === 'removed' && 'invisible'
                  )}
                >
                  <span className="whitespace-pre">
                    {row.type === 'added' || row.type === 'changed' ? `+ ${row.after}` : `  ${row.after}`}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Expected Impact */}
      {data.expected_impact && (
        <div className="bg-gray-50 px-6 py-4">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Expected Impact</p>
          <div className="mt-3 grid grid-cols-3 gap-4">
            {data.expected_impact.success_rate_delta !== undefined && (
              <div>
                <p className="text-xs text-gray-500">Success Rate</p>
                <p className={classNames(
                  'mt-1 text-lg font-semibold tabular-nums',
                  data.expected_impact.success_rate_delta > 0 ? 'text-green-600' : 'text-red-600'
                )}>
                  {data.expected_impact.success_rate_delta > 0 ? '+' : ''}
                  {data.expected_impact.success_rate_delta.toFixed(1)}%
                </p>
              </div>
            )}
            {data.expected_impact.latency_delta_ms !== undefined && (
              <div>
                <p className="text-xs text-gray-500">Latency</p>
                <p className={classNames(
                  'mt-1 text-lg font-semibold tabular-nums',
                  data.expected_impact.latency_delta_ms < 0 ? 'text-green-600' : 'text-red-600'
                )}>
                  {data.expected_impact.latency_delta_ms > 0 ? '+' : ''}
                  {data.expected_impact.latency_delta_ms}ms
                </p>
              </div>
            )}
            {data.expected_impact.cost_delta !== undefined && (
              <div>
                <p className="text-xs text-gray-500">Cost</p>
                <p className={classNames(
                  'mt-1 text-lg font-semibold tabular-nums',
                  data.expected_impact.cost_delta < 0 ? 'text-green-600' : 'text-red-600'
                )}>
                  {data.expected_impact.cost_delta > 0 ? '+' : ''}
                  ${Math.abs(data.expected_impact.cost_delta).toFixed(3)}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
