import { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useConfigs, useConversations, useEvalRuns } from '../lib/api';
import { getNavigationSections } from '../lib/navigation';
import { formatTimestamp, truncate } from '../lib/utils';

type PaletteItem = {
  id: string;
  label: string;
  description?: string;
  href: string;
  group: 'Navigation' | 'Actions' | 'Eval Runs' | 'Configs' | 'Conversations' | 'Smart Results';
};

const SMART_SEARCH_MAP: Array<{
  keywords: string[];
  label: string;
  description: string;
  href: string;
}> = [
  {
    keywords: ['why', 'routing', 'failing', 'failure', 'blame'],
    label: 'Diagnose routing failures',
    description: 'Jump to Blame Map filtered on routing_error',
    href: '/blame?filter=routing_error',
  },
  {
    keywords: ['fix', 'safety', 'violation'],
    label: 'Fix safety violations',
    description: 'Apply tighten-safety-policy runbook',
    href: '/runbooks?action=apply&runbook=tighten-safety-policy',
  },
  {
    keywords: ['what', 'changed', 'changes', 'diff'],
    label: 'What changed?',
    description: 'Open the unified review workflow',
    href: '/improvements?tab=review',
  },
  {
    keywords: ['show', 'failures', 'conversations', 'fail'],
    label: 'Show me failures',
    description: 'Browse failed conversations',
    href: '/conversations?outcome=fail',
  },
  {
    keywords: ['how', 'agent', 'doing', 'health', 'status'],
    label: 'How is my agent doing?',
    description: 'Open dashboard',
    href: '/dashboard',
  },
  {
    keywords: ['deploy', 'production', 'ship', 'release'],
    label: 'Deploy to production',
    description: 'Open CX Deploy page',
    href: '/cx/deploy',
  },
  {
    keywords: ['import', 'agent', 'cx', 'studio'],
    label: 'Import agent',
    description: 'Import from Vertex AI Agent Studio',
    href: '/cx/import',
  },
  {
    keywords: ['optimize', 'improve', 'run', 'cycle'],
    label: 'Run optimization',
    description: 'Start live optimization',
    href: '/live-optimize',
  },
  {
    keywords: ['compare', 'configs', 'diff', 'versions'],
    label: 'Compare configs',
    description: 'View config history',
    href: '/configs',
  },
];

const staticItems: PaletteItem[] = [
  ...getNavigationSections().map((section) => ({
    id: `nav-${section.group}`,
    label: section.label,
    description: section.description,
    href: section.items[0]?.path ?? '/build',
    group: 'Navigation' as const,
  })),
  ...getNavigationSections().flatMap((section) =>
    section.items.map((item) => ({
      id: `nav-item-${section.group}-${item.path}`,
      label: item.label,
      description: `${section.label} · ${section.description}`,
      href: item.path,
      group: 'Navigation' as const,
    }))
  ),
  {
    id: 'action-dashboard',
    label: 'Go to Dashboard',
    description: 'Open system health overview',
    href: '/dashboard',
    group: 'Actions',
  },
  {
    id: 'action-new-eval',
    label: 'New Eval Run',
    description: 'Open Eval Runs and prefill the launch form',
    href: '/evals?new=1',
    group: 'Actions',
  },
  {
    id: 'action-optimize',
    label: 'Run Optimization',
    description: 'Open optimization controls',
    href: '/optimize?new=1',
    group: 'Actions',
  },
  {
    id: 'action-deploy',
    label: 'Deploy Version',
    description: 'Open deployment flow',
    href: '/deploy?new=1',
    group: 'Actions',
  },
  {
    id: 'action-conversations',
    label: 'Inspect Conversations',
    description: 'Browse recent failures and tool calls',
    href: '/conversations',
    group: 'Actions',
  },
];

function matches(text: string, query: string): boolean {
  return text.toLowerCase().includes(query.toLowerCase());
}

function smartSearch(query: string): PaletteItem[] {
  const tokens = query.toLowerCase().split(/\s+/);
  const results: Array<{ item: typeof SMART_SEARCH_MAP[0], score: number }> = [];

  for (const item of SMART_SEARCH_MAP) {
    let score = 0;
    for (const token of tokens) {
      for (const keyword of item.keywords) {
        if (keyword.includes(token)) {
          score += token.length / keyword.length;  // Partial match scoring
        }
      }
    }
    if (score > 0) {
      results.push({ item, score });
    }
  }

  return results
    .sort((a, b) => b.score - a.score)
    .slice(0, 5)
    .map((r, index) => ({
      id: `smart-${index}`,
      label: r.item.label,
      description: r.item.description,
      href: r.item.href,
      group: 'Smart Results' as const,
    }));
}

export function CommandPalette() {
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  const { data: runs } = useEvalRuns();
  const { data: configs } = useConfigs();
  const { data: conversations } = useConversations({ limit: 15 });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const isCmdK = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k';
      if (!isCmdK) return;
      event.preventDefault();
      setIsOpen((state) => !state);
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    const openHandler = () => setIsOpen(true);
    window.addEventListener('open-command-palette', openHandler);
    return () => window.removeEventListener('open-command-palette', openHandler);
  }, []);

  useEffect(() => {
    if (!isOpen) {
      setQuery('');
      setSelectedIndex(0);
    }
  }, [isOpen]);

  const dynamicItems = useMemo<PaletteItem[]>(() => {
    const runItems: PaletteItem[] = (runs || []).slice(0, 6).map((run) => ({
      id: `run-${run.run_id}`,
      label: `Run ${run.run_id.slice(0, 8)}`,
      description: `${run.status} · Score ${run.composite_score.toFixed(1)}`,
      href: `/evals/${run.run_id}`,
      group: 'Eval Runs',
    }));

    const configItems: PaletteItem[] = (configs || []).slice(0, 6).map((config) => ({
      id: `config-${config.version}`,
      label: `Config v${config.version}`,
      description: `${config.status} · ${formatTimestamp(config.timestamp)}`,
      href: '/configs',
      group: 'Configs',
    }));

    const conversationItems: PaletteItem[] = (conversations || []).slice(0, 6).map((conversation) => ({
      id: `conversation-${conversation.conversation_id}`,
      label: `Conversation ${conversation.conversation_id.slice(0, 8)}`,
      description: truncate(conversation.user_message, 70),
      href: '/conversations',
      group: 'Conversations',
    }));

    return [...staticItems, ...runItems, ...configItems, ...conversationItems];
  }, [configs, conversations, runs]);

  const filteredItems = useMemo(() => {
    if (!query.trim()) return dynamicItems;

    // Get smart search results
    const smartResults = smartSearch(query);

    // Get regular filtered results
    const regularResults = dynamicItems.filter((item) => {
      const text = `${item.label} ${item.description || ''} ${item.group}`;
      return matches(text, query);
    });

    // Combine smart results first, then regular results
    return [...smartResults, ...regularResults];
  }, [dynamicItems, query]);

  const grouped = useMemo(() => {
    return filteredItems.reduce<Record<string, PaletteItem[]>>((accumulator, item) => {
      if (!accumulator[item.group]) {
        accumulator[item.group] = [];
      }
      accumulator[item.group].push(item);
      return accumulator;
    }, {});
  }, [filteredItems]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  function handleNavigate(href: string) {
    navigate(href);
    setIsOpen(false);
  }

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'Escape') {
      setIsOpen(false);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, filteredItems.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter' && filteredItems[selectedIndex]) {
      handleNavigate(filteredItems[selectedIndex].href);
    }
  }

  if (!isOpen) return null;

  let flatIndex = 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/25 px-4 pt-[12vh] backdrop-blur-[2px]"
      onClick={() => setIsOpen(false)}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-gray-100 px-3.5 py-2.5">
          <Search className="h-4 w-4 text-gray-300" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search..."
            className="w-full border-none bg-transparent text-sm text-gray-900 outline-none placeholder:text-gray-400"
            autoFocus
          />
          <kbd className="rounded border border-gray-200 px-1.5 py-0.5 font-mono text-[10px] text-gray-400">
            esc
          </kbd>
        </div>

        <div className="max-h-[50vh] overflow-y-auto py-2">
          {filteredItems.length === 0 && (
            <p className="px-3.5 py-8 text-center text-sm text-gray-400">No results</p>
          )}

          {Object.entries(grouped).map(([groupName, entries]) => (
            <div key={groupName} className="mb-1 last:mb-0">
              <p className="px-3.5 py-1.5 text-[11px] font-medium text-gray-400">
                {groupName}
              </p>
              {entries.map((entry) => {
                const currentIndex = flatIndex++;
                return (
                  <button
                    key={entry.id}
                    onClick={() => handleNavigate(entry.href)}
                    aria-label={entry.label}
                    className={`flex w-full items-center gap-3 px-3.5 py-2 text-left text-sm transition-colors ${
                      currentIndex === selectedIndex
                        ? 'bg-gray-100 text-gray-900'
                        : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">
                        {entry.group === 'Smart Results' && '✨ '}
                        {entry.label}
                      </p>
                      {entry.description && (
                        <p className="truncate text-xs text-gray-400">{entry.description}</p>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
