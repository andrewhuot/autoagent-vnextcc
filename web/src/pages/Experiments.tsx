import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { ExperimentCardComponent } from '../components/ExperimentCard';
import type { ExperimentCard } from '../lib/types';
import { classNames } from '../lib/utils';

const mockExperiments: ExperimentCard[] = [
  {
    experiment_id: 'exp_001',
    hypothesis: 'Adding routing keywords will reduce routing errors by 15%',
    operator_name: 'routing_edit',
    touched_surfaces: ['routing'],
    risk_class: 'medium',
    status: 'accepted',
    baseline_scores: { quality: 0.72, safety: 1.0, composite: 0.78 },
    candidate_scores: { quality: 0.85, safety: 1.0, composite: 0.88 },
    significance_p_value: 0.012,
    significance_delta: 0.10,
    deployment_policy: 'canary',
    created_at: Date.now() / 1000 - 3600,
  },
  {
    experiment_id: 'exp_002',
    hypothesis: 'Increased tool timeouts will reduce tool failures',
    operator_name: 'tool_description_edit',
    touched_surfaces: ['tool_description'],
    risk_class: 'medium',
    status: 'rejected',
    baseline_scores: { quality: 0.72, composite: 0.78 },
    candidate_scores: { quality: 0.71, composite: 0.76 },
    significance_p_value: 0.45,
    significance_delta: -0.02,
    deployment_policy: 'canary',
    created_at: Date.now() / 1000 - 7200,
  },
  {
    experiment_id: 'exp_003',
    hypothesis: 'Enhanced root prompt improves response quality',
    operator_name: 'instruction_rewrite',
    touched_surfaces: ['instruction'],
    risk_class: 'low',
    status: 'pending',
    baseline_scores: { composite: 0.78 },
    candidate_scores: { composite: 0 },
    significance_p_value: 1.0,
    significance_delta: 0,
    deployment_policy: 'canary',
    created_at: Date.now() / 1000 - 600,
  },
];

type FilterTab = 'all' | 'pending' | 'accepted' | 'rejected';

const tabs: { key: FilterTab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'rejected', label: 'Rejected' },
];

export function Experiments() {
  const [activeTab, setActiveTab] = useState<FilterTab>('all');

  const filtered =
    activeTab === 'all'
      ? mockExperiments
      : mockExperiments.filter((e) => e.status === activeTab);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Experiments"
        description="Reviewable experiment cards with hypothesis, diff, and results"
      />

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

      {/* Experiment cards */}
      {filtered.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {filtered.map((experiment) => (
            <ExperimentCardComponent key={experiment.experiment_id} experiment={experiment} />
          ))}
        </div>
      ) : (
        <div className="flex h-48 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          No experiments match this filter.
        </div>
      )}
    </div>
  );
}
