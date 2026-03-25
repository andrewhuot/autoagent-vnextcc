import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, ChevronDown, ChevronRight, BookOpen, Tag, Play, FileCode, Shield, ArrowLeftRight } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { useRunbooks, useRunbookDetail, useApplyRunbook } from '../lib/api';
import { classNames } from '../lib/utils';
import { toastSuccess, toastError } from '../lib/toast';
import type { Runbook } from '../lib/types';

export function Runbooks() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [expandedName, setExpandedName] = useState<string | null>(null);

  const { data: runbooks = [], isLoading, isError } = useRunbooks();
  const detailQuery = useRunbookDetail(expandedName ?? undefined);
  const applyMutation = useApplyRunbook();

  // Collect all unique tags
  const allTags = Array.from(new Set(runbooks.flatMap((p) => p.tags))).sort();

  // Filter runbooks
  const filtered = runbooks.filter((p) => {
    const matchesSearch =
      !searchQuery.trim() ||
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesTag = !selectedTag || p.tags.includes(selectedTag);
    return matchesSearch && matchesTag;
  });

  function handleApply(name: string) {
    applyMutation.mutate(
      { name },
      {
        onSuccess: () => {
          toastSuccess('Runbook applied', `${name} has been applied.`);
        },
        onError: (error) => {
          toastError('Apply failed', error.message);
        },
      }
    );
  }

  function toggleExpand(name: string) {
    setExpandedName((current) => (current === name ? null : name));
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Runbooks"
        description="Browse and apply runbooks — curated bundles of skills, policies, and tool contracts"
        actions={
          <Link
            to="/registry"
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
          >
            <BookOpen className="h-4 w-4" />
            View Components
          </Link>
        }
      />

      {/* Search */}
      <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3">
        <Search className="h-4 w-4 shrink-0 text-gray-400" />
        <input
          type="text"
          placeholder="Search runbooks..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full bg-transparent text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none"
        />
      </div>

      {/* Tag filter */}
      {allTags.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 rounded-xl border border-gray-200 bg-white px-2 py-2">
          <button
            onClick={() => setSelectedTag(null)}
            className={classNames(
              'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
              !selectedTag
                ? 'bg-gray-900 text-white'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
            )}
          >
            All
          </button>
          {allTags.map((tag) => (
            <button
              key={tag}
              onClick={() => setSelectedTag(tag === selectedTag ? null : tag)}
              className={classNames(
                'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                selectedTag === tag
                  ? 'bg-gray-900 text-white'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              )}
            >
              <Tag className="h-3.5 w-3.5" />
              {tag}
            </button>
          ))}
        </div>
      )}

      {/* Loading / error */}
      {isLoading && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading runbooks...
        </div>
      )}
      {isError && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load runbooks.
        </div>
      )}

      {/* Runbook list */}
      {!isLoading && !isError && (
        <div className="space-y-2">
          {filtered.length === 0 ? (
            <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              No runbooks found.
            </div>
          ) : (
            filtered.map((runbook) => {
              const isExpanded = expandedName === runbook.name;
              const detail = isExpanded ? detailQuery.data : null;

              return (
                <div
                  key={runbook.name}
                  className="rounded-xl border border-gray-200 bg-white transition-colors"
                >
                  {/* Runbook header */}
                  <div className="flex items-center gap-3 px-4 py-3">
                    <button
                      onClick={() => toggleExpand(runbook.name)}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    >
                      {isExpanded ? (
                        <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
                      ) : (
                        <ChevronRight className="h-4 w-4 shrink-0 text-gray-400" />
                      )}
                      <div className="min-w-0 flex-1">
                        <span className="font-mono text-sm font-medium text-gray-900">{runbook.name}</span>
                        <p className="mt-0.5 truncate text-xs text-gray-500">{runbook.description}</p>
                      </div>
                    </button>

                    <div className="flex items-center gap-2">
                      {runbook.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700"
                        >
                          {tag}
                        </span>
                      ))}
                      <button
                        onClick={() => handleApply(runbook.name)}
                        disabled={applyMutation.isPending}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
                      >
                        <Play className="h-3 w-3" />
                        Apply
                      </button>
                    </div>
                  </div>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div className="border-t border-gray-100 px-4 py-4">
                      {detailQuery.isLoading && (
                        <p className="text-sm text-gray-500">Loading details...</p>
                      )}
                      {detail && (
                        <div className="grid gap-4 sm:grid-cols-3">
                          {/* Skills */}
                          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                            <h4 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-gray-500">
                              <FileCode className="h-3.5 w-3.5" />
                              Skills ({detail.skills.length})
                            </h4>
                            {detail.skills.length === 0 ? (
                              <p className="text-xs text-gray-400">None</p>
                            ) : (
                              <ul className="space-y-1">
                                {detail.skills.map((s) => (
                                  <li key={s} className="font-mono text-xs text-gray-700">
                                    {s}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>

                          {/* Policies */}
                          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                            <h4 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-gray-500">
                              <Shield className="h-3.5 w-3.5" />
                              Policies ({detail.policies.length})
                            </h4>
                            {detail.policies.length === 0 ? (
                              <p className="text-xs text-gray-400">None</p>
                            ) : (
                              <ul className="space-y-1">
                                {detail.policies.map((p) => (
                                  <li key={p} className="font-mono text-xs text-gray-700">
                                    {p}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>

                          {/* Tool Contracts */}
                          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                            <h4 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-gray-500">
                              <ArrowLeftRight className="h-3.5 w-3.5" />
                              Tool Contracts ({detail.tool_contracts.length})
                            </h4>
                            {detail.tool_contracts.length === 0 ? (
                              <p className="text-xs text-gray-400">None</p>
                            ) : (
                              <ul className="space-y-1">
                                {detail.tool_contracts.map((tc) => (
                                  <li key={tc} className="font-mono text-xs text-gray-700">
                                    {tc}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
