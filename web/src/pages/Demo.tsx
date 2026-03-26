import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Play, CheckCircle2, ArrowRight, Activity, Shield, Zap, Target } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { HealthPulse } from '../components/HealthPulse';
import { StatusBadge } from '../components/StatusBadge';

interface DemoScenario {
  name: string;
  description: string;
  journey: {
    initial_health: number;
    final_health: number;
    improvement: number;
    cycles: number;
  };
  acts: Array<{
    act: number;
    title: string;
    description: string;
    metrics?: Record<string, number>;
    insight?: string;
    improvement?: string;
  }>;
}

interface ActProgress {
  act: number;
  title: string;
  description: string;
  status: 'pending' | 'running' | 'complete';
  diagnosis?: any;
  proposal?: any;
  evaluation?: any;
  decision?: any;
  message?: string;
}

export function Demo() {
  const navigate = useNavigate();
  const [scenario, setScenario] = useState<DemoScenario | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [actProgress, setActProgress] = useState<ActProgress[]>([]);
  const [currentScore, setCurrentScore] = useState(0.62);
  const [finalResult, setFinalResult] = useState<any>(null);

  useEffect(() => {
    fetch('/api/demo/scenario')
      .then((res) => res.json())
      .then((data) => {
        setScenario(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load demo scenario:', err);
        setLoading(false);
      });
  }, []);

  const runDemo = () => {
    setRunning(true);
    setActProgress([]);
    setCurrentScore(0.62);
    setFinalResult(null);

    const eventSource = new EventSource('/api/demo/stream');

    eventSource.addEventListener('act_start', (event) => {
      const data = JSON.parse(event.data);
      setActProgress((prev) => [
        ...prev,
        {
          act: data.act,
          title: data.title,
          description: data.description,
          status: 'running',
        },
      ]);
    });

    eventSource.addEventListener('diagnosis', (event) => {
      const data = JSON.parse(event.data);
      setActProgress((prev) =>
        prev.map((act) => (act.status === 'running' ? { ...act, diagnosis: data } : act))
      );
    });

    eventSource.addEventListener('proposal', (event) => {
      const data = JSON.parse(event.data);
      setActProgress((prev) =>
        prev.map((act) => (act.status === 'running' ? { ...act, proposal: data } : act))
      );
    });

    eventSource.addEventListener('evaluation', (event) => {
      const data = JSON.parse(event.data);
      setActProgress((prev) =>
        prev.map((act) => (act.status === 'running' ? { ...act, evaluation: data } : act))
      );
      setCurrentScore(data.score_after);
    });

    eventSource.addEventListener('decision', (event) => {
      const data = JSON.parse(event.data);
      setActProgress((prev) =>
        prev.map((act) => (act.status === 'running' ? { ...act, decision: data } : act))
      );
    });

    eventSource.addEventListener('act_complete', (event) => {
      const data = JSON.parse(event.data);
      setActProgress((prev) =>
        prev.map((act) => (act.status === 'running' ? { ...act, status: 'complete', message: data.message } : act))
      );
    });

    eventSource.addEventListener('demo_complete', (event) => {
      const data = JSON.parse(event.data);
      setFinalResult(data);
      setRunning(false);
      eventSource.close();
    });

    eventSource.onerror = () => {
      setRunning(false);
      eventSource.close();
    };
  };

  if (loading) {
    return <LoadingSkeleton rows={8} />;
  }

  if (!scenario) {
    return (
      <div className="space-y-4">
        <PageHeader title="Demo" description="Failed to load demo scenario" />
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Could not load demo scenario. Please check the API connection.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="VP Demo: E-commerce Support Bot"
        description="Watch AutoAgent optimize a real-world support bot from 0.62 → 0.87 health"
        actions={
          <>
            <button
              onClick={() => navigate('/experiments')}
              className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              View Experiments
            </button>
            <button
              onClick={() => navigate('/traces')}
              className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              View Traces
            </button>
            <button
              onClick={runDemo}
              disabled={running}
              className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 px-4 py-2 text-sm font-medium text-white shadow-lg transition hover:from-blue-700 hover:to-purple-700 disabled:opacity-60"
            >
              {running ? (
                <>
                  <Activity className="h-4 w-4 animate-pulse" />
                  Running Demo...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  Run Demo
                </>
              )}
            </button>
          </>
        }
      />

      {/* Scenario Overview */}
      <section className="rounded-lg border border-gray-200 bg-gradient-to-br from-blue-50 to-purple-50 p-6">
        <div className="flex items-start gap-4">
          <div className="rounded-full bg-gradient-to-br from-blue-500 to-purple-600 p-3">
            <Sparkles className="h-6 w-6 text-white" />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-semibold text-gray-900">{scenario.name}</h2>
            <p className="mt-1 text-sm text-gray-600">{scenario.description}</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-4">
              <div className="rounded-lg bg-white p-3 shadow-sm">
                <div className="flex items-center gap-2">
                  <Target className="h-4 w-4 text-gray-400" />
                  <p className="text-xs text-gray-500">Initial Health</p>
                </div>
                <p className="mt-1 text-2xl font-bold text-gray-900">{(scenario.journey.initial_health * 100).toFixed(0)}%</p>
              </div>
              <div className="rounded-lg bg-white p-3 shadow-sm">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-gray-400" />
                  <p className="text-xs text-gray-500">Final Health</p>
                </div>
                <p className="mt-1 text-2xl font-bold text-green-600">{(scenario.journey.final_health * 100).toFixed(0)}%</p>
              </div>
              <div className="rounded-lg bg-white p-3 shadow-sm">
                <div className="flex items-center gap-2">
                  <ArrowRight className="h-4 w-4 text-gray-400" />
                  <p className="text-xs text-gray-500">Improvement</p>
                </div>
                <p className="mt-1 text-2xl font-bold text-blue-600">+{(scenario.journey.improvement * 100).toFixed(0)}%</p>
              </div>
              <div className="rounded-lg bg-white p-3 shadow-sm">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-gray-400" />
                  <p className="text-xs text-gray-500">Optimization Acts</p>
                </div>
                <p className="mt-1 text-2xl font-bold text-purple-600">{scenario.journey.cycles}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Live Progress */}
      {(running || finalResult) && (
        <section className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Live Optimization Progress</h3>
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-500">Current Health</span>
              <HealthPulse score={currentScore} label="" size="sm" />
            </div>
          </div>

          <div className="space-y-4">
            {actProgress.map((act) => (
              <div
                key={act.act}
                className={`rounded-lg border p-4 transition-all ${
                  act.status === 'running'
                    ? 'border-blue-300 bg-blue-50'
                    : act.status === 'complete'
                    ? 'border-green-300 bg-green-50'
                    : 'border-gray-200 bg-gray-50'
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    {act.status === 'complete' ? (
                      <CheckCircle2 className="mt-0.5 h-5 w-5 text-green-600" />
                    ) : act.status === 'running' ? (
                      <Activity className="mt-0.5 h-5 w-5 animate-pulse text-blue-600" />
                    ) : (
                      <div className="mt-0.5 h-5 w-5 rounded-full border-2 border-gray-300" />
                    )}
                    <div className="flex-1">
                      <h4 className="font-semibold text-gray-900">
                        Act {act.act}: {act.title}
                      </h4>
                      <p className="mt-0.5 text-sm text-gray-600">{act.description}</p>

                      {act.diagnosis && (
                        <div className="mt-3 rounded-md bg-white p-3">
                          <p className="text-xs font-semibold text-gray-700">Diagnosis</p>
                          {act.diagnosis.failure_buckets && (
                            <div className="mt-2 space-y-1">
                              {Object.entries(act.diagnosis.failure_buckets).map(([key, count]) => (
                                <div key={key} className="flex items-center justify-between text-xs">
                                  <span className="text-gray-600">{key.replace(/_/g, ' ')}</span>
                                  <span className="font-medium text-gray-900">{count as number} failures</span>
                                </div>
                              ))}
                            </div>
                          )}
                          {act.diagnosis.root_cause && (
                            <p className="mt-2 text-xs text-gray-700">
                              <span className="font-semibold">Root cause:</span> {act.diagnosis.root_cause}
                            </p>
                          )}
                        </div>
                      )}

                      {act.proposal && (
                        <div className="mt-3 rounded-md bg-white p-3">
                          <p className="text-xs font-semibold text-gray-700">Proposal</p>
                          <p className="mt-1 text-sm text-gray-900">{act.proposal.change_description}</p>
                          <p className="mt-2 text-xs text-gray-600">
                            <span className="font-semibold">Section:</span> {act.proposal.config_section}
                          </p>
                          <p className="mt-1 text-xs text-gray-600">
                            <span className="font-semibold">Reasoning:</span> {act.proposal.reasoning}
                          </p>
                        </div>
                      )}

                      {act.evaluation && (
                        <div className="mt-3 rounded-md bg-white p-3">
                          <p className="text-xs font-semibold text-gray-700">Evaluation</p>
                          <div className="mt-2 grid grid-cols-3 gap-3">
                            <div>
                              <p className="text-xs text-gray-500">Before</p>
                              <p className="text-lg font-bold text-gray-900">
                                {(act.evaluation.score_before * 100).toFixed(0)}%
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-500">After</p>
                              <p className="text-lg font-bold text-green-600">
                                {(act.evaluation.score_after * 100).toFixed(0)}%
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-500">Improvement</p>
                              <p className="text-lg font-bold text-blue-600">
                                +{(act.evaluation.improvement * 100).toFixed(0)}%
                              </p>
                            </div>
                          </div>
                        </div>
                      )}

                      {act.decision && (
                        <div className="mt-3 rounded-md bg-white p-3">
                          <div className="flex items-center justify-between">
                            <p className="text-xs font-semibold text-gray-700">Decision</p>
                            <StatusBadge
                              variant={act.decision.accepted ? 'success' : 'error'}
                              label={act.decision.accepted ? 'Accepted' : 'Rejected'}
                            />
                          </div>
                          <p className="mt-2 text-xs text-gray-700">{act.decision.message}</p>
                        </div>
                      )}

                      {act.message && act.status === 'complete' && (
                        <p className="mt-3 text-sm font-medium text-green-700">{act.message}</p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {finalResult && (
            <div className="mt-6 rounded-lg border-2 border-green-300 bg-gradient-to-br from-green-50 to-blue-50 p-6">
              <div className="flex items-start gap-4">
                <div className="rounded-full bg-gradient-to-br from-green-500 to-blue-600 p-3">
                  <CheckCircle2 className="h-8 w-8 text-white" />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-bold text-gray-900">{finalResult.message}</h3>
                  <div className="mt-4 grid gap-3 sm:grid-cols-3">
                    <div className="rounded-lg bg-white p-3 shadow-sm">
                      <p className="text-xs text-gray-500">Baseline Health</p>
                      <p className="text-2xl font-bold text-gray-900">{(finalResult.baseline * 100).toFixed(0)}%</p>
                    </div>
                    <div className="rounded-lg bg-white p-3 shadow-sm">
                      <p className="text-xs text-gray-500">Final Health</p>
                      <p className="text-2xl font-bold text-green-600">{(finalResult.final * 100).toFixed(0)}%</p>
                    </div>
                    <div className="rounded-lg bg-white p-3 shadow-sm">
                      <p className="text-xs text-gray-500">Total Improvement</p>
                      <p className="text-2xl font-bold text-blue-600">+{finalResult.percentage_improvement.toFixed(1)}%</p>
                    </div>
                  </div>
                  <div className="mt-4">
                    <p className="text-xs font-semibold text-gray-700">Changes Applied:</p>
                    <ul className="mt-2 space-y-1">
                      {finalResult.fixes.map((fix: string, index: number) => (
                        <li key={index} className="flex items-start gap-2 text-sm text-gray-700">
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
                          <span>{fix}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="mt-4 flex gap-3">
                    <button
                      onClick={() => navigate('/experiments')}
                      className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    >
                      View Experiment Cards
                      <ArrowRight className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => navigate('/traces')}
                      className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    >
                      Explore Traces
                      <ArrowRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Story Acts */}
      <section className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-sm font-semibold text-gray-900">Optimization Journey (5 Acts)</h3>
        <div className="space-y-3">
          {scenario.acts.map((act, index) => (
            <div key={act.act} className="rounded-lg border border-gray-200 bg-gray-50 p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-sm font-bold text-white">
                  {act.act}
                </div>
                <div className="flex-1">
                  <h4 className="font-semibold text-gray-900">{act.title}</h4>
                  <p className="mt-1 text-sm text-gray-600">{act.description}</p>
                  {act.metrics && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {Object.entries(act.metrics).map(([key, value]) => (
                        <span key={key} className="rounded-md bg-white px-2 py-1 text-xs text-gray-700">
                          {key.replace(/_/g, ' ')}: <span className="font-semibold">{value}</span>
                        </span>
                      ))}
                    </div>
                  )}
                  {act.insight && <p className="mt-2 text-sm italic text-gray-700">{act.insight}</p>}
                  {act.improvement && (
                    <p className="mt-2 text-sm font-medium text-green-700">{act.improvement}</p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
