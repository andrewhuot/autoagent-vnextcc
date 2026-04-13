import { useState } from 'react';
import { PhaseIndicator } from '../components/PhaseIndicator';
import { LiveCycleCard } from '../components/LiveCycleCard';
import { ScoreChart } from '../components/ScoreChart';
import { Confetti } from '../components/Confetti';

type Phase = 'diagnose' | 'propose' | 'evaluate' | 'decide';

interface LiveOptimizeProps {
  activeAgentName?: string | null;
  requireSelectedAgent?: boolean;
}

interface CycleResult {
  cycle: number;
  changeDescription: string;
  scoreDelta: number;
  accepted: boolean;
  bestScore: number;
}

interface ScorePoint {
  label: string;
  score: number;
}

export function LiveOptimize({
  activeAgentName = null,
  requireSelectedAgent = false,
}: LiveOptimizeProps) {
  const [isRunning, setIsRunning] = useState(false);
  const [currentPhase, setCurrentPhase] = useState<Phase | null>(null);
  const [completedPhases, setCompletedPhases] = useState<Set<string>>(new Set());
  const [completedCycles, setCompletedCycles] = useState<CycleResult[]>([]);
  const [scoreData, setScoreData] = useState<ScorePoint[]>([]);
  const [showConfetti, setShowConfetti] = useState(false);
  const [totalCycles, setTotalCycles] = useState(3);
  const canStart = !requireSelectedAgent || Boolean(activeAgentName);
  const subtitle = requireSelectedAgent
    ? activeAgentName
      ? `Preview the streaming optimization loop for ${activeAgentName}. This tab uses simulated events so you can understand the phases before running the real optimizer.`
      : 'Select an agent above to start the live simulation.'
    : 'Preview the optimization loop with a simulated streaming walkthrough.';

  const startOptimization = () => {
    if (!canStart) {
      return;
    }

    // Reset state
    setIsRunning(true);
    setCurrentPhase(null);
    setCompletedPhases(new Set());
    setCompletedCycles([]);
    setScoreData([]);
    setShowConfetti(false);

    // This page is the simulated walkthrough; explicit opt-in so the real
    // stream endpoint 400s any caller that forgets to pass a task_id.
    const eventSource = new EventSource(
      `/api/optimize/stream?simulated=1&cycles=${totalCycles}&mode=standard`
    );

    eventSource.addEventListener('cycle_start', () => {
      setCurrentPhase('diagnose');
      setCompletedPhases(new Set());
    });

    eventSource.addEventListener('diagnosis', () => {
      setCompletedPhases(prev => new Set([...prev, 'diagnose']));
      setCurrentPhase('propose');
    });

    eventSource.addEventListener('proposal', () => {
      setCompletedPhases(prev => new Set([...prev, 'propose']));
      setCurrentPhase('evaluate');
    });

    eventSource.addEventListener('evaluation', () => {
      setCompletedPhases(prev => new Set([...prev, 'evaluate']));
      setCurrentPhase('decide');
    });

    eventSource.addEventListener('decision', () => {
      setCompletedPhases(prev => new Set([...prev, 'decide']));
    });

    eventSource.addEventListener('cycle_complete', (e) => {
      const data = JSON.parse(e.data);
      const newCycle: CycleResult = {
        cycle: data.cycle,
        changeDescription: data.change_description,
        scoreDelta: data.score_delta,
        accepted: data.accepted,
        bestScore: data.best_score,
      };

      setCompletedCycles(prev => [newCycle, ...prev]); // Newest first
      setScoreData(prev => [
        ...prev,
        { label: `Cycle ${data.cycle}`, score: data.best_score * 100 }
      ]);
      setCurrentPhase(null);
      setCompletedPhases(new Set());
    });

    eventSource.addEventListener('optimization_complete', () => {
      setIsRunning(false);
      setCurrentPhase(null);

      // Trigger confetti on completion
      setShowConfetti(true);
      setTimeout(() => setShowConfetti(false), 2500);

      eventSource.close();
    });

    eventSource.onerror = (error) => {
      console.error('SSE Error:', error);
      setIsRunning(false);
      setCurrentPhase(null);
      eventSource.close();
    };
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <Confetti trigger={showConfetti} />

      <section className="mb-6 rounded-2xl border border-sky-100 bg-sky-50/70 px-5 py-4 shadow-sm shadow-sky-100/60">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <span className="inline-flex rounded-full border border-sky-200 bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-800">
              Simulation preview
            </span>
            <p className="mt-3 text-sm leading-relaxed text-sky-950">{subtitle}</p>
          </div>
          {requireSelectedAgent ? (
            <div className="rounded-2xl border border-white bg-white/90 px-4 py-4 shadow-sm">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">Selected agent</p>
              <p className="mt-2 text-sm font-semibold text-gray-900">
                {activeAgentName ?? 'Choose an agent above'}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {activeAgentName
                  ? 'Keep this same agent selected when you move back to the Run tab.'
                  : 'The live simulation stays disabled until the main Optimize workflow has an active agent.'}
              </p>
            </div>
          ) : null}
        </div>
      </section>

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Live Optimization</h1>
            <p className="text-sm text-gray-500 mt-1">
              {requireSelectedAgent ? 'Watch the live demo without losing your main workflow context' : 'Watch the optimization loop play out in real-time'}
            </p>
          </div>

          <div className="flex items-center gap-4">
            {!isRunning && (
              <div className="flex items-center gap-2">
                <label htmlFor="cycles" className="text-sm text-gray-600">Cycles:</label>
                <select
                  id="cycles"
                  value={totalCycles}
                  onChange={(e) => setTotalCycles(Number(e.target.value))}
                  className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
                >
                  <option value={1}>1</option>
                  <option value={3}>3</option>
                  <option value={5}>5</option>
                  <option value={10}>10</option>
                </select>
              </div>
            )}

            <button
              onClick={startOptimization}
              disabled={isRunning || !canStart}
              className={`
                px-6 py-2 rounded-lg font-medium text-sm transition-colors
                ${
                  isRunning || !canStart
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                }
              `}
            >
              {isRunning ? 'Running...' : 'Start Optimization'}
            </button>
          </div>
        </div>
      </div>

      {/* Phase Indicator */}
      {isRunning && (
        <div className="mb-8 bg-white rounded-lg border border-gray-200 shadow-sm">
          <PhaseIndicator activePhase={currentPhase} completedPhases={completedPhases} />
        </div>
      )}

      {/* Score Chart */}
      {scoreData.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Score Progress</h2>
          <div className="bg-white rounded-lg border border-gray-200 p-4 shadow-sm">
            <ScoreChart data={scoreData} height={280} />
          </div>
        </div>
      )}

      {/* Completed Cycles */}
      {completedCycles.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Optimization History ({completedCycles.length} cycle{completedCycles.length !== 1 ? 's' : ''})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {completedCycles.map((cycle) => (
              <LiveCycleCard
                key={cycle.cycle}
                cycle={cycle.cycle}
                changeDescription={cycle.changeDescription}
                scoreDelta={cycle.scoreDelta}
                accepted={cycle.accepted}
              />
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!isRunning && completedCycles.length === 0 && (
        <div className="text-center py-16 bg-white rounded-lg border border-gray-200">
          <div className="text-gray-400 mb-4">
            <svg className="w-16 h-16 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-gray-900 mb-2">
            {requireSelectedAgent && !activeAgentName ? 'Select an agent above to continue' : 'Ready to optimize'}
          </h3>
          <p className="text-sm text-gray-500">
            {requireSelectedAgent && !activeAgentName
              ? 'Select an agent above to start the live simulation.'
              : 'Click "Start Optimization" to begin the simulated optimization walkthrough.'}
          </p>
        </div>
      )}
    </div>
  );
}
