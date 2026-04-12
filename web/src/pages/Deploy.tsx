import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ArrowUpCircle, Rocket, RotateCcw } from 'lucide-react';
import { useConfigs, useDeploy, useDeployStatus, usePromoteCanary, useRollback } from '../lib/api';
import { EmptyState } from '../components/EmptyState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { OperatorNextStepCard } from '../components/OperatorNextStepCard';
import { createJourneyStatusSummary } from '../lib/operator-journey';
import { toastError, toastSuccess } from '../lib/toast';
import { formatPercent, formatTimestamp, statusVariant } from '../lib/utils';
import type { DeployStatus } from '../lib/types';

type PendingConfirmation =
  | { type: 'rollback'; canaryVersion: number | null }
  | { type: 'deploy'; version: number; strategy: 'immediate' }
  | { type: 'promote'; canaryVersion: number | null };

/** Translate deploy status into the shared journey card without changing rollout behavior. */
function getDeployJourneySummary(deployStatus: DeployStatus) {
  if (deployStatus.canary_status) {
    return createJourneyStatusSummary({
      currentStep: 'deploy',
      status: 'ready',
      statusLabel: `Canary v${deployStatus.canary_version ?? deployStatus.canary_status.canary_version}`,
      summary: 'A canary is active. Promote it only after reviewing the canary verdict and traffic evidence.',
      nextLabel: 'Promote canary',
      nextDescription: 'Confirm promotion when the canary is ready to become the active version.',
    });
  }

  return createJourneyStatusSummary({
    currentStep: 'deploy',
    status: 'waiting',
    statusLabel: 'No active canary',
    summary: 'Start a canary from a candidate version before promoting production traffic.',
    nextLabel: 'Start canary',
    nextDescription: 'Open the deploy form, choose a candidate version, and keep the canary strategy selected.',
    href: '/deploy?new=1',
  });
}

export function Deploy() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: deployStatus, isLoading, isError, refetch } = useDeployStatus();
  const { data: configs } = useConfigs();
  const deploy = useDeploy();
  const rollback = useRollback();
  const promoteCanary = usePromoteCanary();

  const [showForm, setShowForm] = useState(false);
  const [version, setVersion] = useState('');
  const [strategy, setStrategy] = useState<'canary' | 'immediate'>('canary');
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const showDeployForm = showForm || searchParams.get('new') === '1';
  const activeConfig = deployStatus?.active_version
    ? configs?.find((entry) => entry.version === deployStatus.active_version) || null
    : null;

  function closeForm() {
    setShowForm(false);
    const next = new URLSearchParams(searchParams);
    next.delete('new');
    setSearchParams(next);
  }

  function handleDeploy() {
    if (!version) return;
    if (strategy === 'immediate') {
      setPendingConfirmation({ type: 'deploy', version: Number(version), strategy });
      return;
    }

    deploy.mutate(
      { version: Number(version), strategy },
      {
        onSuccess: (response) => {
          setPendingConfirmation(null);
          toastSuccess('Deploy request completed', response.message);
          closeForm();
          setVersion('');
          refetch();
        },
        onError: (error) => {
          toastError('Deploy failed', error.message);
        },
      }
    );
  }

  function handlePromote() {
    setPendingConfirmation({
      type: 'promote',
      canaryVersion: deployStatus?.canary_version ?? null,
    });
  }

  function handleRollback() {
    setPendingConfirmation({
      type: 'rollback',
      canaryVersion: deployStatus?.canary_version ?? null,
    });
  }

  function confirmPendingAction() {
    if (!pendingConfirmation) return;

    if (pendingConfirmation.type === 'rollback') {
      rollback.mutate(undefined, {
        onSuccess: (response) => {
          setPendingConfirmation(null);
          toastSuccess('Rollback completed', response.message);
          refetch();
        },
        onError: (error) => {
          setPendingConfirmation(null);
          toastError('Rollback failed', error.message);
        },
      });
      return;
    }

    if (pendingConfirmation.type === 'promote') {
      const params = pendingConfirmation.canaryVersion
        ? { version: pendingConfirmation.canaryVersion }
        : undefined;
      promoteCanary.mutate(params, {
        onSuccess: (response) => {
          setPendingConfirmation(null);
          toastSuccess('Canary promoted', response.message);
          refetch();
        },
        onError: (error) => {
          setPendingConfirmation(null);
          toastError('Promotion failed', error.message);
        },
      });
      return;
    }

    deploy.mutate(
      { version: pendingConfirmation.version, strategy: pendingConfirmation.strategy },
      {
        onSuccess: (response) => {
          setPendingConfirmation(null);
          toastSuccess('Deploy request completed', response.message);
          closeForm();
          setVersion('');
          refetch();
        },
        onError: (error) => {
          setPendingConfirmation(null);
          toastError('Deploy failed', error.message);
        },
      }
    );
  }

  function cancelPendingAction() {
    setPendingConfirmation(null);
  }

  const confirmationTitle =
    pendingConfirmation?.type === 'rollback'
      ? 'Confirm rollback'
      : pendingConfirmation?.type === 'promote'
        ? 'Confirm canary promotion'
        : 'Confirm immediate deploy';
  const confirmationDescription =
    pendingConfirmation?.type === 'rollback'
      ? `Rollback canary v${pendingConfirmation.canaryVersion ?? '—'} and return traffic to the active version.`
      : pendingConfirmation?.type === 'promote'
        ? `Promote canary v${pendingConfirmation.canaryVersion ?? '—'} to active and route all traffic to it.`
        : `Promote v${pendingConfirmation?.type === 'deploy' ? pendingConfirmation.version : '—'} to all traffic immediately.`;

  function isConfirmationPending(type: PendingConfirmation['type']) {
    return pendingConfirmation?.type === type;
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={4} />
        <LoadingSkeleton rows={7} />
      </div>
    );
  }

  if (!deployStatus) {
    return (
      <EmptyState
        icon={Rocket}
        title="No deployment status"
        description="Initialize and deploy a config version to begin rollout management."
        actionLabel="Refresh"
        onAction={() => refetch()}
      />
    );
  }

  const journeySummary = getDeployJourneySummary(deployStatus);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Deploy"
        description="Promote stable versions, run canary rollouts, and monitor verdicts before full promotion."
        actions={
          <button
            onClick={() => {
              if (showDeployForm) {
                closeForm();
                return;
              }
              setShowForm(true);
            }}
            className="rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
          >
            {showDeployForm ? 'Hide Deploy Form' : 'Deploy Version'}
          </button>
        }
      />

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Could not load deployment status.
        </div>
      )}

      <OperatorNextStepCard
        summary={journeySummary}
        onAction={deployStatus.canary_status ? handlePromote : undefined}
      />

      {pendingConfirmation && (
        <section className="rounded-lg border border-amber-200 bg-amber-50 p-4">
          <h3 className="text-sm font-semibold text-amber-900">{confirmationTitle}</h3>
          <p className="mt-1 text-sm text-amber-800">{confirmationDescription}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={cancelPendingAction}
              className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm font-medium text-amber-900 hover:bg-amber-100"
            >
              Cancel
            </button>
            <button
              onClick={confirmPendingAction}
              className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
            >
              {pendingConfirmation.type === 'rollback'
                ? 'Confirm rollback'
                : pendingConfirmation.type === 'promote'
                  ? 'Confirm promote'
                  : 'Confirm deploy'}
            </button>
          </div>
        </section>
      )}

      <section className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <p className="text-xs text-gray-500">Active Version</p>
          <p className="mt-1 text-3xl font-semibold text-gray-900">
            {deployStatus.active_version ? `v${deployStatus.active_version}` : '—'}
          </p>
          {activeConfig && (
            <p className="mt-1 text-xs text-gray-500">{activeConfig.config_hash} · {activeConfig.status}</p>
          )}
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <p className="text-xs text-gray-500">Canary Version</p>
          <p className="mt-1 text-3xl font-semibold text-gray-900">
            {deployStatus.canary_version ? `v${deployStatus.canary_version}` : '—'}
          </p>
          {deployStatus.canary_status ? (
            <p className="mt-1 text-xs text-gray-500">
              {deployStatus.canary_status.canary_conversations} conversations observed
            </p>
          ) : (
            <p className="mt-1 text-xs text-gray-500">No active canary</p>
          )}
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <p className="text-xs text-gray-500">Version Count</p>
          <p className="mt-1 text-3xl font-semibold text-gray-900">{deployStatus.total_versions}</p>
          <p className="mt-1 text-xs text-gray-500">Tracked in version manifest</p>
        </div>
      </section>

      {deployStatus.canary_status && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-gray-900">Canary Verdict</h3>
            <div className="flex items-center gap-2">
              <StatusBadge
                variant={statusVariant(deployStatus.canary_status.verdict)}
                label={deployStatus.canary_status.verdict}
              />
              <button
                onClick={handlePromote}
                disabled={promoteCanary.isPending || isConfirmationPending('promote')}
                className="inline-flex items-center gap-1 rounded-lg border border-green-300 bg-white px-2.5 py-1 text-xs text-green-700 hover:bg-green-50 disabled:opacity-60"
              >
                <ArrowUpCircle className="h-3.5 w-3.5" />
                {promoteCanary.isPending ? 'Promoting...' : 'Promote'}
              </button>
              <button
                onClick={handleRollback}
                disabled={rollback.isPending || isConfirmationPending('rollback')}
                className="inline-flex items-center gap-1 rounded-lg border border-red-300 bg-white px-2.5 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-60"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {rollback.isPending ? 'Rolling back...' : 'Rollback'}
              </button>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <p className="text-xs text-gray-500">Canary success rate</p>
              <p className="mt-1 text-xl font-semibold text-gray-900">
                {formatPercent(deployStatus.canary_status.canary_success_rate)}
              </p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <p className="text-xs text-gray-500">Baseline success rate</p>
              <p className="mt-1 text-xl font-semibold text-gray-900">
                {formatPercent(deployStatus.canary_status.baseline_success_rate)}
              </p>
            </div>
          </div>
        </section>
      )}

      {showDeployForm && (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label htmlFor="deploy-version" className="mb-1 block text-xs text-gray-500">Version</label>
              <select
                id="deploy-version"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">Select version</option>
                {(configs || []).map((config) => (
                  <option key={config.version} value={config.version}>
                    v{config.version} · {config.status}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="deploy-strategy" className="mb-1 block text-xs text-gray-500">Strategy</label>
              <select
                id="deploy-strategy"
                value={strategy}
                onChange={(event) => setStrategy(event.target.value as 'canary' | 'immediate')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="canary">Canary (safe default)</option>
                <option value="immediate">Immediate promotion</option>
              </select>
            </div>

            <div className="flex items-end">
              <button
                onClick={handleDeploy}
                disabled={!version || deploy.isPending || isConfirmationPending('deploy')}
                className="w-full rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
              >
                {deploy.isPending ? 'Deploying...' : 'Deploy'}
              </button>
            </div>
          </div>
        </section>
      )}

      <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 bg-gray-50 px-4 py-3">
          <h3 className="text-sm font-semibold text-gray-900">Recent Deployment History</h3>
        </div>

        {deployStatus.history.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-white">
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Version</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Timestamp</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Status</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Composite</th>
                </tr>
              </thead>
              <tbody>
                {deployStatus.history.map((entry, index) => (
                  <tr key={`${entry.version}-${entry.timestamp}`} className={index % 2 ? 'bg-gray-50/60' : ''}>
                    <td className="px-4 py-2 font-medium text-gray-900">v{entry.version}</td>
                    <td className="px-4 py-2 text-gray-600">{formatTimestamp(entry.timestamp)}</td>
                    <td className="px-4 py-2">
                      <StatusBadge variant={statusVariant(entry.status)} label={entry.status} />
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {typeof entry.scores?.composite === 'number'
                        ? `${(entry.scores.composite * 100).toFixed(1)}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-6 text-center text-sm text-gray-500">No deployment history yet.</div>
        )}
      </section>
    </div>
  );
}
