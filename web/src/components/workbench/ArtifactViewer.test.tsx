import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { useWorkbenchStore } from '../../lib/workbench-store';
import { ArtifactViewer } from './ArtifactViewer';

describe('ArtifactViewer', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
    useWorkbenchStore.getState().hydrate({
      projectId: 'wb-filter',
      projectName: 'Filter Workbench',
      target: 'portable',
      environment: 'draft',
      version: 1,
      artifacts: [
        {
          id: 'art-agent',
          task_id: 'task-role',
          category: 'agent',
          name: 'Agent role',
          summary: 'Agent summary',
          preview: 'AGENT PREVIEW',
          source: 'AGENT SOURCE',
          language: 'markdown',
          created_at: '2026-04-11T00:00:00Z',
          version: 1,
        },
        {
          id: 'art-tool',
          task_id: 'task-tool',
          category: 'tool',
          name: 'flight_status_lookup.py',
          summary: 'Tool summary',
          preview: 'TOOL PREVIEW',
          source: 'TOOL SOURCE',
          language: 'python',
          created_at: '2026-04-11T00:00:00Z',
          version: 1,
        },
      ],
    });
    useWorkbenchStore.getState().setActiveArtifact('art-agent');
  });

  it('switches the active artifact to the selected category', async () => {
    const user = userEvent.setup();
    render(<ArtifactViewer />);

    expect(screen.getByText('AGENT PREVIEW')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Tools/ }));

    expect(screen.getByText('flight_status_lookup.py')).toBeInTheDocument();
    expect(screen.queryByText('AGENT PREVIEW')).not.toBeInTheDocument();
  });

  it('groups less common artifact categories under Other', async () => {
    const user = userEvent.setup();
    useWorkbenchStore.setState({
      artifacts: [
        ...useWorkbenchStore.getState().artifacts,
        {
          id: 'art-callback',
          task_id: 'task-callback',
          category: 'callback',
          name: 'After response callback',
          summary: 'Callback summary',
          preview: 'CALLBACK PREVIEW',
          source: 'CALLBACK SOURCE',
          language: 'python',
          created_at: '2026-04-11T00:00:00Z',
          version: 1,
        },
      ],
    });

    render(<ArtifactViewer />);
    await user.click(screen.getByRole('button', { name: /Other/ }));

    expect(screen.getByText('After response callback')).toBeInTheDocument();
    expect(screen.getByText('CALLBACK')).toBeInTheDocument();
    expect(screen.getByText('PREVIEW')).toBeInTheDocument();
  });

  it('does not show the Diff tab when there are no previous version artifacts', () => {
    render(<ArtifactViewer />);
    expect(screen.queryByRole('button', { name: 'Diff' })).not.toBeInTheDocument();
  });

  it('shows version badge when iterationCount > 0', () => {
    useWorkbenchStore.setState({ iterationCount: 2 });
    render(<ArtifactViewer />);
    // Two artifacts => sub-navigation visible, each should have a "v3" badge
    expect(screen.getAllByText('v3').length).toBeGreaterThanOrEqual(1);
  });

  it('shows the Diff tab when previousVersionArtifacts and diffTargetVersion are set', () => {
    useWorkbenchStore.setState({
      previousVersionArtifacts: [
        {
          id: 'art-agent-old',
          task_id: 'task-role',
          category: 'agent',
          name: 'Agent role',
          summary: 'Old summary',
          preview: 'OLD PREVIEW',
          source: 'OLD SOURCE',
          language: 'markdown',
          created_at: '2026-04-10T00:00:00Z',
          version: 1,
        },
      ],
      diffTargetVersion: 1,
    });
    render(<ArtifactViewer />);
    expect(screen.getByRole('button', { name: 'Diff' })).toBeInTheDocument();
  });

  it('renders the diff view with added and removed lines', async () => {
    const user = userEvent.setup();
    useWorkbenchStore.setState({
      previousVersionArtifacts: [
        {
          id: 'art-agent-old',
          task_id: 'task-role',
          category: 'agent',
          name: 'Agent role',
          summary: 'Old summary',
          preview: 'line one\nold line',
          source: 'line one\nold line',
          language: 'python',
          created_at: '2026-04-10T00:00:00Z',
          version: 1,
        },
      ],
      diffTargetVersion: 1,
      artifacts: [
        {
          id: 'art-agent',
          task_id: 'task-role',
          category: 'agent',
          name: 'Agent role',
          summary: 'Agent summary',
          preview: 'line one\nnew line',
          source: 'line one\nnew line',
          language: 'python',
          created_at: '2026-04-11T00:00:00Z',
          version: 2,
        },
      ],
      activeArtifactId: 'art-agent',
    });
    render(<ArtifactViewer />);
    await user.click(screen.getByRole('button', { name: 'Diff' }));
    // The diff should show the removed old line and added new line
    expect(screen.getByText('old line')).toBeInTheDocument();
    expect(screen.getByText('new line')).toBeInTheDocument();
  });

  it('renders review gate and handoff details in the activity tab', async () => {
    const user = userEvent.setup();
    useWorkbenchStore.setState({
      activeWorkspaceTab: 'activity',
      presentation: {
        run_id: 'run-1',
        version: 2,
        summary: 'Built 3 canonical changes.',
        artifact_ids: ['art-agent'],
        active_artifact_id: 'art-agent',
        generated_outputs: ['agent.py'],
        validation_status: 'passed',
        next_actions: ['Review candidate before promotion.'],
        review_gate: {
          status: 'review_required',
          promotion_status: 'draft',
          requires_human_review: true,
          blocking_reasons: [],
          checks: [
            {
              name: 'human_review',
              status: 'required',
              required: true,
              detail: 'Human review is required before promotion.',
            },
          ],
        },
        handoff: {
          project_id: 'wb-filter',
          run_id: 'run-1',
          turn_id: 'turn-1',
          version: 2,
          review_gate_status: 'review_required',
          active_artifact_id: 'art-agent',
          last_event_sequence: 12,
          next_operator_action: 'Review candidate and run evals before promotion.',
          resume_prompt: 'Resume Workbench project wb-filter at Draft v2.',
        },
      },
    });

    render(<ArtifactViewer />);
    await user.click(screen.getByRole('button', { name: 'Activity' }));

    expect(screen.getByText('Review gate')).toBeInTheDocument();
    expect(screen.getByText('review_required')).toBeInTheDocument();
    expect(screen.getByText('human_review: required')).toBeInTheDocument();
    expect(screen.getByText('Session handoff')).toBeInTheDocument();
    expect(screen.getByText('Resume Workbench project wb-filter at Draft v2.')).toBeInTheDocument();
  });

  it('renders durable handoff and evidence details without presentation state', async () => {
    const user = userEvent.setup();
    useWorkbenchStore.setState({
      activeWorkspaceTab: 'activity',
      presentation: null,
      activeRun: {
        run_id: 'run-2',
        project_id: 'wb-filter',
        brief: 'Build',
        target: 'portable',
        environment: 'draft',
        status: 'completed',
        phase: 'presenting',
        started_version: 1,
        completed_version: 2,
        created_at: '2026-04-11T00:00:00Z',
        completed_at: '2026-04-11T00:00:01Z',
        error: null,
        events: [],
        messages: [],
        validation: null,
        presentation: null,
        evidence_summary: {
          structural_status: 'passed',
          improvement_status: 'changed',
          correction_status: 'corrected',
          operations_applied: 2,
        },
        handoff: {
          run_id: 'run-2',
          next_action: 'Review corrected compatibility evidence.',
          last_event: { sequence: 8, event: 'run.completed' },
          progress: { total_tasks: 2, completed_tasks: 2 },
          verification: { status: 'passed' },
        },
      },
    });

    render(<ArtifactViewer />);
    await user.click(screen.getByRole('button', { name: 'Activity' }));

    expect(screen.getByText('Evidence status')).toBeInTheDocument();
    expect(screen.getByText('improvement_evidence: changed')).toBeInTheDocument();
    expect(screen.getByText('correction: corrected')).toBeInTheDocument();
    expect(screen.getByText('Session handoff')).toBeInTheDocument();
    expect(screen.getByText('Review corrected compatibility evidence.')).toBeInTheDocument();
  });
});
