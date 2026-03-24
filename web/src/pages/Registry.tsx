import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, ChevronDown, ChevronRight, BookOpen, Tag, FileCode, ArrowLeftRight } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { classNames } from '../lib/utils';

const API_BASE = '/api';

const registryTypes = [
  { key: 'skills', label: 'Skills', icon: FileCode },
  { key: 'policies', label: 'Policies', icon: BookOpen },
  { key: 'tool_contracts', label: 'Tool Contracts', icon: Tag },
  { key: 'handoff_schemas', label: 'Handoff Schemas', icon: ArrowLeftRight },
] as const;

type RegistryType = (typeof registryTypes)[number]['key'];

interface RegistryItem {
  name: string;
  description: string;
  version: number;
  updated_at: string;
}

interface RegistryItemDetail {
  name: string;
  description: string;
  version: number;
  updated_at: string;
  content: string;
  versions: { version: number; updated_at: string; author: string }[];
}

interface DiffResult {
  diff: string;
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export function Registry() {
  const [activeType, setActiveType] = useState<RegistryType>('skills');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedItem, setExpandedItem] = useState<string | null>(null);
  const [diffVersions, setDiffVersions] = useState<{ v1: number; v2: number } | null>(null);

  const listQuery = useQuery({
    queryKey: ['registry', activeType, searchQuery],
    queryFn: () =>
      searchQuery.trim()
        ? fetchJson<RegistryItem[]>(`/registry/search?q=${encodeURIComponent(searchQuery)}&type=${activeType}`)
        : fetchJson<RegistryItem[]>(`/registry/${activeType}`),
  });

  const detailQuery = useQuery({
    queryKey: ['registry', activeType, expandedItem],
    queryFn: () => fetchJson<RegistryItemDetail>(`/registry/${activeType}/${expandedItem}`),
    enabled: !!expandedItem,
  });

  const diffQuery = useQuery({
    queryKey: ['registry-diff', activeType, expandedItem, diffVersions?.v1, diffVersions?.v2],
    queryFn: () =>
      fetchJson<DiffResult>(
        `/registry/${activeType}/${expandedItem}/diff?v1=${diffVersions!.v1}&v2=${diffVersions!.v2}`
      ),
    enabled: !!expandedItem && !!diffVersions,
  });

  function toggleItem(name: string) {
    setExpandedItem((current) => (current === name ? null : name));
    setDiffVersions(null);
  }

  const items = listQuery.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Registry Browser"
        description="Browse and inspect skills, policies, tool contracts, and handoff schemas"
      />

      {/* Tab navigation */}
      <div className="flex flex-wrap items-center gap-1 rounded-xl border border-gray-200 bg-white px-2 py-2">
        {registryTypes.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => {
              setActiveType(key);
              setExpandedItem(null);
              setDiffVersions(null);
            }}
            className={classNames(
              'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
              activeType === key
                ? 'bg-gray-900 text-white'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3">
        <Search className="h-4 w-4 shrink-0 text-gray-400" />
        <input
          type="text"
          placeholder={`Search ${registryTypes.find((t) => t.key === activeType)?.label ?? ''}...`}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full bg-transparent text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none"
        />
      </div>

      {/* Loading / error states */}
      {listQuery.isLoading && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading registry items...
        </div>
      )}
      {listQuery.isError && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load registry items.
        </div>
      )}

      {/* Item list */}
      {!listQuery.isLoading && !listQuery.isError && (
        <div className="space-y-2">
          {items.length === 0 ? (
            <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              No items found.
            </div>
          ) : (
            items.map((item) => {
              const isExpanded = expandedItem === item.name;
              const detail = isExpanded ? detailQuery.data : null;

              return (
                <div
                  key={item.name}
                  className="rounded-xl border border-gray-200 bg-white transition-colors"
                >
                  {/* Item header */}
                  <button
                    onClick={() => toggleItem(item.name)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left"
                  >
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0 text-gray-400" />
                    )}
                    <span className="font-mono text-sm font-medium text-gray-900">{item.name}</span>
                    <span className="text-xs text-gray-500">{item.description}</span>
                    <span className="ml-auto rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                      v{item.version}
                    </span>
                  </button>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div className="border-t border-gray-100 px-4 py-4">
                      {detailQuery.isLoading && (
                        <p className="text-sm text-gray-500">Loading details...</p>
                      )}
                      {detail && (
                        <div className="space-y-4">
                          {/* Content */}
                          <div>
                            <h4 className="text-xs font-medium text-gray-500">Content</h4>
                            <pre className="mt-1 max-h-64 overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
                              {detail.content}
                            </pre>
                          </div>

                          {/* Version history */}
                          <div>
                            <h4 className="text-xs font-medium text-gray-500">Version History</h4>
                            <div className="mt-2 space-y-1">
                              {detail.versions.map((v) => (
                                <div
                                  key={v.version}
                                  className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2"
                                >
                                  <div className="flex items-center gap-3">
                                    <span className="rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                                      v{v.version}
                                    </span>
                                    <span className="text-xs text-gray-500">{v.author}</span>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs text-gray-400">{v.updated_at}</span>
                                    {v.version > 1 && (
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setDiffVersions({ v1: v.version - 1, v2: v.version });
                                        }}
                                        className="rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-600 hover:bg-gray-50"
                                      >
                                        Diff
                                      </button>
                                    )}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>

                          {/* Diff viewer */}
                          {diffVersions && (
                            <div>
                              <h4 className="text-xs font-medium text-gray-500">
                                Diff: v{diffVersions.v1} → v{diffVersions.v2}
                              </h4>
                              {diffQuery.isLoading && (
                                <p className="mt-1 text-sm text-gray-500">Loading diff...</p>
                              )}
                              {diffQuery.data && (
                                <pre className="mt-1 max-h-80 overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs">
                                  {diffQuery.data.diff.split('\n').map((line, i) => (
                                    <div
                                      key={i}
                                      className={classNames(
                                        'px-1',
                                        line.startsWith('+') ? 'bg-green-50 text-green-800' : '',
                                        line.startsWith('-') ? 'bg-red-50 text-red-800' : '',
                                        !line.startsWith('+') && !line.startsWith('-') ? 'text-gray-600' : ''
                                      )}
                                    >
                                      {line}
                                    </div>
                                  ))}
                                </pre>
                              )}
                            </div>
                          )}
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
