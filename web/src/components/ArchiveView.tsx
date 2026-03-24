import type { ArchiveEntry, ArchiveRole } from '../lib/types';
import { classNames } from '../lib/utils';

interface Props {
  entries: ArchiveEntry[];
}

const ROLE_ORDER: ArchiveRole[] = [
  'incumbent',
  'quality_leader',
  'cost_leader',
  'latency_leader',
  'safety_leader',
  'cluster_specialist',
];

const ROLE_STYLES: Record<ArchiveRole, { bg: string; text: string; border: string; label: string }> = {
  quality_leader: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200', label: 'Quality Leader' },
  cost_leader: { bg: 'bg-green-50', text: 'text-green-700', border: 'border-green-200', label: 'Cost Leader' },
  latency_leader: { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200', label: 'Latency Leader' },
  safety_leader: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200', label: 'Safety Leader' },
  cluster_specialist: { bg: 'bg-gray-50', text: 'text-gray-700', border: 'border-gray-200', label: 'Cluster Specialist' },
  incumbent: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', label: 'Incumbent' },
};

function groupByRole(entries: ArchiveEntry[]): Map<ArchiveRole, ArchiveEntry[]> {
  const map = new Map<ArchiveRole, ArchiveEntry[]>();
  for (const entry of entries) {
    const group = map.get(entry.role) ?? [];
    group.push(entry);
    map.set(entry.role, group);
  }
  return map;
}

function ScoreChips({ scores }: { scores: Record<string, number> }) {
  const entries = Object.entries(scores);
  if (entries.length === 0) return <span className="text-[11px] text-gray-400">No scores</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([key, val]) => (
        <span
          key={key}
          className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] tabular-nums text-gray-600"
        >
          {key}: {typeof val === 'number' ? val.toFixed(2) : String(val)}
        </span>
      ))}
    </div>
  );
}

function ObjectiveVector({ vector }: { vector: number[] }) {
  if (vector.length === 0) return null;
  return (
    <span className="text-[10px] text-gray-400 font-mono">
      [{vector.map((v) => v.toFixed(2)).join(', ')}]
    </span>
  );
}

export function ArchiveView({ entries }: Props) {
  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
        No archive entries yet.
      </div>
    );
  }

  const grouped = groupByRole(entries);

  return (
    <div className="space-y-4">
      {ROLE_ORDER.map((role) => {
        const group = grouped.get(role);
        if (!group || group.length === 0) return null;
        const style = ROLE_STYLES[role];
        const isIncumbent = role === 'incumbent';

        return (
          <div key={role}>
            <div className="flex items-center gap-2 mb-2">
              <span className={classNames('rounded-md px-2 py-0.5 text-[11px] font-medium', style.bg, style.text)}>
                {style.label}
              </span>
              <span className="text-[11px] text-gray-400">{group.length} {group.length === 1 ? 'entry' : 'entries'}</span>
            </div>

            <div className="overflow-hidden rounded-lg border border-gray-200">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500">Candidate</th>
                    <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500">Experiment</th>
                    <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500">Scores</th>
                    <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500">Objective</th>
                  </tr>
                </thead>
                <tbody>
                  {group.map((entry, idx) => (
                    <tr
                      key={entry.entry_id}
                      className={classNames(
                        'border-b border-gray-100 last:border-b-0',
                        isIncumbent ? 'bg-amber-50/40' : idx % 2 === 1 ? 'bg-gray-50/40' : ''
                      )}
                    >
                      <td className="px-3 py-2 font-mono text-xs text-gray-700">{entry.candidate_id || entry.entry_id.slice(0, 8)}</td>
                      <td className="px-3 py-2 font-mono text-xs text-gray-500">{entry.experiment_id || '-'}</td>
                      <td className="px-3 py-2"><ScoreChips scores={entry.scores} /></td>
                      <td className="px-3 py-2"><ObjectiveVector vector={entry.objective_vector} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
