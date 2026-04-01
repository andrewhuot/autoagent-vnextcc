import { useEffect, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BookOpen,
  Bot,
  FlaskConical,
  LayoutDashboard,
  LifeBuoy,
  Rocket,
  Search,
  Settings2,
  Sparkles,
  Terminal,
  type LucideIcon,
} from 'lucide-react';

interface CliGuide {
  title: string;
  description: string;
  command: string;
  icon: LucideIcon;
}

interface WebGuide {
  title: string;
  description: string;
  icon: LucideIcon;
}

const CLI_GUIDES: CliGuide[] = [
  {
    title: 'Getting Started',
    description: 'Launch a fresh workspace, confirm your runtime mode, and make sure AgentLab is pointed at the right repo.',
    command: 'npx agentlab',
    icon: Terminal,
  },
  {
    title: 'Running Evals',
    description: 'Run suites early and often so you can compare changes with confidence before promoting anything.',
    command: 'agentlab eval run --suite smoke',
    icon: FlaskConical,
  },
  {
    title: 'Optimization',
    description: 'Explore prompt and config improvements when you need to lift score, reduce regressions, or tighten policy behavior.',
    command: 'agentlab optimize --objective quality',
    icon: Sparkles,
  },
  {
    title: 'Deployment',
    description: 'Ship the strongest candidate with a deliberate rollout once the workspace looks healthy and the review loop is complete.',
    command: 'agentlab deploy --strategy canary',
    icon: Rocket,
  },
];

const WEB_GUIDES: WebGuide[] = [
  {
    title: 'Dashboard Overview',
    description: 'Use the dashboard as your control tower for workspace health, activity, and the current state of the build-to-deploy loop.',
    icon: LayoutDashboard,
  },
  {
    title: 'Building Agents',
    description: 'Open Build when you want to draft prompts, refine configs, and iterate in the same workspace you use for saved artifacts.',
    icon: Bot,
  },
  {
    title: 'Results Explorer',
    description: 'Move into Results Explorer to inspect eval output, compare runs, and spot the patterns behind regressions or wins.',
    icon: Search,
  },
  {
    title: 'Settings & Config',
    description: 'Keep Settings and Setup close by whenever you need to verify provider keys, runtime mode, notifications, or workspace defaults.',
    icon: Settings2,
  },
];

/**
 * Keeps the core CLI and web UI onboarding guidance inside AgentLab so users can learn without
 * leaving the product.
 */
export function Docs() {
  useEffect(() => {
    document.title = 'Documentation • AgentLab';
  }, []);

  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-[28px] border border-slate-200 bg-white px-6 py-8 shadow-sm sm:px-8">
        <div className="absolute inset-y-0 right-0 w-1/2 bg-[radial-gradient(circle_at_top_right,_rgba(56,189,248,0.18),_transparent_46%)]" />
        <div className="relative space-y-5">
          <div className="inline-flex items-center gap-2 rounded-full border border-sky-100 bg-sky-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-sky-700">
            <BookOpen className="h-4 w-4" />
            In-app guide
          </div>
          <div className="space-y-3">
            <h2 className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">
              Documentation
            </h2>
            <p className="max-w-3xl text-sm leading-7 text-slate-600 sm:text-base">
              Start here when you want a clean tour of the AgentLab workflow, from your first CLI
              command to the parts of the web UI you will use every day.
            </p>
          </div>
          <div className="flex flex-wrap gap-3 text-sm text-slate-600">
            <Link
              to="/cli"
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 transition hover:border-slate-300 hover:bg-white hover:text-slate-900"
            >
              Jump to CLI launcher
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              to="/build"
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 transition hover:border-slate-300 hover:bg-white hover:text-slate-900"
            >
              Open Build workspace
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </section>

      <GuideSection
        eyebrow="CLI"
        title="Using the CLI"
        description="The terminal is still the quickest way to launch, evaluate, optimize, and deploy. These cards cover the most common starting points."
      >
        <div className="grid gap-4 md:grid-cols-2">
          {CLI_GUIDES.map((guide) => (
            <CliGuideCard key={guide.title} guide={guide} />
          ))}
        </div>
      </GuideSection>

      <GuideSection
        eyebrow="Web UI"
        title="Using the Web UI"
        description="Once the workspace is running, the UI gives you a calmer way to inspect runs, iterate on configs, and keep the broader system in view."
      >
        <div className="grid gap-4 md:grid-cols-2">
          {WEB_GUIDES.map((guide) => (
            <WebGuideCard key={guide.title} guide={guide} />
          ))}
        </div>
      </GuideSection>

      <section className="rounded-[24px] border border-slate-200 bg-slate-950 p-6 text-slate-100 shadow-sm">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-2xl space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-slate-300">
              <LifeBuoy className="h-4 w-4" />
              Need Help?
            </div>
            <h3 className="text-2xl font-semibold tracking-tight text-white">Need Help?</h3>
            <p className="text-sm leading-6 text-slate-300">
              Start with the built-in CLI help, double-check Setup if the workspace looks unhealthy,
              and use Settings when you need to confirm runtime details or notification behavior.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3 lg:w-[34rem]">
            <HelpLink to="/cli" title="CLI Launcher" body="Copy the command you need without leaving the app." />
            <HelpLink to="/setup" title="Setup" body="Verify API keys, mode, and workspace readiness." />
            <HelpLink to="/settings" title="Settings" body="Review config defaults and notification behavior." />
          </div>
        </div>

        <div className="mt-5 rounded-2xl border border-white/10 bg-black/20 px-4 py-3">
          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Tip</p>
          <code className="mt-2 block font-mono text-sm text-sky-200">agentlab help</code>
        </div>
      </section>
    </div>
  );
}

function GuideSection({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-5">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sky-600">{eyebrow}</p>
        <h3 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h3>
        <p className="max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
      </div>
      {children}
    </section>
  );
}

function CliGuideCard({ guide }: { guide: CliGuide }) {
  const Icon = guide.icon;

  return (
    <article className="rounded-[22px] border border-slate-200 bg-white p-5 shadow-sm transition duration-200 hover:border-sky-200 hover:shadow-lg hover:shadow-slate-200/70">
      <div className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
        <Icon className="h-4 w-4" />
        CLI Guide
      </div>
      <h4 className="mt-4 text-lg font-semibold tracking-tight text-slate-900">{guide.title}</h4>
      <p className="mt-2 text-sm leading-6 text-slate-600">{guide.description}</p>
      <div className="mt-4 rounded-xl bg-gray-900 px-4 py-3">
        <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Example command</p>
        <code className="mt-2 block font-mono text-sm text-sky-200">{guide.command}</code>
      </div>
    </article>
  );
}

function WebGuideCard({ guide }: { guide: WebGuide }) {
  const Icon = guide.icon;

  return (
    <article className="rounded-[22px] border border-slate-200 bg-white p-5 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-sky-200 hover:shadow-lg hover:shadow-slate-200/70">
      <div className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-sky-50 text-sky-700">
        <Icon className="h-5 w-5" />
      </div>
      <h4 className="mt-4 text-lg font-semibold tracking-tight text-slate-900">{guide.title}</h4>
      <p className="mt-2 text-sm leading-6 text-slate-600">{guide.description}</p>
    </article>
  );
}

function HelpLink({ to, title, body }: { to: string; title: string; body: string }) {
  return (
    <Link
      to={to}
      className="rounded-2xl border border-white/10 bg-white/5 p-4 transition hover:border-sky-400/30 hover:bg-sky-400/10"
    >
      <p className="text-sm font-semibold text-white">{title}</p>
      <p className="mt-2 text-sm leading-6 text-slate-300">{body}</p>
    </Link>
  );
}
