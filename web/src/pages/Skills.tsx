import { useMemo, useState } from 'react';
import { BookOpen, FlaskConical, Hammer, Layers, Puzzle, Search, Sparkles, TestTube2, Wrench } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import {
  useArchiveSkill,
  useComposeSkills,
  useCreateSkill,
  useEditDraftSkill,
  useInstallMarketplaceSkill,
  usePromoteSkill,
  useSkillDrafts,
  useSkillEffectiveness,
  useSkillMarketplace,
  useTestSkill,
  useUnifiedSkills,
} from '../lib/api';
import type { SkillCompositionResult, UnifiedSkill } from '../lib/types';
import { toastError, toastSuccess } from '../lib/toast';
import { classNames } from '../lib/utils';

type SkillTab = 'build' | 'runtime';

function skillScore(skill: UnifiedSkill): number {
  const metric = skill.effectiveness;
  return metric.success_rate * Math.max(metric.average_improvement, 0);
}

function SkillCard({
  skill,
  selected,
  onSelect,
  selectedForCompose,
  onToggleCompose,
}: {
  skill: UnifiedSkill;
  selected: boolean;
  onSelect: () => void;
  selectedForCompose: boolean;
  onToggleCompose: () => void;
}) {
  const score = skillScore(skill);
  const usage = skill.effectiveness.times_applied;
  const successRate = Math.round(skill.effectiveness.success_rate * 100);
  return (
    <div
      className={classNames(
        'rounded-xl border p-4 transition',
        selected ? 'border-orange-500 bg-orange-50/50' : 'border-zinc-200 bg-white hover:border-zinc-300'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <button onClick={onSelect} className="text-left">
          <div className="flex items-center gap-2">
            <span
              className={classNames(
                'rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                skill.kind === 'build' ? 'bg-amber-100 text-amber-700' : 'bg-teal-100 text-teal-700'
              )}
            >
              {skill.kind}
            </span>
            <span className="text-[11px] text-zinc-500">v{skill.version}</span>
          </div>
          <h3 className="mt-2 text-sm font-semibold text-zinc-900">{skill.name}</h3>
          <p className="mt-1 text-xs leading-relaxed text-zinc-600">{skill.description}</p>
        </button>
        <button
          onClick={onToggleCompose}
          className={classNames(
            'rounded-md border px-2 py-1 text-[11px] font-medium',
            selectedForCompose
              ? 'border-orange-500 bg-orange-500 text-white'
              : 'border-zinc-300 bg-white text-zinc-700 hover:border-zinc-400'
          )}
        >
          {selectedForCompose ? 'In Set' : 'Compose'}
        </button>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 rounded-lg border border-zinc-200 bg-zinc-50 p-2 text-center">
        <div>
          <p className="text-[10px] uppercase text-zinc-500">Score</p>
          <p className="text-xs font-semibold text-zinc-900">{score.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase text-zinc-500">Success</p>
          <p className="text-xs font-semibold text-zinc-900">{successRate}%</p>
        </div>
        <div>
          <p className="text-[10px] uppercase text-zinc-500">Uses</p>
          <p className="text-xs font-semibold text-zinc-900">{usage}</p>
        </div>
      </div>
      {skill.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {skill.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function DetailPanel({
  skill,
  onRunTest,
}: {
  skill: UnifiedSkill | null;
  onRunTest: (skillId: string) => void;
}) {
  const effectiveness = useSkillEffectiveness(skill?.id ?? null);
  if (!skill) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-300 bg-white p-8 text-center text-sm text-zinc-500">
        Select a skill to view its full definition, dependencies, and effectiveness history.
      </div>
    );
  }
  const history = effectiveness.data?.effectiveness?.history ?? [];
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-zinc-900">{skill.name}</h3>
          <p className="mt-1 text-sm text-zinc-600">{skill.description}</p>
        </div>
        <button
          onClick={() => onRunTest(skill.id)}
          className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-semibold text-zinc-700 hover:border-zinc-400"
        >
          <TestTube2 className="h-3.5 w-3.5" />
          Test
        </button>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3">
          <p className="text-[11px] uppercase text-zinc-500">Capabilities</p>
          <p className="mt-1 text-xs text-zinc-700">{skill.capabilities.join(', ') || 'None'}</p>
        </div>
        <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3">
          <p className="text-[11px] uppercase text-zinc-500">Dependencies</p>
          <p className="mt-1 text-xs text-zinc-700">{skill.dependencies.join(', ') || 'None'}</p>
        </div>
      </div>

      {skill.kind === 'build' ? (
        <div className="mt-4 rounded-lg border border-zinc-200 p-3">
          <p className="text-[11px] uppercase text-zinc-500">Build-Time Mutation Operators</p>
          <div className="mt-2 space-y-2">
            {skill.mutations.map((mutation) => (
              <div key={mutation.name} className="rounded-md border border-zinc-200 bg-zinc-50 p-2 text-xs">
                <p className="font-semibold text-zinc-800">
                  {mutation.name} <span className="text-zinc-500">({mutation.target_surface})</span>
                </p>
                <p className="mt-1 text-zinc-600">{mutation.description}</p>
              </div>
            ))}
            {skill.mutations.length === 0 && <p className="text-xs text-zinc-500">No mutations defined.</p>}
          </div>
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-zinc-200 p-3">
          <p className="text-[11px] uppercase text-zinc-500">Run-Time Tools & Policies</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <div className="rounded-md border border-zinc-200 bg-zinc-50 p-2">
              <p className="text-[11px] font-semibold text-zinc-700">Tools</p>
              <ul className="mt-1 space-y-1 text-xs text-zinc-600">
                {skill.tools.map((tool) => (
                  <li key={tool.name}>{tool.name}</li>
                ))}
                {skill.tools.length === 0 && <li>None</li>}
              </ul>
            </div>
            <div className="rounded-md border border-zinc-200 bg-zinc-50 p-2">
              <p className="text-[11px] font-semibold text-zinc-700">Policies</p>
              <ul className="mt-1 space-y-1 text-xs text-zinc-600">
                {skill.policies.map((policy) => (
                  <li key={policy.name}>{policy.name}</li>
                ))}
                {skill.policies.length === 0 && <li>None</li>}
              </ul>
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 rounded-lg border border-zinc-200 p-3">
        <p className="text-[11px] uppercase text-zinc-500">Effectiveness History</p>
        <p className="mt-1 text-xs text-zinc-600">
          {skill.effectiveness.times_applied} total runs, {(skill.effectiveness.success_rate * 100).toFixed(0)}% success
        </p>
        <div className="mt-2 max-h-28 overflow-y-auto rounded border border-zinc-200 bg-zinc-50 p-2">
          {history.length === 0 ? (
            <p className="text-xs text-zinc-500">No recorded outcomes yet.</p>
          ) : (
            <ul className="space-y-1 text-xs text-zinc-600">
              {history.slice(0, 10).map((entry, idx) => (
                <li key={idx}>
                  {String(entry.recorded_at || 'recent')} | success={String(entry.success)} | improvement=
                  {Number(entry.improvement || 0).toFixed(3)}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function ComposePanel({
  selectedRefs,
  result,
  onCompose,
}: {
  selectedRefs: string[];
  result: SkillCompositionResult | null;
  onCompose: () => void;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-900">Compose Skill Set</h3>
        <button
          onClick={onCompose}
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-zinc-700"
        >
          Compose
        </button>
      </div>
      <p className="mt-1 text-xs text-zinc-600">Selected: {selectedRefs.join(', ') || 'None'}</p>
      {result && (
        <div className="mt-3 rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-xs">
          <p className={classNames('font-semibold', result.valid ? 'text-emerald-700' : 'text-red-700')}>
            {result.valid ? 'Valid composition' : 'Composition has issues'}
          </p>
          {result.missing_dependencies.length > 0 && (
            <p className="mt-1 text-zinc-600">Missing deps: {result.missing_dependencies.join(', ')}</p>
          )}
          {result.conflicts.length > 0 && (
            <p className="mt-1 text-zinc-600">
              Conflicts: {result.conflicts.map((conflict) => `${conflict.surface}`).join(', ')}
            </p>
          )}
          <p className="mt-1 text-zinc-600">
            Ordered: {result.skills.map((skill) => skill.id).join(' -> ') || 'None'}
          </p>
        </div>
      )}
    </div>
  );
}

export function Skills() {
  const [tab, setTab] = useState<SkillTab>('build');
  const [query, setQuery] = useState('');
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null);
  const [composeRefs, setComposeRefs] = useState<string[]>([]);
  const [composeResult, setComposeResult] = useState<SkillCompositionResult | null>(null);

  const skillsQuery = useUnifiedSkills({ kind: tab });
  const draftsQuery = useSkillDrafts();
  const marketQuery = useSkillMarketplace({ kind: tab });
  const installMutation = useInstallMarketplaceSkill();
  const composeMutation = useComposeSkills();
  const testMutation = useTestSkill();
  const createMutation = useCreateSkill();
  const promoteMutation = usePromoteSkill();
  const archiveMutation = useArchiveSkill();
  const editDraftMutation = useEditDraftSkill();

  const skills = skillsQuery.data?.skills ?? [];
  const filteredSkills = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return skills;
    return skills.filter((skill) => {
      const haystack = `${skill.id} ${skill.name} ${skill.description} ${skill.domain} ${skill.tags.join(' ')}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [skills, query]);

  const selectedSkill = useMemo(
    () => filteredSkills.find((skill) => skill.id === selectedSkillId) ?? filteredSkills[0] ?? null,
    [filteredSkills, selectedSkillId]
  );

  function toggleCompose(skill: UnifiedSkill) {
    setComposeRefs((current) =>
      current.includes(skill.id) ? current.filter((value) => value !== skill.id) : [...current, skill.id]
    );
  }

  function runCompose() {
    if (composeRefs.length === 0) {
      toastError('Select skills', 'Choose at least one skill to compose.');
      return;
    }
    composeMutation.mutate(
      { skills: composeRefs },
      {
        onSuccess: (result) => {
          setComposeResult(result);
          toastSuccess('Composition complete', result.valid ? 'Skill set is valid.' : 'Check dependency/conflict notes.');
        },
        onError: (err) => toastError('Compose failed', err.message),
      }
    );
  }

  function runSkillTest(skillId: string) {
    testMutation.mutate(skillId, {
      onSuccess: (result) => {
        toastSuccess('Test finished', `Pass rate ${(result.pass_rate * 100).toFixed(0)}%`);
        skillsQuery.refetch();
      },
      onError: (err) => toastError('Skill test failed', err.message),
    });
  }

  function installListing(name: string) {
    installMutation.mutate(
      { name },
      {
        onSuccess: () => {
          toastSuccess('Skill installed', `${name} installed from marketplace.`);
          skillsQuery.refetch();
          marketQuery.refetch();
        },
        onError: (err) => toastError('Install failed', err.message),
      }
    );
  }

  function quickCreate(kind: SkillTab) {
    const name = window.prompt(`New ${kind} skill id`, kind === 'build' ? 'keyword_expansion_custom' : 'refund_processing_custom');
    if (!name) return;
    const description = window.prompt('Description', `Custom ${kind} skill`) ?? '';

    const payload: Partial<UnifiedSkill> =
      kind === 'build'
        ? {
            id: name,
            name,
            kind: 'build',
            version: '1.0.0',
            description,
            capabilities: ['custom_build_capability'],
            mutations: [
              {
                name: `${name}_mutation`,
                mutation_type: 'instruction_hardening',
                target_surface: 'prompts.root',
                description: description || 'Harden instructions',
              },
            ],
            triggers: [{ failure_family: 'routing_error' }],
            eval_criteria: ['composite_score gt 0.0'],
            guardrails: ['Validate on holdout set'],
            examples: [],
            tools: [],
            instructions: '',
            policies: [],
            dependencies: [],
            test_cases: [],
            tags: ['custom'],
            domain: 'customer-support',
            effectiveness: {
              times_applied: 0,
              success_rate: 0,
              average_improvement: 0,
              successful_runs: 0,
              failed_runs: 0,
              last_updated: null,
              outcomes: [],
            },
            metadata: {},
            status: 'active',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }
        : {
            id: name,
            name,
            kind: 'runtime',
            version: '1.0.0',
            description,
            capabilities: ['custom_runtime_capability'],
            mutations: [],
            triggers: [],
            eval_criteria: [],
            guardrails: [],
            examples: [],
            tools: [{ name: 'custom_tool', description: 'Custom runtime tool' }],
            instructions: 'Handle this capability safely.',
            policies: [{ name: 'custom_policy', rules: ['Never reveal secrets'] }],
            dependencies: [],
            test_cases: [],
            tags: ['custom'],
            domain: 'customer-support',
            effectiveness: {
              times_applied: 0,
              success_rate: 0,
              average_improvement: 0,
              successful_runs: 0,
              failed_runs: 0,
              last_updated: null,
              outcomes: [],
            },
            metadata: {},
            status: 'active',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };

    createMutation.mutate(payload, {
      onSuccess: (data) => {
        toastSuccess('Skill created', `${data.skill.id}@${data.skill.version}`);
        skillsQuery.refetch();
      },
      onError: (err) => toastError('Create failed', err.message),
    });
  }

  function approveDraft(skillId: string) {
    promoteMutation.mutate(
      { id: skillId, approved_by: 'web-reviewer' },
      {
        onSuccess: () => {
          toastSuccess('Draft approved', `${skillId} promoted to active.`);
          draftsQuery.refetch();
          skillsQuery.refetch();
        },
        onError: (err) => toastError('Promotion failed', err.message),
      }
    );
  }

  function editDraft(skillId: string, currentDescription: string) {
    const nextDescription = window.prompt('Edit draft description', currentDescription);
    if (!nextDescription || nextDescription === currentDescription) return;
    editDraftMutation.mutate(
      { id: skillId, updates: { description: nextDescription, edited_by: 'web-editor' } },
      {
        onSuccess: () => {
          toastSuccess('Draft updated', `${skillId} updated before promotion.`);
          draftsQuery.refetch();
        },
        onError: (err) => toastError('Update failed', err.message),
      }
    );
  }

  function rejectDraft(skillId: string) {
    const reason = window.prompt('Reject reason', 'Insufficient effectiveness evidence');
    if (!reason) return;
    archiveMutation.mutate(
      { id: skillId, reason, reviewed_by: 'web-reviewer' },
      {
        onSuccess: () => {
          toastSuccess('Draft rejected', `${skillId} archived.`);
          draftsQuery.refetch();
          skillsQuery.refetch();
        },
        onError: (err) => toastError('Archive failed', err.message),
      }
    );
  }

  const listings = marketQuery.data?.listings ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Skills Marketplace"
        description="Build-time optimization strategies and run-time agent capabilities as one composable primitive."
      />

      <section className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-amber-900">
            Drafts for Review
          </h2>
          <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-amber-800">
            {draftsQuery.data?.count ?? 0}
          </span>
        </div>
        <p className="mb-3 text-xs text-amber-800">
          Human review queue for auto-learned skills. Approve to Promote into the active default skill set.
        </p>
        <div className="space-y-2">
          {(draftsQuery.data?.drafts || []).slice(0, 5).map((draft) => (
            <div key={draft.skill.id} className="rounded-lg border border-amber-200 bg-white px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold text-zinc-900">{draft.skill.id}</p>
                  <p className="text-[11px] text-zinc-600">{draft.skill.description}</p>
                  <p className="mt-1 text-[10px] text-zinc-500">
                    source={draft.source_optimization} · success={(draft.metrics.success_rate * 100).toFixed(0)}% · triggers={draft.skill.triggers.length}
                  </p>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => approveDraft(draft.skill.id)}
                    className="rounded-md border border-emerald-300 bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-100"
                  >
                    Approve & Promote
                  </button>
                  <button
                    onClick={() => editDraft(draft.skill.id, draft.skill.description)}
                    className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-[11px] font-semibold text-zinc-700 hover:bg-zinc-50"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => rejectDraft(draft.skill.id)}
                    className="rounded-md border border-red-300 bg-red-50 px-2 py-1 text-[11px] font-semibold text-red-700 hover:bg-red-100"
                  >
                    Reject
                  </button>
                </div>
              </div>
            </div>
          ))}
          {!draftsQuery.isLoading && (draftsQuery.data?.count ?? 0) === 0 && (
            <p className="rounded-lg border border-dashed border-amber-200 bg-white px-3 py-2 text-xs text-amber-800">
              No drafts awaiting review.
            </p>
          )}
        </div>
      </section>

      <div className="rounded-2xl border border-zinc-200 bg-gradient-to-r from-amber-50 via-white to-teal-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex rounded-lg border border-zinc-300 bg-white p-1">
            <button
              onClick={() => setTab('build')}
              className={classNames(
                'inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-semibold',
                tab === 'build' ? 'bg-amber-500 text-white' : 'text-zinc-600 hover:bg-zinc-100'
              )}
            >
              <FlaskConical className="h-3.5 w-3.5" />
              Build-Time
            </button>
            <button
              onClick={() => setTab('runtime')}
              className={classNames(
                'inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-semibold',
                tab === 'runtime' ? 'bg-teal-600 text-white' : 'text-zinc-600 hover:bg-zinc-100'
              )}
            >
              <Wrench className="h-3.5 w-3.5" />
              Run-Time
            </button>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => quickCreate(tab)}
              className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-semibold text-zinc-700 hover:border-zinc-400"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Create
            </button>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-zinc-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search skills"
                className="rounded-md border border-zinc-300 bg-white py-1.5 pl-8 pr-2 text-xs focus:border-zinc-500 focus:outline-none"
              />
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr,1.8fr]">
        <div className="space-y-4">
          <div className="rounded-xl border border-zinc-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-zinc-900">
                <BookOpen className="h-4 w-4" />
                {tab === 'build' ? 'Build-Time Skills' : 'Run-Time Skills'}
              </h2>
              <span className="text-xs text-zinc-500">{filteredSkills.length} skills</span>
            </div>
            <div className="space-y-3">
              {skillsQuery.isLoading && <p className="text-xs text-zinc-500">Loading skills…</p>}
              {!skillsQuery.isLoading && filteredSkills.length === 0 && (
                <p className="text-xs text-zinc-500">No skills found for this filter.</p>
              )}
              {filteredSkills.map((skill) => (
                <SkillCard
                  key={skill.id}
                  skill={skill}
                  selected={selectedSkill?.id === skill.id}
                  onSelect={() => setSelectedSkillId(skill.id)}
                  selectedForCompose={composeRefs.includes(skill.id)}
                  onToggleCompose={() => toggleCompose(skill)}
                />
              ))}
            </div>
          </div>

          <ComposePanel selectedRefs={composeRefs} result={composeResult} onCompose={runCompose} />
        </div>

        <div className="space-y-4">
          <DetailPanel skill={selectedSkill} onRunTest={runSkillTest} />

          <div className="rounded-xl border border-zinc-200 bg-white p-4">
            <h3 className="inline-flex items-center gap-2 text-sm font-semibold text-zinc-900">
              <Layers className="h-4 w-4" />
              Marketplace
            </h3>
            <p className="mt-1 text-xs text-zinc-600">
              Discover and install community skills for {tab === 'build' ? 'optimization' : 'runtime capability'} workflows.
            </p>
            <div className="mt-3 space-y-2">
              {marketQuery.isLoading && <p className="text-xs text-zinc-500">Loading marketplace…</p>}
              {!marketQuery.isLoading && listings.length === 0 && (
                <p className="text-xs text-zinc-500">No marketplace listings for this tab yet.</p>
              )}
              {listings.slice(0, 8).map((listing) => (
                <div key={listing.listing_id} className="flex items-start justify-between rounded-lg border border-zinc-200 bg-zinc-50 p-3">
                  <div>
                    <p className="text-xs font-semibold text-zinc-900">{listing.name}</p>
                    <p className="text-[11px] text-zinc-600">{listing.description}</p>
                    <p className="mt-1 text-[10px] text-zinc-500">
                      score {listing.score.toFixed(2)} | installs {listing.usage_count}
                    </p>
                  </div>
                  <button
                    onClick={() => installListing(listing.skill_id)}
                    className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-2.5 py-1 text-[11px] font-semibold text-zinc-700 hover:border-zinc-400"
                  >
                    <Puzzle className="h-3 w-3" />
                    Install
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-zinc-200 bg-white p-4">
            <h3 className="inline-flex items-center gap-2 text-sm font-semibold text-zinc-900">
              <Hammer className="h-4 w-4" />
              Leaderboard Snapshot
            </h3>
            <p className="mt-1 text-xs text-zinc-600">
              Top performers in this tab by effectiveness score.
            </p>
            <div className="mt-3 space-y-2">
              {[...skills]
                .sort((a, b) => skillScore(b) - skillScore(a))
                .slice(0, 5)
                .map((skill, index) => (
                  <div key={skill.id} className="flex items-center justify-between rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs">
                    <span className="font-medium text-zinc-700">
                      {index + 1}. {skill.id}
                    </span>
                    <span className="text-zinc-600">{skillScore(skill).toFixed(2)}</span>
                  </div>
                ))}
              {skills.length === 0 && <p className="text-xs text-zinc-500">No skills available.</p>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
