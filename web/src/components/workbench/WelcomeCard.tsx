/**
 * Empty-state welcome shown when the conversation feed is empty.
 *
 * Mirrors the Claude Code REPL banner: a single-line greeting, a tight set of
 * example prompts the operator can copy, and the slash command primer. The
 * component is purely presentational — clicking an example prompt focuses the
 * composer and pre-fills the value via the workbench store's setter.
 */

import { ArrowUpRight, Sparkles, Terminal } from 'lucide-react';
import { WORKBENCH_SLASH_COMMANDS } from './SlashCommandPalette';

const EXAMPLE_PROMPTS: Array<{ title: string; brief: string }> = [
  {
    title: 'Refunds support agent',
    brief:
      'Build a refunds support agent that can look up orders, calculate refund amounts using a refund_policy tool, and escalate disputed cases to a human reviewer.',
  },
  {
    title: 'Travel itinerary planner',
    brief:
      'Build a travel planning agent that takes a destination and dates, generates a 3-day itinerary, and outputs structured JSON with morning / afternoon / evening blocks.',
  },
  {
    title: 'Internal release notes writer',
    brief:
      'Build an agent that ingests a list of merged PR titles and generates a customer-facing release note grouped by feature, fix, and chore.',
  },
];

export function WelcomeCard() {
  const fillComposer = (text: string) => {
    const textarea = document.querySelector<HTMLTextAreaElement>(
      '[aria-label="Build request"]'
    );
    if (!textarea) return;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      'value'
    )?.set;
    setter?.call(textarea, text);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    textarea.focus();
    textarea.setSelectionRange(text.length, text.length);
  };

  return (
    <section className="rounded-xl border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] px-5 py-5">
      <div className="flex items-center gap-2 text-[color:var(--wb-accent)]">
        <Sparkles className="h-4 w-4" />
        <h2 className="text-[15px] font-semibold text-[color:var(--wb-text)]">
          Workbench is ready.
        </h2>
      </div>
      <p className="mt-2 text-[13px] leading-6 text-[color:var(--wb-text-soft)]">
        Describe the agent you want in plain English. The Workbench plans the work,
        edits the canonical config, generates tools and guardrails, and renders the
        result on the right. When the candidate is ready, switch to{' '}
        <span className="font-medium text-[color:var(--wb-success)]">Chat</span> mode
        to test it without leaving the page.
      </p>

      <div className="mt-4">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--wb-text-dim)]">
          Try a starter brief
        </p>
        <div className="grid gap-2 sm:grid-cols-3">
          {EXAMPLE_PROMPTS.map((example) => (
            <button
              key={example.title}
              type="button"
              onClick={() => fillComposer(example.brief)}
              className="group flex flex-col rounded-lg border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] p-3 text-left text-[12px] transition hover:border-[color:var(--wb-border-strong)]"
            >
              <span className="flex items-center justify-between gap-2 text-[12px] font-medium text-[color:var(--wb-text)]">
                {example.title}
                <ArrowUpRight className="h-3 w-3 text-[color:var(--wb-text-dim)] transition group-hover:text-[color:var(--wb-accent)]" />
              </span>
              <span className="mt-1 line-clamp-2 text-[11px] leading-5 text-[color:var(--wb-text-dim)]">
                {example.brief}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-3 py-2.5">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--wb-text-dim)]">
          <Terminal className="h-3 w-3" />
          Slash commands
        </div>
        <ul className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-2">
          {WORKBENCH_SLASH_COMMANDS.slice(0, 6).map((cmd) => (
            <li key={cmd.name} className="flex items-baseline gap-2">
              <span className="font-mono text-[color:var(--wb-accent)]">/{cmd.name}</span>
              <span className="text-[color:var(--wb-text-dim)]">{cmd.description}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
