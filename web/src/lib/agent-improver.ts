import type { BuilderConfig, BuilderSessionPayload } from './builder-chat-api';
import type { AgentLibraryItem, BuildSaveResult } from './types';

export const AGENT_IMPROVER_STORAGE_KEY = 'agentlab.agent-improver.v2';

const MAX_STORED_CHECKPOINTS = 10;

interface StorageLike {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
}

export interface AgentImproverCheckpoint {
  id: string;
  createdAt: number;
  latestUserRequest: string;
  session: BuilderSessionPayload;
}

export interface PersistedAgentImproverState {
  version: 2;
  liveSessionId: string | null;
  checkpoints: AgentImproverCheckpoint[];
  activeCheckpointIndex: number;
  previewMessage: string;
  saveResult: BuildSaveResult | null;
  savedAgent: AgentLibraryItem | null;
}

/**
 * Keeps the draft history stable enough for undo/redo and tab-close recovery.
 */
export function buildCheckpointHistory(
  current: AgentImproverCheckpoint[],
  session: BuilderSessionPayload,
): AgentImproverCheckpoint[] {
  const nextCheckpoint: AgentImproverCheckpoint = {
    id: buildCheckpointId(session),
    createdAt: session.updated_at,
    latestUserRequest: latestUserRequestFromSession(session),
    session,
  };

  const existingIndex = current.findIndex((checkpoint) => checkpoint.id === nextCheckpoint.id);
  const deduped =
    existingIndex === -1
      ? [...current, nextCheckpoint]
      : current.map((checkpoint, index) => (index === existingIndex ? nextCheckpoint : checkpoint));

  return deduped.slice(-MAX_STORED_CHECKPOINTS);
}

/**
 * Restores browser-local draft continuity without trusting malformed storage.
 */
export function readPersistedAgentImproverState(
  storage: StorageLike | null | undefined = getBrowserStorage(),
): PersistedAgentImproverState | null {
  if (!storage) {
    return null;
  }

  try {
    const raw = storage.getItem(AGENT_IMPROVER_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as Partial<PersistedAgentImproverState>;
    const checkpoints = Array.isArray(parsed.checkpoints)
      ? parsed.checkpoints.filter(isCheckpoint)
      : [];

    if (checkpoints.length === 0 && typeof parsed.previewMessage !== 'string') {
      return null;
    }

    const maxIndex = Math.max(checkpoints.length - 1, 0);
    const activeCheckpointIndex =
      typeof parsed.activeCheckpointIndex === 'number'
        ? Math.min(Math.max(parsed.activeCheckpointIndex, 0), maxIndex)
        : maxIndex;

    return {
      version: 2,
      liveSessionId: typeof parsed.liveSessionId === 'string' ? parsed.liveSessionId : null,
      checkpoints,
      activeCheckpointIndex,
      previewMessage: typeof parsed.previewMessage === 'string' ? parsed.previewMessage : '',
      saveResult: isRecord(parsed.saveResult) ? (parsed.saveResult as BuildSaveResult) : null,
      savedAgent: isRecord(parsed.savedAgent) ? (parsed.savedAgent as AgentLibraryItem) : null,
    };
  } catch {
    return null;
  }
}

/**
 * Persists the user-visible draft state so recovery is predictable after tab close or refresh.
 */
export function writePersistedAgentImproverState(
  state: PersistedAgentImproverState,
  storage: StorageLike | null | undefined = getBrowserStorage(),
): void {
  if (!storage) {
    return;
  }

  storage.setItem(AGENT_IMPROVER_STORAGE_KEY, JSON.stringify(state));
}

/**
 * Clears browser-local draft state when the user intentionally starts over.
 */
export function clearPersistedAgentImproverState(
  storage: StorageLike | null | undefined = getBrowserStorage(),
): void {
  if (!storage) {
    return;
  }

  storage.removeItem(AGENT_IMPROVER_STORAGE_KEY);
}

/**
 * Generates count labels that read like product copy instead of raw string concatenation.
 */
export function formatCountLabel(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : (plural ?? inferPlural(singular))}`;
}

/**
 * Produces a safer human-readable YAML preview for builder drafts and local exports.
 */
export function serializeBuilderConfigToYaml(config: BuilderConfig): string {
  return renderYamlValue(config, 0).join('\n');
}

/**
 * Reuses the user's last explicit request for restoration banners and restart flows.
 */
export function latestUserRequestFromSession(session: BuilderSessionPayload | null | undefined): string {
  const userMessage = [...(session?.messages ?? [])].reverse().find((message) => message.role === 'user');
  return userMessage?.content ?? 'No request submitted yet.';
}

/**
 * Creates a stable local export filename when the live backend export is unavailable.
 */
export function buildLocalDraftFilename(agentName: string, format: 'yaml' | 'json'): string {
  return `${slugify(agentName)}.${format}`;
}

function buildCheckpointId(session: BuilderSessionPayload): string {
  return `${session.session_id}:${session.updated_at}`;
}

function getBrowserStorage(): StorageLike | null {
  if (typeof window === 'undefined') {
    return null;
  }

  return window.localStorage;
}

function isCheckpoint(value: unknown): value is AgentImproverCheckpoint {
  return isRecord(value)
    && typeof value.id === 'string'
    && typeof value.createdAt === 'number'
    && typeof value.latestUserRequest === 'string'
    && isRecord(value.session)
    && typeof value.session.session_id === 'string'
    && typeof value.session.updated_at === 'number';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function inferPlural(value: string): string {
  if (value.endsWith('y') && !/[aeiou]y$/i.test(value)) {
    return `${value.slice(0, -1)}ies`;
  }
  if (value.endsWith('s')) {
    return `${value}es`;
  }
  return `${value}s`;
}

function renderYamlValue(value: unknown, indentLevel: number): string[] {
  const indent = '  '.repeat(indentLevel);

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return [`${indent}[]`];
    }

    return value.flatMap((item) => renderYamlArrayItem(item, indentLevel));
  }

  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      return [`${indent}{}`];
    }

    return entries.flatMap(([key, item]) => renderYamlObjectEntry(key, item, indentLevel));
  }

  return [`${indent}${renderInlineYamlValue(value)}`];
}

function renderYamlArrayItem(value: unknown, indentLevel: number): string[] {
  const indent = '  '.repeat(indentLevel);

  if (typeof value === 'string' && value.includes('\n')) {
    return [
      `${indent}- |-`,
      ...value.split('\n').map((line) => `${indent}  ${line}`),
    ];
  }

  if (isInlineYamlValue(value)) {
    return [`${indent}- ${renderInlineYamlValue(value)}`];
  }

  return [
    `${indent}-`,
    ...renderYamlValue(value, indentLevel + 1),
  ];
}

function renderYamlObjectEntry(key: string, value: unknown, indentLevel: number): string[] {
  const indent = '  '.repeat(indentLevel);
  const renderedKey = needsQuotedString(key) ? quoteYamlString(key) : key;

  if (typeof value === 'string' && value.includes('\n')) {
    return [
      `${indent}${renderedKey}: |-`,
      ...value.split('\n').map((line) => `${indent}  ${line}`),
    ];
  }

  if (isInlineYamlValue(value)) {
    return [`${indent}${renderedKey}: ${renderInlineYamlValue(value)}`];
  }

  return [
    `${indent}${renderedKey}:`,
    ...renderYamlValue(value, indentLevel + 1),
  ];
}

function isInlineYamlValue(value: unknown): boolean {
  return value === null
    || typeof value === 'number'
    || typeof value === 'boolean'
    || typeof value === 'string';
}

function renderInlineYamlValue(value: unknown): string {
  if (value === null || value === undefined) {
    return 'null';
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  const stringValue = String(value);
  return needsQuotedString(stringValue) ? quoteYamlString(stringValue) : stringValue;
}

function needsQuotedString(value: string): boolean {
  return value.length === 0
    || value.trim() !== value
    || /[:#[\]{}&,*!|>'"%@`]/.test(value)
    || /^[-?:]/.test(value)
    || /^(true|false|null|~)$/i.test(value)
    || /^[-+]?[0-9]+(\.[0-9]+)?$/.test(value);
}

function quoteYamlString(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'agent-improver-draft';
}
