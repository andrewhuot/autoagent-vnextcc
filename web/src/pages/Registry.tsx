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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function summarizeRegistryItem(data: Record<string, unknown>): string {
  if (typeof data.description === 'string' && data.description.trim()) {
    return data.description;
  }
  if (typeof data.instructions === 'string' && data.instructions.trim()) {
    return data.instructions.trim().split('\n')[0] ?? 'Instructions available';
  }
  if (Array.isArray(data.rules) && data.rules.length > 0) {
    return `${data.rules.length} rule${data.rules.length === 1 ? '' : 's'}`;
  }
  if (typeof data.tool_name === 'string' && data.tool_name.trim()) {
    return `Tool contract for ${data.tool_name}`;
  }
  if (typeof data.from_agent === 'string' && typeof data.to_agent === 'string') {
    return `${data.from_agent} -> ${data.to_agent}`;
  }
  return 'No description available';
}

function normalizeRegistryItem(raw: unknown): RegistryItem {
  const item = isRecord(raw) ? raw : {};
  const data = isRecord(item.data) ? item.data : {};

  return {
    name: typeof item.name === 'string' ? item.name : 'unknown',
    description: summarizeRegistryItem(data),
    version: typeof item.version === 'number' ? item.version : 1,
    updated_at: typeof item.created_at === 'string' ? item.created_at : '',
  };
}

function normalizeRegistryDetail(payload: unknown): RegistryItemDetail | null {
  const wrapper = isRecord(payload) ? payload : {};
  const rawItem = isRecord(wrapper.item) ? wrapper.item : wrapper;
  if (!isRecord(rawItem)) {
    return null;
  }

  const data = isRecord(rawItem.data) ? rawItem.data : {};
  const metadata = isRecord(data.metadata) ? data.metadata : {};

  return {
    name: typeof rawItem.name === 'string' ? rawItem.name : 'unknown',
    description: summarizeRegistryItem(data),
    version: typeof rawItem.version === 'number' ? rawItem.version : 1,
    updated_at: typeof rawItem.created_at === 'string' ? rawItem.created_at : '',
    content: JSON.stringify(data, null, 2),
    versions: [
      {
        version: typeof rawItem.version === 'number' ? rawItem.version : 1,
        updated_at: typeof rawItem.created_at === 'string' ? rawItem.created_at : '',
        author: typeof metadata.author === 'string' ? metadata.author : 'system',
      },
    ],
  };
}

function normalizeDiff(payload: unknown): DiffResult {
  const data = isRecord(payload) ? payload : {};
  const changes = Array.isArray(data.changes) ? data.changes : [];

  if (changes.length === 0) {
    return { diff: 'No differences found.' };
  }

  return {
    diff: changes
      .filter(isRecord)
      .map((change) => {
        const field = typeof change.field === 'string' ? change.field : 'unknown';
        const oldValue = JSON.stringify(change.old, null, 2) ?? 'null';
        const newValue = JSON.stringify(change.new, null, 2) ?? 'null';
        return `Field: ${field}\n- ${oldValue}\n+ ${newValue}`;
      })
      .join('\n\n'),
  };
}

export function Registry() {
  const [activeType, setActiveType] = useState<RegistryType>('skills');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedItem, setExpandedItem] = useState<string | null>(null);
  const [diffVersions, setDiffVersions] = useState<{ v1: number; v2: number } | null>(null);

  const listQuery = useQuery<RegistryItem[]>({
    queryKey: ['registry', activeType, searchQuery],
    queryFn: async () => {
      if (searchQuery.trim()) {
        const payload = await fetchJson<{ results?: unknown[] }>(
          `/registry/search?q=${encodeURIComponent(searchQuery)}&type=${activeType}`
        );
        return (payload.results ?? []).map(normalizeRegistryItem);
      }

      const payload = await fetchJson<{ items?: unknown[] }>(`/registry/${activeType}`);
      return (payload.items ?? []).map(normalizeRegistryItem);
    },
  });

  const detailQuery = useQuery({
    queryKey: ['registry', activeType, expandedItem],
    queryFn: async () => {
      const payload = await fetchJson<unknown>(`/registry/${activeType}/${expandedItem}`);
      return normalizeRegistryDetail(payload);
    },
    enabled: !!expandedItem,
  });

  const diffQuery = useQuery({
    queryKey: ['registry-diff', activeType, expandedItem, diffVersions?.v1, diffVersions?.v2],
    queryFn: async () => {
      const payload = await fetchJson<unknown>(
        `/registry/${activeType}/${expandedItem}/diff?v1=${diffVersions!.v1}&v2=${diffVersions!.v2}`
      );
      return normalizeDiff(payload);
    },
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
