import { Check, Loader2, ChevronRight, Circle } from 'lucide-react';
import { useState } from 'react';
import { classNames } from '../../lib/utils';

interface ProgressStep {
  id: string;
  label: string;
  status: 'completed' | 'in-progress' | 'pending' | 'failed';
  details?: string | string[];
  timestamp?: number;
}

export interface ProgressData {
  title: string;
  steps: ProgressStep[];
  overall_progress: number;
  current_step_index?: number;
}

interface ProgressCardProps {
  data: ProgressData;
}

export function ProgressCard({ data }: ProgressCardProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());

  const toggleStep = (stepId: string) => {
    const newExpanded = new Set(expandedSteps);
    if (newExpanded.has(stepId)) {
      newExpanded.delete(stepId);
    } else {
      newExpanded.add(stepId);
    }
    setExpandedSteps(newExpanded);
  };

  const getStepIcon = (step: ProgressStep) => {
    switch (step.status) {
      case 'completed':
        return <Check className="h-4 w-4 text-green-600" />;
      case 'in-progress':
        return <Loader2 className="h-4 w-4 text-blue-600 animate-spin" />;
      case 'failed':
        return <Circle className="h-4 w-4 text-red-600" />;
      default:
        return <Circle className="h-4 w-4 text-gray-300" />;
    }
  };

  const getStepColor = (step: ProgressStep): string => {
    switch (step.status) {
      case 'completed':
        return 'text-green-700';
      case 'in-progress':
        return 'text-blue-700 font-medium';
      case 'failed':
        return 'text-red-700';
      default:
        return 'text-gray-500';
    }
  };

  const getStepBg = (step: ProgressStep): string => {
    switch (step.status) {
      case 'completed':
        return 'bg-green-50';
      case 'in-progress':
        return 'bg-blue-50';
      case 'failed':
        return 'bg-red-50';
      default:
        return '';
    }
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h3 className="text-sm font-medium text-gray-900">{data.title}</h3>
          <p className="mt-1 text-xs text-gray-500">
            {data.steps.filter(s => s.status === 'completed').length} of {data.steps.length} steps completed
          </p>
        </div>
        <div className="rounded-lg bg-gray-100 px-3 py-1.5">
          <span className="text-lg font-bold tabular-nums text-gray-900">
            {data.overall_progress.toFixed(0)}%
          </span>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-blue-600 transition-all duration-500"
          style={{ width: `${data.overall_progress}%` }}
        />
      </div>

      {/* Steps List */}
      <div className="mt-6 space-y-2">
        {data.steps.map((step, idx) => {
          const isExpanded = expandedSteps.has(step.id);
          const hasDetails = step.details && (
            typeof step.details === 'string' ? step.details.length > 0 : step.details.length > 0
          );

          return (
            <div
              key={step.id}
              className={classNames(
                'rounded-lg border border-gray-200 overflow-hidden transition-colors',
                getStepBg(step)
              )}
            >
              <button
                onClick={() => hasDetails && toggleStep(step.id)}
                disabled={!hasDetails}
                className={classNames(
                  'w-full flex items-center gap-3 px-4 py-3 text-left transition-colors',
                  hasDetails && 'hover:bg-white/50 cursor-pointer',
                  !hasDetails && 'cursor-default'
                )}
              >
                {/* Status Icon */}
                <div className="flex-shrink-0">
                  {getStepIcon(step)}
                </div>

                {/* Step Number */}
                <div className="flex-shrink-0 text-xs font-medium text-gray-400">
                  {idx + 1}.
                </div>

                {/* Step Label */}
                <div className={classNames('flex-1 text-sm', getStepColor(step))}>
                  {step.label}
                </div>

                {/* Expand Icon */}
                {hasDetails && (
                  <ChevronRight
                    className={classNames(
                      'h-4 w-4 text-gray-400 transition-transform',
                      isExpanded && 'rotate-90'
                    )}
                  />
                )}
              </button>

              {/* Details */}
              {isExpanded && hasDetails && step.details && (
                <div className="border-t border-gray-200 bg-white/50 px-4 py-3">
                  {typeof step.details === 'string' ? (
                    <p className="text-xs text-gray-600">{step.details}</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {step.details.map((detail, detailIdx) => (
                        <li key={detailIdx} className="flex items-start gap-2 text-xs text-gray-600">
                          <span className="text-gray-400">•</span>
                          <span>{detail}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Current Step Indicator */}
      {data.current_step_index !== undefined && data.current_step_index < data.steps.length && (
        <div className="mt-4 border-t border-gray-100 pt-4">
          <p className="text-xs text-gray-500">
            Currently working on:{' '}
            <span className="font-medium text-gray-900">
              {data.steps[data.current_step_index].label}
            </span>
          </p>
        </div>
      )}
    </div>
  );
}
