import type { BuildPreviewResult, BuildSaveResult } from './types';

export interface BuilderMessage {
  message_id: string;
  role: 'assistant' | 'user';
  content: string;
  created_at: number;
}

export interface BuilderTool {
  name: string;
  description: string;
  when_to_use: string;
}

export interface BuilderRoutingRule {
  name: string;
  intent: string;
  description: string;
}

export interface BuilderPolicy {
  name: string;
  description: string;
}

export interface BuilderEvalCriterion {
  name: string;
  description: string;
}

export interface BuilderConfig {
  agent_name: string;
  model: string;
  system_prompt: string;
  tools: BuilderTool[];
  routing_rules: BuilderRoutingRule[];
  policies: BuilderPolicy[];
  eval_criteria: BuilderEvalCriterion[];
  metadata: Record<string, unknown>;
}

export interface BuilderEvalDraft {
  case_count: number;
  scenarios: Array<{ name: string; description: string }>;
}

export interface BuilderSessionPayload {
  session_id: string;
  mock_mode: boolean;
  mock_reason?: string;
  messages: BuilderMessage[];
  config: BuilderConfig;
  stats: {
    tool_count: number;
    policy_count: number;
    routing_rule_count: number;
  };
  evals: BuilderEvalDraft | null;
  updated_at: number;
}

export interface BuilderExportPayload {
  filename: string;
  content: string;
  content_type: string;
}

export class BuilderApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'BuilderApiError';
    this.status = status;
  }
}

async function fetchBuilderApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new BuilderApiError(
      (text && text.trim()) ? text : `The server is temporarily unavailable. Retrying usually resolves this.`,
      response.status,
    );
  }

  return response.json() as Promise<T>;
}

export function sendBuilderMessage(body: {
  message: string;
  session_id?: string | null;
}): Promise<BuilderSessionPayload> {
  return fetchBuilderApi('/api/builder/chat', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function exportBuilderConfig(body: {
  session_id: string;
  format?: 'yaml' | 'json';
}): Promise<BuilderExportPayload> {
  return fetchBuilderApi('/api/builder/export', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function saveBuilderSession(body: { session_id: string }): Promise<BuildSaveResult> {
  return fetchBuilderApi('/api/builder/save', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function previewBuilderSession(body: {
  session_id: string;
  message: string;
}): Promise<BuildPreviewResult> {
  return fetchBuilderApi('/api/builder/preview', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
