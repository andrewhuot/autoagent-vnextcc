import { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useConfigs, useConversations, useEvalRuns } from '../lib/api';
import { formatTimestamp, truncate } from '../lib/utils';

type PaletteItem = {
  id: string;
  label: string;
  description?: string;
  href: string;
  group: 'Actions' | 'Eval Runs' | 'Configs' | 'Conversations';
};

const staticItems: PaletteItem[] = [
  {
    id: 'action-dashboard',
    label: 'Go to Dashboard',
    description: 'Open system health overview',
    href: '/',
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

export function CommandPalette() {
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');

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
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    window.addEventListener('keydown', onEscape);
    return () => window.removeEventListener('keydown', onEscape);
  }, []);

  const dynamicItems = useMemo<PaletteItem[]>(() => {
    const runItems: PaletteItem[] = (runs || []).slice(0, 6).map((run) => ({
      id: `run-${run.run_id}`,
      label: `Run ${run.run_id.slice(0, 8)} · ${run.status}`,
      description: `Score ${run.composite_score.toFixed(1)} · ${run.passed_cases}/${run.total_cases} passed`,
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
    if (!query.trim()) {
      return dynamicItems;
    }

    return dynamicItems.filter((item) => {
      const text = `${item.label} ${item.description || ''} ${item.group}`;
      return matches(text, query);
    });
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

  function handleNavigate(href: string) {
    navigate(href);
    setIsOpen(false);
    setQuery('');
  }

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/20 px-4 pt-[8vh] backdrop-blur-[2px]">
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl">
        <div className="flex items-center gap-3 border-b border-gray-200 px-4 py-3">
          <Search className="h-4 w-4 text-gray-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search evals, configs, conversations, and actions"
            className="w-full border-none text-sm text-gray-900 outline-none placeholder:text-gray-400"
            autoFocus
          />
          <kbd className="rounded border border-gray-200 bg-gray-50 px-2 py-1 font-mono text-[10px] text-gray-500">
            esc
          </kbd>
        </div>

        <div className="max-h-[60vh] overflow-y-auto p-3">
          {filteredItems.length === 0 && (
            <p className="px-2 py-6 text-center text-sm text-gray-500">No matches found.</p>
          )}

          {Object.entries(grouped).map(([groupName, entries]) => (
            <div key={groupName} className="mb-4 last:mb-0">
              <p className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                {groupName}
              </p>
              <div className="space-y-1">
                {entries.map((entry) => (
                  <button
                    key={entry.id}
                    onClick={() => handleNavigate(entry.href)}
                    className="w-full rounded-lg px-3 py-2 text-left transition hover:bg-blue-50"
                  >
                    <p className="text-sm font-medium text-gray-900">{entry.label}</p>
                    {entry.description && (
                      <p className="mt-0.5 text-xs text-gray-600">{entry.description}</p>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="border-t border-gray-200 px-4 py-2 text-xs text-gray-500">
          Tip: use <kbd className="rounded border border-gray-200 px-1.5 py-0.5 font-mono">Cmd</kbd>
          +
          <kbd className="rounded border border-gray-200 px-1.5 py-0.5 font-mono">K</kbd> anytime.
        </div>
      </div>
    </div>
  );
}
