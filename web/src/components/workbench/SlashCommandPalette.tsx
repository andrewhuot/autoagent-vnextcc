/**
 * Inline slash-command palette shown over the composer when the user types `/`.
 *
 * Mirrors Claude Code: a tight list of commands with a keyboard hint, scoped to
 * the workbench (build vs chat vs config actions). The list is curated and
 * filtered by the typed prefix so the user can ⏎ to dispatch.
 */

import { useEffect, useMemo, useRef } from 'react';
import { classNames } from '../../lib/utils';

export interface SlashCommand {
  /** Command keyword without the leading slash. */
  name: string;
  /** Short description shown beside the command. */
  description: string;
  /** Optional argument hint (e.g. "<task description>"). */
  args?: string;
  /** Mode this command lives in — used to colour-code the entry. */
  mode?: 'build' | 'chat' | 'utility';
}

export const WORKBENCH_SLASH_COMMANDS: SlashCommand[] = [
  { name: 'build', description: 'Switch to build mode and submit a build brief', args: '<intent>', mode: 'build' },
  { name: 'chat', description: 'Switch to chat mode to test the agent', args: '<message>', mode: 'chat' },
  { name: 'config', description: 'Open the canonical config view', mode: 'utility' },
  { name: 'agent', description: 'Open the agent card', mode: 'utility' },
  { name: 'evals', description: 'Open the evals workspace', mode: 'utility' },
  { name: 'reset', description: 'Reset the chat transcript', mode: 'chat' },
  { name: 'clear', description: 'Clear the conversation feed and start fresh', mode: 'utility' },
  { name: 'help', description: 'Show keyboard shortcuts and commands', mode: 'utility' },
];

interface SlashCommandPaletteProps {
  query: string;
  selectedIndex: number;
  onSelect: (cmd: SlashCommand) => void;
  onIndexChange: (index: number) => void;
}

export function filterSlashCommands(query: string): SlashCommand[] {
  const q = query.replace(/^\//, '').toLowerCase();
  if (!q) return WORKBENCH_SLASH_COMMANDS;
  return WORKBENCH_SLASH_COMMANDS.filter(
    (c) => c.name.toLowerCase().startsWith(q) || c.description.toLowerCase().includes(q)
  );
}

export function SlashCommandPalette({
  query,
  selectedIndex,
  onSelect,
  onIndexChange,
}: SlashCommandPaletteProps) {
  const filtered = useMemo(() => filterSlashCommands(query), [query]);
  const listRef = useRef<HTMLUListElement>(null);

  // Keep the active item in view as the user arrows through.
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const item = list.querySelector<HTMLLIElement>(
      `li[data-index="${selectedIndex}"]`
    );
    item?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  if (filtered.length === 0) return null;

  return (
    <div
      className="absolute bottom-full left-3 right-3 mb-2 max-h-[260px] overflow-hidden rounded-lg border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] shadow-lg"
      role="listbox"
      aria-label="Slash commands"
    >
      <div className="border-b border-[color:var(--wb-border)] px-3 py-1.5 text-[10px] uppercase tracking-wider text-[color:var(--wb-text-dim)]">
        Commands {filtered.length > 0 && <span>· {filtered.length}</span>}
      </div>
      <ul ref={listRef} className="max-h-[220px] overflow-y-auto py-1">
        {filtered.map((cmd, index) => {
          const isActive = index === selectedIndex;
          return (
            <li
              key={cmd.name}
              data-index={index}
              role="option"
              aria-selected={isActive}
              className={classNames(
                'flex cursor-pointer items-center gap-3 px-3 py-1.5 text-[12px]',
                isActive
                  ? 'bg-[color:var(--wb-bg-active)] text-[color:var(--wb-text)]'
                  : 'text-[color:var(--wb-text-soft)] hover:bg-[color:var(--wb-bg-hover)]'
              )}
              onMouseEnter={() => onIndexChange(index)}
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(cmd);
              }}
            >
              <span
                className={classNames(
                  'inline-flex w-16 shrink-0 items-center rounded-md px-1.5 py-0.5 font-mono text-[11px]',
                  cmd.mode === 'build' && 'bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]',
                  cmd.mode === 'chat' && 'bg-[color:var(--wb-success-weak)] text-[color:var(--wb-success)]',
                  cmd.mode === 'utility' && 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-dim)]'
                )}
              >
                /{cmd.name}
              </span>
              <span className="min-w-0 flex-1 truncate">{cmd.description}</span>
              {cmd.args && (
                <span className="hidden shrink-0 font-mono text-[10px] text-[color:var(--wb-text-muted)] sm:inline">
                  {cmd.args}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      <div className="border-t border-[color:var(--wb-border)] px-3 py-1 text-[10px] text-[color:var(--wb-text-dim)]">
        ↑↓ navigate · ⏎ select · esc dismiss
      </div>
    </div>
  );
}
