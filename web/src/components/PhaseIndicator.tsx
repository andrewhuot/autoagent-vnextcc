interface PhaseIndicatorProps {
  activePhase: 'diagnose' | 'propose' | 'evaluate' | 'decide' | null;
  completedPhases: Set<string>;
}

const PHASES = [
  { id: 'diagnose', label: 'Diagnose' },
  { id: 'propose', label: 'Propose' },
  { id: 'evaluate', label: 'Evaluate' },
  { id: 'decide', label: 'Decide' },
] as const;

export function PhaseIndicator({ activePhase, completedPhases }: PhaseIndicatorProps) {
  const getPhaseState = (phaseId: string): 'pending' | 'active' | 'complete' => {
    if (completedPhases.has(phaseId)) return 'complete';
    if (activePhase === phaseId) return 'active';
    return 'pending';
  };

  return (
    <div className="flex items-center justify-center gap-4 py-8">
      {PHASES.map((phase, index) => {
        const state = getPhaseState(phase.id);

        return (
          <div key={phase.id} className="flex items-center gap-4">
            {/* Phase Box */}
            <div
              className={`
                relative flex flex-col items-center justify-center
                w-32 h-24 rounded-lg border-2 transition-all duration-300
                ${
                  state === 'pending'
                    ? 'bg-gray-50 border-gray-300 text-gray-500'
                    : state === 'active'
                    ? 'bg-blue-50 border-blue-500 text-blue-700 phase-pulse'
                    : 'bg-green-50 border-green-500 text-green-700'
                }
              `}
            >
              {/* Icon */}
              <div className="mb-2">
                {state === 'pending' && (
                  <div className="w-6 h-6 rounded-full border-2 border-gray-400" />
                )}
                {state === 'active' && (
                  <div className="w-6 h-6 rounded-full bg-blue-500 border-2 border-blue-600" />
                )}
                {state === 'complete' && (
                  <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </div>

              {/* Label */}
              <div className="text-sm font-medium">{phase.label}</div>
            </div>

            {/* Arrow between phases */}
            {index < PHASES.length - 1 && (
              <div className="text-2xl text-gray-400">→</div>
            )}
          </div>
        );
      })}

      <style>{`
        @keyframes phase-pulse {
          0%, 100% {
            transform: scale(1);
            opacity: 1;
          }
          50% {
            transform: scale(1.05);
            opacity: 0.9;
          }
        }

        .phase-pulse {
          animation: phase-pulse 2s ease-in-out infinite;
        }
      `}</style>
    </div>
  );
}
