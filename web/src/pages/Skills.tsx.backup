import { useState } from 'react';
import { Search, Zap, Shield, Clock, Star, Package, Filter, ChevronRight, X, TrendingUp, Award } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { classNames } from '../lib/utils';
import { useSkills, useSkillRecommendations, useSkillStats, useApplySkill } from '../lib/api';
import { toastSuccess, toastError } from '../lib/toast';
import type { ExecutableSkill, SkillLeaderboardEntry } from '../lib/types';

// ---------------------------------------------------------------------------
// Category config
// ---------------------------------------------------------------------------

const CATEGORIES = ['All', 'Routing', 'Safety', 'Latency', 'Quality', 'Cost'] as const;
const PLATFORMS = ['All', 'Universal', 'CX Agent Studio'] as const;

type CategoryFilter = (typeof CATEGORIES)[number];
type PlatformFilter = (typeof PLATFORMS)[number];

interface CategoryStyle {
  badge: string;
  icon: React.ComponentType<{ className?: string }>;
}

const CATEGORY_STYLES: Record<string, CategoryStyle> = {
  routing:  { badge: 'bg-blue-50 text-blue-700',   icon: ChevronRight },
  safety:   { badge: 'bg-red-50 text-red-700',     icon: Shield },
  latency:  { badge: 'bg-amber-50 text-amber-700', icon: Clock },
  quality:  { badge: 'bg-green-50 text-green-700', icon: Star },
  cost:     { badge: 'bg-purple-50 text-purple-700', icon: Zap },
};

function getCategoryStyle(category: string): CategoryStyle {
  return CATEGORY_STYLES[category.toLowerCase()] ?? { badge: 'bg-gray-100 text-gray-600', icon: Package };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CategoryBadge({ category }: { category: string }) {
  const style = getCategoryStyle(category);
  return (
    <span className={classNames('rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide', style.badge)}>
      {category}
    </span>
  );
}

function StatPill({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col">
      <span className="text-[11px] text-gray-400">{label}</span>
      <span className="text-[13px] font-semibold text-gray-800">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill Card
// ---------------------------------------------------------------------------

interface SkillCardProps {
  skill: ExecutableSkill;
  onClick: () => void;
  recommended?: boolean;
}

function SkillCard({ skill, onClick, recommended = false }: SkillCardProps) {
  const successPct = Math.round(skill.success_rate * 100);
  const improvementPct = skill.proven_improvement != null ? Math.round(skill.proven_improvement * 100) : null;

  return (
    <button
      onClick={onClick}
      className={classNames(
        'group flex w-full flex-col gap-3 rounded-xl border bg-white p-4 text-left transition hover:border-gray-300 hover:shadow-sm',
        recommended ? 'border-blue-200 ring-1 ring-blue-100' : 'border-gray-200'
      )}
    >
      {/* Top row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            {recommended && (
              <span className="rounded-md bg-blue-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
                Recommended
              </span>
            )}
            <CategoryBadge category={skill.category} />
          </div>
          <p className="mt-1.5 font-mono text-sm font-medium text-gray-900 truncate">{skill.name}</p>
        </div>
        <ChevronRight className="h-4 w-4 shrink-0 text-gray-300 transition group-hover:text-gray-500" />
      </div>

      {/* Description */}
      <p className="text-[13px] leading-5 text-gray-500 line-clamp-2">{skill.description}</p>

      {/* Platform */}
      <div className="flex items-center gap-1.5">
        <Package className="h-3.5 w-3.5 text-gray-400" />
        <span className="text-[12px] text-gray-400">{skill.platform}</span>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 border-t border-gray-100 pt-3">
        <StatPill label="Success rate" value={`${successPct}%`} />
        <StatPill label="Applied" value={skill.times_applied.toLocaleString()} />
        {improvementPct != null && (
          <StatPill label="Improvement" value={`+${improvementPct}%`} />
        )}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Detail Modal
// ---------------------------------------------------------------------------

interface DetailModalProps {
  skill: ExecutableSkill;
  onClose: () => void;
}

function DetailModal({ skill, onClose }: DetailModalProps) {
  const [confirming, setConfirming] = useState(false);
  const applyMutation = useApplySkill();

  const successPct = Math.round(skill.success_rate * 100);
  const improvementPct = skill.proven_improvement != null ? Math.round(skill.proven_improvement * 100) : null;

  function handleApply() {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    applyMutation.mutate(skill.name, {
      onSuccess: () => {
        toastSuccess('Skill applied', `${skill.name} has been applied.`);
        setConfirming(false);
        onClose();
      },
      onError: (err) => {
        toastError('Apply failed', err.message);
        setConfirming(false);
      },
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Panel */}
      <div className="relative z-10 flex max-h-[90vh] w-full max-w-2xl flex-col rounded-2xl border border-gray-200 bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-gray-100 px-6 py-5">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <CategoryBadge category={skill.category} />
              <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                v{skill.version}
              </span>
              <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                {skill.status}
              </span>
            </div>
            <h2 className="mt-1.5 font-mono text-base font-semibold text-gray-900">{skill.name}</h2>
            <p className="mt-1 text-[13px] text-gray-500">{skill.description}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* Key stats */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
              <p className="text-[11px] text-gray-400">Success rate</p>
              <p className="mt-0.5 text-lg font-bold text-gray-900">{successPct}%</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
              <p className="text-[11px] text-gray-400">Times applied</p>
              <p className="mt-0.5 text-lg font-bold text-gray-900">{skill.times_applied.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
              <p className="text-[11px] text-gray-400">Improvement</p>
              <p className="mt-0.5 text-lg font-bold text-gray-900">
                {improvementPct != null ? `+${improvementPct}%` : '—'}
              </p>
            </div>
          </div>

          {/* Platform + surfaces */}
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">Platform &amp; Surfaces</h3>
            <div className="flex flex-wrap gap-1.5">
              <span className="rounded-md border border-gray-200 bg-white px-2 py-0.5 text-[12px] text-gray-600">
                {skill.platform}
              </span>
              {skill.target_surfaces.map((s) => (
                <span key={s} className="rounded-md border border-gray-200 bg-white px-2 py-0.5 text-[12px] text-gray-600">
                  {s}
                </span>
              ))}
            </div>
          </div>

          {/* Mutations */}
          {skill.mutations.length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                Mutations ({skill.mutations.length})
              </h3>
              <div className="space-y-2">
                {skill.mutations.map((m) => (
                  <div key={m.name} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-[12px] font-semibold text-gray-800">{m.name}</span>
                      <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
                        {m.mutation_type}
                      </span>
                      <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
                        {m.target_surface}
                      </span>
                    </div>
                    <p className="text-[12px] text-gray-500">{m.description}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Examples */}
          {skill.examples.length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                Examples ({skill.examples.length})
              </h3>
              <div className="space-y-3">
                {skill.examples.map((ex, i) => (
                  <div key={i} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-mono text-[12px] font-semibold text-gray-800">{ex.name}</span>
                      <span className="text-[11px] font-semibold text-green-600">+{Math.round(ex.improvement * 100)}%</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <p className="mb-1 text-[10px] font-semibold uppercase text-gray-400">Before</p>
                        <pre className="overflow-auto rounded border border-gray-200 bg-white p-2 text-[11px] text-gray-600 max-h-24">
                          {typeof ex.before === 'string' ? ex.before : JSON.stringify(ex.before, null, 2)}
                        </pre>
                      </div>
                      <div>
                        <p className="mb-1 text-[10px] font-semibold uppercase text-gray-400">After</p>
                        <pre className="overflow-auto rounded border border-gray-200 bg-white p-2 text-[11px] text-gray-600 max-h-24">
                          {typeof ex.after === 'string' ? ex.after : JSON.stringify(ex.after, null, 2)}
                        </pre>
                      </div>
                    </div>
                    {ex.context && (
                      <p className="mt-2 text-[11px] text-gray-400">{ex.context}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Guardrails */}
          {skill.guardrails.length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                Guardrails
              </h3>
              <ul className="space-y-1">
                {skill.guardrails.map((g, i) => (
                  <li key={i} className="flex items-start gap-2 text-[13px] text-gray-600">
                    <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                    {g}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Eval criteria */}
          {skill.eval_criteria.length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                Eval Criteria
              </h3>
              <div className="space-y-1">
                {skill.eval_criteria.map((ec, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2"
                  >
                    <span className="font-mono text-[12px] text-gray-700">{ec.metric}</span>
                    <div className="flex items-center gap-3 text-[12px] text-gray-500">
                      <span>{ec.operator} {ec.target}</span>
                      <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px]">w={ec.weight}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tags */}
          {skill.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {skill.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full border border-gray-200 bg-white px-2.5 py-0.5 text-[11px] text-gray-500"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-gray-100 px-6 py-4">
          <p className="text-[12px] text-gray-400">Author: {skill.author}</p>
          <div className="flex items-center gap-2">
            {confirming && (
              <span className="text-[12px] text-amber-600">Are you sure? This will apply the skill.</span>
            )}
            {confirming && (
              <button
                onClick={() => setConfirming(false)}
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
            )}
            <button
              onClick={handleApply}
              disabled={applyMutation.isPending}
              className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
            >
              <Zap className="h-3.5 w-3.5" />
              {confirming ? 'Confirm Apply' : 'Apply Skill'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats Panel
// ---------------------------------------------------------------------------

function StatsPanel({ leaderboard }: { leaderboard: SkillLeaderboardEntry[] }) {
  const top5 = leaderboard.slice(0, 5);
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700">
        <Award className="h-4 w-4 text-amber-500" />
        Top Performers
      </h3>
      <div className="space-y-2">
        {top5.map((entry, i) => {
          const successPct = Math.round(entry.success_rate * 100);
          const improvePct = entry.proven_improvement != null ? Math.round(entry.proven_improvement * 100) : null;
          return (
            <div key={entry.name} className="flex items-center gap-3">
              <span className="w-4 shrink-0 text-[12px] font-semibold text-gray-400">#{i + 1}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-[12px] font-medium text-gray-800">{entry.name}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <CategoryBadge category={entry.category} />
                  <span className="text-[11px] text-gray-400">{successPct}% success</span>
                  {improvePct != null && (
                    <span className="text-[11px] font-semibold text-green-600">+{improvePct}%</span>
                  )}
                </div>
              </div>
              <span className="shrink-0 text-[11px] text-gray-400">{entry.times_applied}x</span>
            </div>
          );
        })}
        {top5.length === 0 && (
          <p className="text-[13px] text-gray-400">No data yet.</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function Skills() {
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('All');
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>('All');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSkill, setSelectedSkill] = useState<ExecutableSkill | null>(null);

  const apiCategory = categoryFilter === 'All' ? undefined : categoryFilter.toLowerCase();
  const apiPlatform = platformFilter === 'All' ? undefined : platformFilter;

  const skillsQuery = useSkills(apiCategory, apiPlatform);
  const recommendQuery = useSkillRecommendations();
  const statsQuery = useSkillStats();

  const allSkills = skillsQuery.data?.skills ?? [];
  const recommendedSkills = recommendQuery.data?.skills ?? [];
  const leaderboard = statsQuery.data?.leaderboard ?? [];

  const recommendedNames = new Set(recommendedSkills.map((s) => s.name));

  // Client-side search on top of server-side category/platform filter
  const filtered = allSkills.filter((s) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      s.name.toLowerCase().includes(q) ||
      s.description.toLowerCase().includes(q) ||
      s.tags.some((t) => t.toLowerCase().includes(q))
    );
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Skills"
        description="Executable optimization strategies — the knowledge base powering the optimizer"
      />

      {/* Recommended section */}
      {recommendedSkills.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-blue-500" />
            <h2 className="text-sm font-semibold text-gray-700">Recommended for you</h2>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-600">
              {recommendedSkills.length}
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {recommendedSkills.map((skill) => (
              <SkillCard
                key={skill.name}
                skill={skill}
                recommended
                onClick={() => setSelectedSkill(skill)}
              />
            ))}
          </div>
        </section>
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3">
        <Filter className="h-4 w-4 shrink-0 text-gray-400" />

        {/* Search */}
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Search className="h-4 w-4 shrink-0 text-gray-400" />
          <input
            type="text"
            placeholder="Search skills..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-transparent text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none"
          />
        </div>

        {/* Category dropdown */}
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value as CategoryFilter)}
          className="rounded-lg border border-gray-200 bg-white py-1.5 pl-2.5 pr-7 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-900/10"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>

        {/* Platform dropdown */}
        <select
          value={platformFilter}
          onChange={(e) => setPlatformFilter(e.target.value as PlatformFilter)}
          className="rounded-lg border border-gray-200 bg-white py-1.5 pl-2.5 pr-7 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-900/10"
        >
          {PLATFORMS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      {/* Main content + sidebar */}
      <div className="flex gap-6">
        {/* Grid */}
        <div className="min-w-0 flex-1">
          {skillsQuery.isLoading && (
            <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              Loading skills...
            </div>
          )}
          {skillsQuery.isError && (
            <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
              Failed to load skills.
            </div>
          )}
          {!skillsQuery.isLoading && !skillsQuery.isError && (
            <>
              {filtered.length === 0 ? (
                <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
                  No skills match your filters.
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {filtered.map((skill) => (
                    <SkillCard
                      key={skill.name}
                      skill={skill}
                      recommended={recommendedNames.has(skill.name)}
                      onClick={() => setSelectedSkill(skill)}
                    />
                  ))}
                </div>
              )}
              <p className="mt-3 text-[12px] text-gray-400">
                {filtered.length} skill{filtered.length !== 1 ? 's' : ''} shown
              </p>
            </>
          )}
        </div>

        {/* Stats sidebar */}
        {leaderboard.length > 0 && (
          <aside className="hidden w-64 shrink-0 xl:block">
            <StatsPanel leaderboard={leaderboard} />
          </aside>
        )}
      </div>

      {/* Detail modal */}
      {selectedSkill && (
        <DetailModal skill={selectedSkill} onClose={() => setSelectedSkill(null)} />
      )}
    </div>
  );
}
