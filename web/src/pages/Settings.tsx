import { ExternalLink, Keyboard } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';

const sections = [
  {
    title: 'Agent Configuration',
    description: 'Core runtime files and prompts used by the evaluator and optimizer.',
    items: [
      { label: 'Base Config', value: 'configs/v001_base.yaml' },
      { label: 'Version Manifest', value: 'configs/manifest.json' },
      { label: 'Prompt Defaults', value: 'agent/config/base_config.yaml' },
    ],
  },
  {
    title: 'Evaluation Suite',
    description: 'Case definitions and scoring context used by eval runs.',
    items: [
      { label: 'Case Directory', value: 'evals/cases/' },
      { label: 'Runner Module', value: 'evals/runner.py' },
      { label: 'Scorer Module', value: 'evals/scorer.py' },
    ],
  },
  {
    title: 'Storage Paths',
    description: 'Persistence files used by local execution and server runtime.',
    items: [
      { label: 'Conversations DB', value: 'conversations.db' },
      { label: 'Optimizer Memory DB', value: 'optimizer_memory.db' },
      { label: 'Config Directory', value: 'configs/' },
    ],
  },
];

const shortcuts = [
  { key: 'Cmd+K', action: 'Open command palette' },
  { key: 'N', action: 'Open New Eval Run' },
  { key: 'O', action: 'Open Optimize page' },
  { key: 'D', action: 'Open Deploy page' },
];

export function Settings() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Reference paths, quick links, and operator shortcuts for the AutoAgent control plane."
      />

      <section className="grid gap-4 lg:grid-cols-3">
        {sections.map((section) => (
          <div key={section.title} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900">{section.title}</h3>
            <p className="mt-1 text-sm text-gray-600">{section.description}</p>
            <div className="mt-4 space-y-2">
              {section.items.map((item) => (
                <div key={item.label} className="flex items-center justify-between gap-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                  <span className="text-sm text-gray-700">{item.label}</span>
                  <span className="font-mono text-xs text-gray-600">{item.value}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Keyboard className="h-4 w-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">Keyboard Shortcuts</h3>
          </div>
          <div className="space-y-2">
            {shortcuts.map((shortcut) => (
              <div key={shortcut.key} className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2">
                <span className="text-sm text-gray-700">{shortcut.action}</span>
                <kbd className="rounded border border-gray-300 bg-gray-50 px-2 py-0.5 font-mono text-xs text-gray-700">
                  {shortcut.key}
                </kbd>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-gray-900">Resources</h3>
          <div className="space-y-2">
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2 text-sm text-blue-700 transition hover:bg-blue-50"
            >
              API OpenAPI Docs
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
            <a
              href="http://localhost:8000/redoc"
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2 text-sm text-blue-700 transition hover:bg-blue-50"
            >
              ReDoc Reference
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
            <a
              href="https://github.com/your-org/AutoAgent-VNextCC"
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2 text-sm text-blue-700 transition hover:bg-blue-50"
            >
              Repository
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>

          <p className="mt-4 text-xs text-gray-500">
            Runtime values can be overridden with environment variables like `AUTOAGENT_DB`,
            `AUTOAGENT_CONFIGS`, and `AUTOAGENT_MEMORY_DB`.
          </p>
        </div>
      </section>
    </div>
  );
}
