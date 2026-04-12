import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReflectionCard } from './ReflectionCard';
import type { ReflectionEntry } from '../../lib/workbench-api';

function makeReflection(overrides: Partial<ReflectionEntry> = {}): ReflectionEntry {
  return {
    id: 'reflect-1',
    taskId: 'task-root',
    qualityScore: 82,
    suggestions: ['Add error handling', 'Write a unit test'],
    timestamp: 1_000_000,
    ...overrides,
  };
}

describe('ReflectionCard', () => {
  it('renders the quality score', () => {
    render(
      <div className="workbench-root">
        <ReflectionCard reflection={makeReflection()} onApplySuggestion={() => {}} />
      </div>
    );
    // Score is rendered inside the SVG text element as a number.
    expect(screen.getByText('82')).toBeInTheDocument();
  });

  it('shows all suggestion texts', () => {
    render(
      <div className="workbench-root">
        <ReflectionCard reflection={makeReflection()} onApplySuggestion={() => {}} />
      </div>
    );
    expect(screen.getByText('Add error handling')).toBeInTheDocument();
    expect(screen.getByText('Write a unit test')).toBeInTheDocument();
  });

  it('renders an Apply button per suggestion', () => {
    render(
      <div className="workbench-root">
        <ReflectionCard reflection={makeReflection()} onApplySuggestion={() => {}} />
      </div>
    );
    const buttons = screen.getAllByRole('button', { name: 'Apply' });
    expect(buttons).toHaveLength(2);
  });

  it('calls onApplySuggestion with the suggestion text when Apply is clicked', async () => {
    const handler = vi.fn();
    const user = userEvent.setup();
    render(
      <div className="workbench-root">
        <ReflectionCard
          reflection={makeReflection({ suggestions: ['Add error handling'] })}
          onApplySuggestion={handler}
        />
      </div>
    );
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(handler).toHaveBeenCalledOnce();
    expect(handler).toHaveBeenCalledWith('Add error handling');
  });

  it('shows a "no suggestions" message when the list is empty', () => {
    render(
      <div className="workbench-root">
        <ReflectionCard
          reflection={makeReflection({ suggestions: [] })}
          onApplySuggestion={() => {}}
        />
      </div>
    );
    expect(screen.getByText(/no suggestions/i)).toBeInTheDocument();
  });

  it('has a data-testid for targeting in integration tests', () => {
    const { container } = render(
      <div className="workbench-root">
        <ReflectionCard reflection={makeReflection()} onApplySuggestion={() => {}} />
      </div>
    );
    expect(container.querySelector('[data-testid="reflection-card"]')).toBeTruthy();
  });
});
