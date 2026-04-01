import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Check,
  Copy,
  FlaskConical,
  Hammer,
  Rocket,
  Settings2,
  Sparkles,
  Terminal,
  CircleHelp,
} from 'lucide-react';

import { classNames } from '../lib/utils';

interface CommandCardDefinition {
  key: string;
  label: string;
  command: string;
  description: string;
  icon: ReactNode;
}

interface CopyState {
  key: string;
  status: 'success' | 'error';
}

const QUICK_START_COMMAND = 'npx agentlab';

const COMMON_COMMANDS: CommandCardDefinition[] = [
  {
    key: 'build',
    label: 'Build',
    command: 'agentlab build',
    description: 'Open the builder workflow and start shaping a new agent configuration.',
    icon: <Hammer className="h-4 w-4" />,
  },
  {
    key: 'eval',
    label: 'Eval',
    command: 'agentlab eval run',
    description: 'Run an evaluation suite and capture the metrics you need for the next iteration.',
    icon: <FlaskConical className="h-4 w-4" />,
  },
  {
    key: 'optimize',
    label: 'Optimize',
    command: 'agentlab optimize',
    description: 'Kick off an optimization loop to search for stronger prompts, tools, and policies.',
    icon: <Sparkles className="h-4 w-4" />,
  },
  {
    key: 'deploy',
    label: 'Deploy',
    command: 'agentlab deploy',
    description: 'Promote a validated configuration once your evals and reviews look healthy.',
    icon: <Rocket className="h-4 w-4" />,
  },
  {
    key: 'status',
    label: 'Status',
    command: 'agentlab status',
    description: 'Check the current workspace, active config, and runtime readiness at a glance.',
    icon: <Activity className="h-4 w-4" />,
  },
  {
    key: 'config',
    label: 'Config',
    command: 'agentlab config show',
    description: 'Inspect the config that the CLI is about to use before you run anything expensive.',
    icon: <Settings2 className="h-4 w-4" />,
  },
  {
    key: 'help',
    label: 'Help',
    command: 'agentlab help',
    description: 'List supported commands and flags when you want a quick reminder in the terminal.',
    icon: <CircleHelp className="h-4 w-4" />,
  },
];

/**
 * Provides an approachable launchpad for the AgentLab CLI so users can copy common commands
 * without leaving the web app.
 */
export function CliLauncher() {
  const [copyState, setCopyState] = useState<CopyState | null>(null);

  useEffect(() => {
    document.title = 'CLI • AgentLab';
  }, []);

  async function handleCopy(key: string, command: string) {
    const clipboard = window.navigator.clipboard?.writeText?.bind(window.navigator.clipboard);

    if (!clipboard) {
      setCopyState({ key, status: 'error' });
      return;
    }

    try {
      await clipboard(command);
      setCopyState({ key, status: 'success' });
    } catch {
      setCopyState({ key, status: 'error' });
    }
  }

  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-[28px] border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 px-6 py-8 text-white shadow-xl shadow-slate-900/10 sm:px-8">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(56,189,248,0.24),_transparent_35%),radial-gradient(circle_at_bottom_left,_rgba(96,165,250,0.2),_transparent_32%)]" />
        <div className="absolute inset-y-0 right-0 hidden w-1/3 border-l border-white/10 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.08),_transparent_55%)] lg:block" />

        <div className="relative grid gap-8 lg:grid-cols-[1.25fr_0.75fr] lg:items-end">
          <div className="space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.2em] text-slate-200">
              <Terminal className="h-4 w-4" />
              Terminal-first workflow
            </div>

            <div className="space-y-3">
              <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                Launch the CLI
              </h2>
              <p className="max-w-2xl text-sm leading-7 text-slate-300 sm:text-base">
                Go from zero to an active AgentLab workspace in one command, then keep your build,
                eval, optimize, and deploy loop moving without hunting through docs.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3 text-sm text-slate-200">
              <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1">
                Copy-ready commands
              </span>
              <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1">
                Friendly terminal shortcuts
              </span>
              <Link
                to="/docs"
                className="inline-flex items-center gap-1 rounded-full border border-sky-400/30 bg-sky-400/10 px-3 py-1 text-sky-100 transition hover:bg-sky-400/20"
              >
                Open docs
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>

          <div className="grid gap-3 rounded-[24px] border border-white/10 bg-white/5 p-4 backdrop-blur-sm">
            <HeroStat label="Fast start" value="< 30 sec" />
            <HeroStat label="Core workflows" value="7 commands" />
            <HeroStat label="Best paired with" value="Web UI" />
          </div>
        </div>
      </section>

      <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sky-600">Launch</p>
            <h3 className="text-2xl font-semibold tracking-tight text-slate-900">Quick Start</h3>
            <p className="max-w-2xl text-sm leading-6 text-slate-600">
              Use the starter command below to get into the workflow immediately without installing
              anything globally.
            </p>
          </div>
          <p className="text-sm text-slate-500">Works well for demos, onboarding, and fresh workspace setup.</p>
        </div>

        <div className="mt-6 rounded-[20px] border border-slate-800 bg-slate-950 p-4 text-slate-100 shadow-inner shadow-black/20">
          <div className="flex items-center justify-between gap-3 border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.24em] text-slate-400">
              <Terminal className="h-4 w-4" />
              One-liner
            </div>
            <CopyButton
              active={copyState?.key === 'quick-start' && copyState.status === 'success'}
              error={copyState?.key === 'quick-start' && copyState.status === 'error'}
              label={copyState?.key === 'quick-start' && copyState.status === 'success' ? 'Quick start copied' : 'Copy quick start command'}
              onClick={() => handleCopy('quick-start', QUICK_START_COMMAND)}
            />
          </div>

          <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <code className="rounded-xl bg-gray-900 px-4 py-3 font-mono text-sm text-sky-200">
              {QUICK_START_COMMAND}
            </code>
            <p className="max-w-xl text-sm leading-6 text-slate-400">
              Start here, then jump into `agentlab build`, `agentlab eval run`, or the in-app docs
              once your workspace is live.
            </p>
          </div>
        </div>
      </section>

      <section className="space-y-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sky-600">Toolkit</p>
            <h3 className="text-2xl font-semibold tracking-tight text-slate-900">Common Commands</h3>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-slate-600">
            These are the commands most teams reach for day to day. Each card includes the real
            command string so you can copy it straight into your terminal.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {COMMON_COMMANDS.map((item) => (
            <article
              key={item.key}
              className="group rounded-[22px] border border-slate-200 bg-white p-5 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-sky-200 hover:shadow-lg hover:shadow-slate-200/70"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-3">
                  <div className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                    {item.icon}
                    {item.label}
                  </div>
                  <h4 className="text-lg font-semibold tracking-tight text-slate-900">{item.command}</h4>
                </div>

                <CopyButton
                  active={copyState?.key === item.key && copyState.status === 'success'}
                  error={copyState?.key === item.key && copyState.status === 'error'}
                  label={
                    copyState?.key === item.key && copyState.status === 'success'
                      ? `${item.label} copied`
                      : `Copy ${item.command}`
                  }
                  onClick={() => handleCopy(item.key, item.command)}
                />
              </div>

              <p className="mt-3 text-sm leading-6 text-slate-600">{item.description}</p>

              <div className="mt-4 rounded-xl bg-gray-900 px-4 py-3">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Command</p>
                <code className="mt-2 block font-mono text-sm text-sky-200">{item.command}</code>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function HeroStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/10 p-4">
      <p className="text-xs uppercase tracking-[0.22em] text-slate-400">{label}</p>
      <p className="mt-2 text-lg font-semibold tracking-tight text-white">{value}</p>
    </div>
  );
}

function CopyButton({
  active,
  error,
  label,
  onClick,
}: {
  active: boolean;
  error: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className={classNames(
        'inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition',
        active && 'border-emerald-200 bg-emerald-50 text-emerald-700',
        error && 'border-red-200 bg-red-50 text-red-700',
        !active && !error && 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900'
      )}
    >
      {active ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      <span>{active ? 'Copied' : error ? 'Retry' : 'Copy'}</span>
    </button>
  );
}
