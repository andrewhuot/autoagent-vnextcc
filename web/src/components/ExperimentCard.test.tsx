import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import { ExperimentCardComponent } from './ExperimentCard';
import type { ExperimentCard } from '../lib/types';

function renderCard(experiment: ExperimentCard) {
  render(
    <MemoryRouter>
      <ExperimentCardComponent experiment={experiment} />
    </MemoryRouter>
  );
}

function buildExperiment(status: ExperimentCard['status']): ExperimentCard {
  return {
    experiment_id: 'exp_12345678',
    hypothesis: 'Tighten routing for billing transfers',
    operator_name: 'routing_rule',
    touched_surfaces: ['router.billing'],
    risk_class: 'medium',
    status,
    baseline_scores: { composite: 0.62, quality: 0.58, safety: 0.99 },
    candidate_scores: { composite: 0.71, quality: 0.67, safety: 0.99 },
    significance_p_value: 0.03,
    significance_delta: 0.09,
    deployment_policy: 'human_review',
    created_at: 1_700_000_000,
  };
}

describe('ExperimentCardComponent', () => {
  it('guides pending experiments into the review queue', () => {
    renderCard(buildExperiment('pending'));

    const reviewLink = screen.getByRole('link', { name: 'Approve or reject' });
    expect(reviewLink).toHaveAttribute('href', '/improvements?tab=review');
  });

  it('guides accepted experiments into deploy monitoring', () => {
    renderCard(buildExperiment('accepted'));

    const deployLink = screen.getByRole('link', { name: 'Monitor deploy' });
    expect(deployLink).toHaveAttribute('href', '/deploy');
  });
});
