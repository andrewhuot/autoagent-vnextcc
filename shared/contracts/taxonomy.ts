export const COMMAND_GROUPS = [
  'home',
  'build',
  'import',
  'eval',
  'optimize',
  'review',
  'deploy',
  'observe',
  'govern',
  'integrations',
  'settings',
] as const;

export type CommandGroup = (typeof COMMAND_GROUPS)[number];

export interface CommandTaxonomyEntry {
  label: string;
  description: string;
  subcommands: string[];
}

export type CommandTaxonomy = Record<CommandGroup, CommandTaxonomyEntry>;

export const COMMAND_TAXONOMY: CommandTaxonomy = {
  home: {
    label: 'Home',
    description: 'Workspace status and setup',
    subcommands: ['dashboard', 'setup'],
  },
  build: {
    label: 'Build',
    description: 'Create and refine agent configurations',
    subcommands: ['prompt', 'transcript', 'builder_chat', 'saved_artifacts'],
  },
  import: {
    label: 'Import',
    description: 'Import external agents and artifacts',
    subcommands: ['cx', 'adk', 'config', 'transcript'],
  },
  eval: {
    label: 'Eval',
    description: 'Run and inspect evaluation suites',
    subcommands: ['run', 'results', 'show', 'list', 'generate', 'curriculum'],
  },
  optimize: {
    label: 'Optimize',
    description: 'Improve agent performance through experimentation',
    subcommands: ['run', 'live', 'experiments', 'review', 'opportunities'],
  },
  review: {
    label: 'Review',
    description: 'Review and apply proposed changes',
    subcommands: ['list', 'show', 'apply', 'reject', 'export'],
  },
  deploy: {
    label: 'Deploy',
    description: 'Promote configurations to production',
    subcommands: ['canary', 'immediate', 'status', 'rollback', 'release'],
  },
  observe: {
    label: 'Observe',
    description: 'Monitor agent health and behavior',
    subcommands: ['dashboard', 'traces', 'conversations', 'events', 'blame', 'context', 'loop'],
  },
  govern: {
    label: 'Govern',
    description: 'Manage judges, configs, memory, runbooks, and policies',
    subcommands: ['judges', 'configs', 'memory', 'runbooks', 'scorers', 'skills', 'registry', 'rewards', 'preferences', 'policies'],
  },
  integrations: {
    label: 'Integrations',
    description: 'External platform connections',
    subcommands: ['cx-import', 'cx-deploy', 'adk-import', 'adk-deploy', 'agent-skills', 'mcp'],
  },
  settings: {
    label: 'Settings',
    description: 'Workspace configuration and diagnostics',
    subcommands: ['setup', 'mode', 'doctor', 'notifications'],
  },
};
