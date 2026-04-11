import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  Bot,
  CheckCircle2,
  Code2,
  FileText,
  FlaskConical,
  GitCompareArrows,
  History,
  MessageSquare,
  Play,
  Rocket,
  RotateCcw,
  Send,
  ShieldCheck,
  TerminalSquare,
  Wrench,
  XCircle,
} from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { classNames } from '../lib/utils';
import {
  applyWorkbenchPlan,
  getDefaultWorkbenchProject,
  planWorkbenchChange,
  rollbackWorkbenchProject,
  testWorkbenchProject,
  type CompatibilityStatus,
  type WorkbenchActivity,
  type WorkbenchCompatibilityDiagnostic,
  type WorkbenchExportPreview,
  type WorkbenchOperation,
  type WorkbenchPlan,
  type WorkbenchProject,
  type WorkbenchTarget,
  type WorkbenchTestResult,
} from '../lib/workbench-api';

type WorkbenchMode = 'plan' | 'apply' | 'ask';
type WorkbenchTab =
  | 'preview'
  | 'agent-card'
  | 'source'
  | 'tools'
  | 'callbacks'
  | 'guardrails'
  | 'evals'
  | 'trace'
  | 'test-live'
  | 'deploy'
  | 'activity';

interface ThreadMessage {
  id: string;
  role: 'builder' | 'user' | 'system';
  content: string;
}

interface WorkbenchCollectionItem {
  id: string;
  name?: string;
  description?: string;
  rule?: string;
  hook?: string;
}

const WORKBENCH_TABS: Array<{ id: WorkbenchTab; label: string }> = [
  { id: 'preview', label: 'Preview' },
  { id: 'agent-card', label: 'Agent Card' },
  { id: 'source', label: 'Source Code' },
  { id: 'tools', label: 'Tools' },
  { id: 'callbacks', label: 'Callbacks' },
  { id: 'guardrails', label: 'Guardrails' },
  { id: 'evals', label: 'Evals' },
  { id: 'trace', label: 'Trace' },
  { id: 'test-live', label: 'Test Live' },
  { id: 'deploy', label: 'Deploy' },
  { id: 'activity', label: 'Activity / Diff' },
];

const TARGET_OPTIONS: WorkbenchTarget[] = ['portable', 'adk', 'cx'];
const MODE_LABELS: Record<WorkbenchMode, string> = {
  plan: 'Plan',
  apply: 'Apply',
  ask: 'Ask',
};

const MODE_ARIA_LABELS: Record<WorkbenchMode, string> = {
  plan: 'Plan mode',
  apply: 'Apply mode',
  ask: 'Ask mode',
};

/**
 * Two-pane Agent Builder Workbench built around the canonical project model.
 */
export function AgentWorkbench() {
  const [project, setProject] = useState<WorkbenchProject | null>(null);
  const [plan, setPlan] = useState<WorkbenchPlan | null>(null);
  const [activeTab, setActiveTab] = useState<WorkbenchTab>('preview');
  const [request, setRequest] = useState('');
  const [testMessage, setTestMessage] = useState('My flight is delayed and I need to change my booking.');
  const [mode, setMode] = useState<WorkbenchMode>('plan');
  const [target, setTarget] = useState<WorkbenchTarget>('portable');
  const [environment, setEnvironment] = useState('draft');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [thread, setThread] = useState<ThreadMessage[]>([
    {
      id: 'starter',
      role: 'builder',
      content:
        'Describe the agent you want to build or change. I will turn that into a structured plan before touching the canonical model.',
    },
  ]);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    getDefaultWorkbenchProject()
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setProject(payload.project);
        setTarget(payload.project.target);
        setEnvironment(payload.project.environment);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Workbench failed to load');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setBusy(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rootAgent = project?.model.agents[0] ?? null;
  const latestActivity = project?.activity ?? [];
  const latestVersion = project?.versions.at(-1) ?? null;
  const invalidCompatibility = useMemo(
    () => (project?.compatibility ?? []).filter((item) => item.status === 'invalid'),
    [project?.compatibility]
  );

  function appendThread(message: Omit<ThreadMessage, 'id'>) {
    setThread((current) => [
      ...current,
      {
        ...message,
        id: `thread-${Date.now()}-${current.length}`,
      },
    ]);
  }

  async function handlePlan() {
    const trimmed = request.trim();
    if (!project || !trimmed || busy) {
      return;
    }

    setBusy(true);
    setError(null);
    appendThread({ role: 'user', content: trimmed });
    try {
      const payload = await planWorkbenchChange({
        project_id: project.project_id,
        message: trimmed,
        target,
        mode,
      });
      setProject(payload.project);
      setPlan(payload.plan ?? null);
      setRequest('');
      appendThread({
        role: 'builder',
        content: `Plan ready: ${payload.plan?.summary ?? 'Review the proposed changes before applying.'}`,
      });
    } catch (planError) {
      setError(planError instanceof Error ? planError.message : 'Unable to create a plan');
    } finally {
      setBusy(false);
    }
  }

  async function handleApplyPlan() {
    if (!project || !plan || busy) {
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const payload = await applyWorkbenchPlan({
        project_id: project.project_id,
        plan_id: plan.plan_id,
      });
      setProject(payload.project);
      setPlan(payload.plan ?? null);
      appendThread({
        role: 'system',
        content: `Applied v${payload.project.version}. Automatic test ${payload.project.last_test?.status ?? 'completed'}.`,
      });
    } catch (applyError) {
      setError(applyError instanceof Error ? applyError.message : 'Unable to apply the plan');
    } finally {
      setBusy(false);
    }
  }

  async function handleRunTest() {
    if (!project || busy) {
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const payload = await testWorkbenchProject({
        project_id: project.project_id,
        message: testMessage,
      });
      setProject(payload.project);
      appendThread({
        role: 'system',
        content: `Manual test ${payload.project.last_test?.status ?? 'completed'} for v${payload.project.version}.`,
      });
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : 'Unable to run test');
    } finally {
      setBusy(false);
    }
  }

  async function handleRollback() {
    if (!project || project.versions.length < 2 || busy) {
      return;
    }
    const previousVersion = project.versions[project.versions.length - 2];
    setBusy(true);
    setError(null);
    try {
      const payload = await rollbackWorkbenchProject({
        project_id: project.project_id,
        version: previousVersion.version,
      });
      setProject(payload.project);
      setPlan(null);
      appendThread({
        role: 'system',
        content: `Rolled back to v${previousVersion.version}; new draft is v${payload.project.version}.`,
      });
    } catch (rollbackError) {
      setError(rollbackError instanceof Error ? rollbackError.message : 'Unable to roll back');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="workbench-page" className="space-y-5">
      <PageHeader
        title="Agent Builder Workbench"
        description="Conversation on the left. Truth on the right."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Target mode"
              value={target}
              onChange={(event) => setTarget(event.target.value as WorkbenchTarget)}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700"
            >
              {TARGET_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option === 'portable' ? 'Portable' : option.toUpperCase()}
                </option>
              ))}
            </select>
            <select
              aria-label="Environment"
              value={environment}
              onChange={(event) => setEnvironment(event.target.value)}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700"
            >
              <option value="draft">Draft</option>
              <option value="staging">Staging</option>
              <option value="production">Production</option>
            </select>
            <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">
              {project?.last_test ? `Eval health: ${project.last_test.status}` : 'Eval health: untested'}
            </span>
            <Link
              to="/deploy?new=1"
              className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
            >
              <Rocket className="h-4 w-4" />
              Deploy
            </Link>
            <button
              type="button"
              onClick={() => void handleRollback()}
              disabled={!project || project.versions.length < 2 || busy}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RotateCcw className="h-4 w-4" />
              Rollback
            </button>
          </div>
        }
      />

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      <div className="grid min-h-[760px] gap-5 xl:grid-cols-[minmax(340px,0.42fr)_minmax(0,0.58fr)]">
        <section
          data-testid="workbench-left-pane"
          className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-gray-200 bg-white"
        >
          <div className="border-b border-gray-200 px-5 py-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Builder loop</p>
                <h2 className="mt-1 text-lg font-semibold text-gray-900">Plan, apply, test</h2>
              </div>
              <span className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-semibold text-gray-700">
                {project?.draft_badge ?? 'Loading...'}
              </span>
            </div>
            <p className="mt-2 text-sm leading-6 text-gray-600">
              Natural-language requests become structured operations. Applying a plan creates a version and runs validation.
            </p>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
            {thread.map((message) => (
              <div
                key={message.id}
                className={classNames(
                  'rounded-lg border px-4 py-3 text-sm leading-6',
                  message.role === 'user'
                    ? 'ml-8 border-sky-200 bg-sky-50 text-sky-950'
                    : message.role === 'system'
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                      : 'mr-8 border-gray-200 bg-gray-50 text-gray-700'
                )}
              >
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                  {message.role === 'user' ? 'You' : message.role === 'system' ? 'Progress' : 'Workbench'}
                </p>
                <p>{message.content}</p>
              </div>
            ))}

            {plan ? <ChangePlanCard plan={plan} onApply={() => void handleApplyPlan()} busy={busy} /> : null}

            {project?.last_test ? <TestResultPanel result={project.last_test} /> : null}

            <VersionHistoryPanel project={project} latestVersion={latestVersion} />
          </div>

          <div className="border-t border-gray-200 bg-gray-50 px-5 py-4">
            <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Composer mode">
              {(['plan', 'apply', 'ask'] as WorkbenchMode[]).map((item) => (
                <button
                  key={item}
                  type="button"
                  aria-label={MODE_ARIA_LABELS[item]}
                  aria-pressed={mode === item}
                  onClick={() => setMode(item)}
                  className={classNames(
                    'rounded-lg border px-3 py-1.5 text-xs font-semibold capitalize',
                    mode === item
                      ? 'border-gray-900 bg-gray-900 text-white'
                      : 'border-gray-200 bg-white text-gray-600 hover:text-gray-900'
                  )}
                >
                  {MODE_LABELS[item]}
                </button>
              ))}
            </div>
            <label htmlFor="workbench-request" className="sr-only">
              Workbench request
            </label>
            <textarea
              id="workbench-request"
              aria-label="Workbench request"
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              rows={4}
              placeholder="Add a tool, callback, guardrail, eval, or sub-agent..."
              className="w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-3 text-sm leading-6 text-gray-900 outline-none focus:border-sky-500 focus:ring-4 focus:ring-sky-100"
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-gray-500">
                Plans are reviewable. Apply creates a version and runs a test.
              </p>
              <button
                type="button"
                onClick={() => void handlePlan()}
                disabled={!project || !request.trim() || busy}
                className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
                {busy ? 'Creating plan...' : 'Create plan'}
              </button>
            </div>
          </div>
        </section>

        <section
          data-testid="workbench-right-pane"
          className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-gray-200 bg-white"
        >
          <div className="border-b border-gray-200 px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Current system truth</p>
                <h2 className="mt-1 text-lg font-semibold text-gray-900">
                  {rootAgent?.name ?? project?.name ?? 'Loading Workbench'}
                </h2>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-gray-600">
                  {rootAgent?.role ?? 'Canonical model, compiled outputs, test evidence, and deploy state stay together.'}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <TruthBadge label={`${project?.model.tools.length ?? 0} tools`} />
                <TruthBadge label={`${project?.model.callbacks.length ?? 0} callbacks`} />
                <TruthBadge label={`${project?.model.guardrails.length ?? 0} guardrails`} />
                <TruthBadge label={`${invalidCompatibility.length} invalid`} tone={invalidCompatibility.length ? 'red' : 'green'} />
              </div>
            </div>
          </div>

          <div className="border-b border-gray-200 bg-gray-50 px-3 py-2">
            <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="Workbench truth tabs">
              {WORKBENCH_TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={classNames(
                    'shrink-0 rounded-lg px-3 py-2 text-sm font-medium',
                    activeTab === tab.id
                      ? 'bg-white text-gray-950 shadow-sm'
                      : 'text-gray-600 hover:bg-white/70 hover:text-gray-900'
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
            {project ? (
              <RightPaneContent
                tab={activeTab}
                project={project}
                testMessage={testMessage}
                onTestMessageChange={setTestMessage}
                onRunTest={() => void handleRunTest()}
                busy={busy}
                activity={latestActivity}
              />
            ) : (
              <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
                {busy ? 'Loading Workbench...' : 'Workbench project unavailable.'}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function ChangePlanCard({
  plan,
  onApply,
  busy,
}: {
  plan: WorkbenchPlan;
  onApply: () => void;
  busy: boolean;
}) {
  const applied = plan.status === 'applied';

  return (
    <section
      data-testid="workbench-change-plan"
      className={classNames(
        'rounded-lg border px-4 py-4',
        applied ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p
            className={classNames(
              'text-xs font-semibold uppercase tracking-wider',
              applied ? 'text-emerald-700' : 'text-amber-700'
            )}
          >
            {applied ? 'Applied plan' : 'Change plan'}
          </p>
          <h3 className={classNames('mt-1 text-sm font-semibold', applied ? 'text-emerald-950' : 'text-amber-950')}>
            {plan.summary}
          </h3>
          <p className={classNames('mt-1 text-xs', applied ? 'text-emerald-800' : 'text-amber-800')}>
            Source v{plan.source_version}. Test after apply: {plan.test_after_apply ? 'required' : 'not configured'}.
          </p>
        </div>
        <button
          type="button"
          onClick={onApply}
          disabled={busy || applied}
          className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {applied ? 'Applied' : 'Apply plan'}
        </button>
      </div>
      <div className="mt-3 space-y-2">
        {plan.operations.map((operation, index) => (
          <PlanOperationRow key={`${operation.operation}-${operation.label}-${index}`} operation={operation} />
        ))}
      </div>
    </section>
  );
}

function PlanOperationRow({ operation }: { operation: WorkbenchOperation }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-white px-3 py-2">
      <div>
        <p className="text-sm font-medium text-gray-900">{operation.label}</p>
        <p className="text-xs text-gray-500">
          {operation.operation} {'->'} {operation.target}
        </p>
      </div>
      <CompatibilityPill status={operation.compatibility_status} />
    </div>
  );
}

function TestResultPanel({ result }: { result: WorkbenchTestResult }) {
  const passed = result.status === 'passed';
  return (
    <section className={classNames('rounded-lg border px-4 py-4', passed ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50')}>
      <div className="flex items-center gap-2">
        {passed ? <CheckCircle2 className="h-4 w-4 text-emerald-700" /> : <XCircle className="h-4 w-4 text-red-700" />}
        <h3 className={classNames('text-sm font-semibold', passed ? 'text-emerald-950' : 'text-red-950')}>
          Automatic test {result.status}
        </h3>
      </div>
      <div className="mt-3 space-y-2">
        {result.checks.map((check) => (
          <div key={check.name} className="rounded-lg border border-white/70 bg-white px-3 py-2">
            <p className="text-sm font-medium text-gray-900">{check.name}</p>
            <p className="text-xs leading-5 text-gray-600">{check.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function VersionHistoryPanel({
  project,
  latestVersion,
}: {
  project: WorkbenchProject | null;
  latestVersion: { version: number; summary: string; created_at: string } | null;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white px-4 py-4">
      <div className="flex items-center gap-2">
        <History className="h-4 w-4 text-gray-500" />
        <h3 className="text-sm font-semibold text-gray-900">Version history</h3>
      </div>
      <p className="mt-1 text-xs leading-5 text-gray-500">
        {latestVersion
          ? `Latest v${latestVersion.version}: ${latestVersion.summary}`
          : 'Versions appear after the canonical model is created.'}
      </p>
      <div className="mt-3 space-y-2">
        {(project?.versions ?? []).slice(-4).reverse().map((version) => (
          <div key={version.version} className="flex items-center justify-between gap-3 rounded-lg bg-gray-50 px-3 py-2">
            <span className="text-sm font-medium text-gray-900">v{version.version}</span>
            <span className="truncate text-xs text-gray-500">{version.summary}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function TruthBadge({ label, tone = 'gray' }: { label: string; tone?: 'gray' | 'green' | 'red' }) {
  return (
    <span
      className={classNames(
        'rounded-lg border px-3 py-1.5 text-xs font-semibold',
        tone === 'green'
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
          : tone === 'red'
            ? 'border-red-200 bg-red-50 text-red-700'
            : 'border-gray-200 bg-gray-50 text-gray-700'
      )}
    >
      {label}
    </span>
  );
}

function RightPaneContent({
  tab,
  project,
  testMessage,
  onTestMessageChange,
  onRunTest,
  busy,
  activity,
}: {
  tab: WorkbenchTab;
  project: WorkbenchProject;
  testMessage: string;
  onTestMessageChange: (value: string) => void;
  onRunTest: () => void;
  busy: boolean;
  activity: WorkbenchActivity[];
}) {
  const rootAgent = project.model.agents[0];
  switch (tab) {
    case 'agent-card':
      return <AgentCard project={project} />;
    case 'source':
      return <SourceCodeTab adk={project.exports.adk} cx={project.exports.cx} />;
    case 'tools':
      return <CollectionTab icon={Wrench} title="Tools" empty="No tools yet." items={project.model.tools} diagnostics={project.compatibility} />;
    case 'callbacks':
      return <CollectionTab icon={GitCompareArrows} title="Callbacks" empty="No callbacks yet." items={project.model.callbacks} diagnostics={project.compatibility} />;
    case 'guardrails':
      return <CollectionTab icon={ShieldCheck} title="Guardrails" empty="No guardrails yet." items={project.model.guardrails} diagnostics={project.compatibility} />;
    case 'evals':
      return <EvalsTab project={project} />;
    case 'trace':
      return <TraceTab result={project.last_test} />;
    case 'test-live':
      return (
        <TestLiveTab
          message={testMessage}
          onMessageChange={onTestMessageChange}
          onRunTest={onRunTest}
          busy={busy}
          result={project.last_test}
        />
      );
    case 'deploy':
      return <DeployTab project={project} />;
    case 'activity':
      return <ActivityTab activity={activity} />;
    case 'preview':
    default:
      return (
        <div className="space-y-4">
          <section className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4">
            <div className="flex items-start gap-3">
              <Bot className="mt-1 h-5 w-5 text-sky-600" />
              <div>
                <h3 className="text-base font-semibold text-gray-900">{rootAgent.name}</h3>
                <p className="mt-1 text-sm leading-6 text-gray-600">{rootAgent.instructions}</p>
              </div>
            </div>
          </section>
          <CompatibilityMatrix diagnostics={project.compatibility} />
        </div>
      );
  }
}

function AgentCard({ project }: { project: WorkbenchProject }) {
  const rootAgent = project.model.agents[0];
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Canonical agent card</p>
        <h3 className="mt-2 text-xl font-semibold text-gray-900">{rootAgent.name}</h3>
        <p className="mt-2 text-sm leading-6 text-gray-600">{rootAgent.role}</p>
        <dl className="mt-4 grid gap-3 sm:grid-cols-3">
          <AgentCardMetric label="Model" value={rootAgent.model} />
          <AgentCardMetric label="Version" value={`v${project.version}`} />
          <AgentCardMetric label="Target" value={project.target} />
        </dl>
      </section>
      <section className="rounded-lg border border-gray-200 bg-white px-4 py-4">
        <h4 className="text-sm font-semibold text-gray-900">Components</h4>
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <AgentCardMetric label="Tools" value={String(project.model.tools.length)} />
          <AgentCardMetric label="Callbacks" value={String(project.model.callbacks.length)} />
          <AgentCardMetric label="Guardrails" value={String(project.model.guardrails.length)} />
          <AgentCardMetric label="Eval suites" value={String(project.model.eval_suites.length)} />
        </div>
      </section>
    </div>
  );
}

function AgentCardMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-3">
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold text-gray-900">{value}</dd>
    </div>
  );
}

function SourceCodeTab({ adk, cx }: { adk: WorkbenchExportPreview; cx: WorkbenchExportPreview }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <SourcePreview title="ADK Export Preview" icon={TerminalSquare} preview={adk} />
      <SourcePreview title="CX Export Preview" icon={FileText} preview={cx} />
    </div>
  );
}

function SourcePreview({
  title,
  icon: Icon,
  preview,
}: {
  title: string;
  icon: typeof Code2;
  preview: WorkbenchExportPreview;
}) {
  const firstFile = Object.entries(preview.files)[0] ?? ['empty.txt', ''];
  return (
    <section className="min-w-0 rounded-lg border border-gray-200 bg-gray-950 text-gray-100">
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
        <Icon className="h-4 w-4 text-sky-300" />
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      <div className="border-b border-white/10 px-4 py-2 text-xs text-gray-400">{firstFile[0]}</div>
      <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap px-4 py-4 text-xs leading-5">
        {firstFile[1] || 'No source generated yet.'}
      </pre>
    </section>
  );
}

function CollectionTab({
  icon: Icon,
  title,
  empty,
  items,
  diagnostics,
}: {
  icon: typeof Wrench;
  title: string;
  empty: string;
  items: WorkbenchCollectionItem[];
  diagnostics: WorkbenchCompatibilityDiagnostic[];
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-gray-500" />
        <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      </div>
      {items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
          {empty}
        </div>
      ) : (
        items.map((item) => {
          const diagnostic = diagnostics.find((entry) => entry.object_id === item.id);
          return (
            <div key={String(item.id)} className="rounded-lg border border-gray-200 bg-white px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h4 className="text-sm font-semibold text-gray-900">{String(item.name ?? item.id)}</h4>
                  <p className="mt-1 text-sm leading-6 text-gray-600">
                    {String(item.description ?? item.rule ?? item.hook ?? 'Canonical Workbench object.')}
                  </p>
                </div>
                {diagnostic ? <CompatibilityPill status={diagnostic.status} /> : null}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

function EvalsTab({ project }: { project: WorkbenchProject }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-gray-500" />
          <h3 className="text-base font-semibold text-gray-900">Eval suites</h3>
        </div>
        <Link to="/evals?generator=1" className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
          Open Eval Runs
        </Link>
      </div>
      {project.model.eval_suites.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
          No eval suites yet. Ask the Workbench to add an eval for this agent.
        </div>
      ) : (
        project.model.eval_suites.map((suite) => (
          <section key={suite.id} className="rounded-lg border border-gray-200 bg-white px-4 py-4">
            <h4 className="text-sm font-semibold text-gray-900">{suite.name}</h4>
            <p className="mt-1 text-xs text-gray-500">{suite.cases.length} cases</p>
            <div className="mt-3 space-y-2">
              {suite.cases.map((item) => (
                <div key={item.id} className="rounded-lg bg-gray-50 px-3 py-2">
                  <p className="text-sm text-gray-900">{item.input}</p>
                  {item.expected ? <p className="mt-1 text-xs text-gray-500">{item.expected}</p> : null}
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function TraceTab({ result }: { result: WorkbenchTestResult | null }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-gray-500" />
          <h3 className="text-base font-semibold text-gray-900">Trace</h3>
        </div>
        <Link to="/traces" className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
          Open Traces
        </Link>
      </div>
      {result ? (
        <div className="rounded-lg border border-gray-200 bg-white px-4 py-4">
          <p className="text-sm font-semibold text-gray-900">{result.run_id}</p>
          <div className="mt-3 space-y-2">
            {result.trace.map((event) => (
              <div key={event.event} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                <span className="text-sm text-gray-700">{event.event}</span>
                <span className="text-xs font-semibold text-gray-500">{event.status}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
          Apply a plan or run a live test to create trace evidence.
        </div>
      )}
    </div>
  );
}

function TestLiveTab({
  message,
  onMessageChange,
  onRunTest,
  busy,
  result,
}: {
  message: string;
  onMessageChange: (value: string) => void;
  onRunTest: () => void;
  busy: boolean;
  result: WorkbenchTestResult | null;
}) {
  return (
    <div className="space-y-4">
      <label htmlFor="workbench-test-live" className="text-sm font-semibold text-gray-900">
        Test message
      </label>
      <textarea
        id="workbench-test-live"
        value={message}
        onChange={(event) => onMessageChange(event.target.value)}
        rows={5}
        className="w-full resize-none rounded-lg border border-gray-300 px-3 py-3 text-sm leading-6 outline-none focus:border-sky-500 focus:ring-4 focus:ring-sky-100"
      />
      <button
        type="button"
        onClick={onRunTest}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Play className="h-4 w-4" />
        Run test
      </button>
      {result ? <TestResultPanel result={result} /> : null}
    </div>
  );
}

function DeployTab({ project }: { project: WorkbenchProject }) {
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Deployment target</p>
        <h3 className="mt-2 text-base font-semibold text-gray-900">
          {project.target === 'portable' ? 'Portable export' : project.target.toUpperCase()}
        </h3>
        <p className="mt-2 text-sm leading-6 text-gray-600">
          Save this canonical version into the AgentLab library, run evals, then deploy through the existing release workflow.
        </p>
      </section>
      <div className="flex flex-wrap gap-2">
        <Link to="/evals?new=1" className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
          Run Eval
        </Link>
        <Link to="/deploy?new=1" className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800">
          Open Deploy
        </Link>
      </div>
    </div>
  );
}

function ActivityTab({ activity }: { activity: WorkbenchActivity[] }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <MessageSquare className="h-4 w-4 text-gray-500" />
        <h3 className="text-base font-semibold text-gray-900">Activity / Diff</h3>
      </div>
      {activity.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
          Activity appears after planning and applying changes.
        </div>
      ) : (
        activity.map((item) => (
          <section key={item.id} className="rounded-lg border border-gray-200 bg-white px-4 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">{item.kind}</p>
                <h4 className="mt-1 text-sm font-semibold text-gray-900">{item.summary}</h4>
              </div>
              <span className="text-xs text-gray-500">{new Date(item.created_at).toLocaleString()}</span>
            </div>
            <div className="mt-3 space-y-2">
              {item.diff.map((diff, index) => (
                <div key={`${item.id}-${diff.field}-${index}`} className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
                  {diff.field}: {String(diff.before ?? 'none')} {'->'} {String(diff.after ?? 'none')}
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function CompatibilityMatrix({ diagnostics }: { diagnostics: WorkbenchCompatibilityDiagnostic[] }) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white px-4 py-4">
      <h3 className="text-sm font-semibold text-gray-900">Compatibility diagnostics</h3>
      <div className="mt-3 space-y-2">
        {diagnostics.map((item) => (
          <div key={item.object_id} className="flex flex-wrap items-start justify-between gap-3 rounded-lg bg-gray-50 px-3 py-2">
            <div>
              <p className="text-sm font-medium text-gray-900">{item.label}</p>
              <p className="mt-1 text-xs leading-5 text-gray-600">{item.reason}</p>
            </div>
            <CompatibilityPill status={item.status} />
          </div>
        ))}
      </div>
    </section>
  );
}

function CompatibilityPill({ status }: { status: CompatibilityStatus }) {
  const tone =
    status === 'portable'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : status === 'invalid'
        ? 'border-red-200 bg-red-50 text-red-700'
        : 'border-amber-200 bg-amber-50 text-amber-700';
  return (
    <span className={classNames('rounded-lg border px-2.5 py-1 text-xs font-semibold', tone)}>
      {status}
    </span>
  );
}
