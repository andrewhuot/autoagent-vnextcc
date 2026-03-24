import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { ExperimentCardComponent } from '../components/ExperimentCard';
import { ParetoFrontierView } from '../components/ParetoFrontierView';
import { ArchiveView } from '../components/ArchiveView';
import { JudgeCalibrationView } from '../components/JudgeCalibrationView';
import { useExperiments, useParetoFrontier, useArchiveEntries, useJudgeCalibration } from '../lib/api';
import { classNames } from '../lib/utils';

type FilterTab = 'all' | 'pending' | 'accepted' | 'rejected';

const tabs: { key: FilterTab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'rejected', label: 'Rejected' },
];

export function Experiments() {
  const [activeTab, setActiveTab] = useState<FilterTab>('all');

  const statusParam = activeTab === 'all' ? undefined : activeTab;
  const { data: experiments = [], isLoading, isError } = useExperiments(statusParam);
  const { data: frontier } = useParetoFrontier();
  const { data: archiveEntries = [] } = useArchiveEntries();
  const { data: calibration } = useJudgeCalibration();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Experiments"
        description="Reviewable experiment cards with hypothesis, diff, and results"
      />

      {/* Archive section */}
      {archiveEntries.length > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-gray-900">
              Elite Archive ({archiveEntries.length} entries)
            </summary>
            <div className="mt-4">
              <ArchiveView entries={archiveEntries} />
            </div>
          </details>
        </section>
      )}

      {frontier && frontier.candidates.length > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-gray-900">
              Pareto Frontier ({frontier.frontier_size} candidates)
            </summary>
            <div className="mt-4">
              <ParetoFrontierView frontier={frontier} />
            </div>
          </details>
        </section>
      )}

      {/* Judge calibration section */}
      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <details>
          <summary className="cursor-pointer text-sm font-semibold text-gray-900">
            Judge Calibration
          </summary>
          <div className="mt-4">
            <JudgeCalibrationView calibration={calibration} />
          </div>
        </details>
      </section>

      {/* Filter tabs */}
      <div className="flex gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={classNames(
              'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              activeTab === tab.key
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Loading / error states */}
      {isLoading && (
        <div className="flex h-48 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading experiments...
        </div>
      )}
      {isError && (
        <div className="flex h-48 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load experiments.
        </div>
      )}

      {/* Experiment cards */}
      {!isLoading && !isError && (
        experiments.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {experiments.map((experiment) => (
              <ExperimentCardComponent key={experiment.experiment_id} experiment={experiment} />
            ))}
          </div>
        ) : (
          <div className="flex h-48 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
            No experiments match this filter.
          </div>
        )
      )}
    </div>
  );
}
