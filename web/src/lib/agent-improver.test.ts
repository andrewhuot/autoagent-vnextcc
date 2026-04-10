import { describe, expect, it } from 'vitest';

import type { BuilderConfig } from './builder-chat-api';
import {
  buildCheckpointHistory,
  formatCountLabel,
  serializeBuilderConfigToYaml,
} from './agent-improver';

function mockConfig(overrides: Partial<BuilderConfig> = {}): BuilderConfig {
  return {
    agent_name: 'Escalation Concierge',
    model: 'gpt-5.4-mini',
    system_prompt: 'Help customers safely.\nEscalate with context when needed.',
    tools: [
      {
        name: 'ticket_lookup',
        description: 'Look up the current customer ticket.',
        when_to_use: 'When the customer references an existing ticket.',
      },
    ],
    routing_rules: [
      {
        name: 'escalation',
        intent: 'human_help',
        description: "Escalate when confidence < 0.4 or the user asks for a human.",
      },
    ],
    policies: [
      {
        name: 'Context preservation',
        description: 'Pass the last two customer actions into escalations.',
      },
    ],
    eval_criteria: [
      {
        name: 'Safe escalation',
        description: 'Escalations preserve context and follow policy.',
      },
    ],
    metadata: {
      owner: 'agent-improver',
      enabled: true,
      notes: 'Keep the handoff concise.',
    },
    ...overrides,
  };
}

describe('agent improver helpers', () => {
  it('serializes builder configs into readable YAML with block strings and nested metadata', () => {
    const yaml = serializeBuilderConfigToYaml(
      mockConfig({
        metadata: {
          owner: 'agent-improver',
          enabled: true,
          notes: 'Keep the handoff concise.\nInclude the last two actions.',
          channels: ['chat', 'email'],
        },
      })
    );

    expect(yaml).toContain('agent_name: Escalation Concierge');
    expect(yaml).toContain('system_prompt: |-');
    expect(yaml).toContain('  Help customers safely.');
    expect(yaml).toContain('metadata:');
    expect(yaml).toContain('  enabled: true');
    expect(yaml).toContain('  channels:');
    expect(yaml).toContain('    - chat');
    expect(yaml).toContain('  notes: |-');
    expect(yaml).toContain('    Include the last two actions.');
  });

  it('formats count labels with correct irregular plurals', () => {
    expect(formatCountLabel(1, 'policy', 'policies')).toBe('1 policy');
    expect(formatCountLabel(3, 'policy', 'policies')).toBe('3 policies');
    expect(formatCountLabel(2, 'capability')).toBe('2 capabilities');
  });

  it('deduplicates checkpoint history entries by session version and caps the retained history', () => {
    const history = Array.from({ length: 14 }, (_, index) =>
      buildCheckpointHistory(
        index === 0 ? [] : Array.from({ length: Math.min(index, 10) }, (__unused, historyIndex) => ({
          id: `session-1:${historyIndex + 1}`,
          createdAt: historyIndex + 1,
          latestUserRequest: `Request ${historyIndex + 1}`,
          session: {
            session_id: 'session-1',
            mock_mode: false,
            messages: [],
            config: mockConfig({ agent_name: `Agent ${historyIndex + 1}` }),
            stats: { tool_count: 1, policy_count: 1, routing_rule_count: 1 },
            evals: null,
            updated_at: historyIndex + 1,
          },
        })),
        {
          session_id: 'session-1',
          mock_mode: false,
          messages: [],
          config: mockConfig({ agent_name: `Agent ${index + 1}` }),
          stats: { tool_count: 1, policy_count: 1, routing_rule_count: 1 },
          evals: null,
          updated_at: index + 1,
        }
      )
    ).at(-1);

    expect(history).toHaveLength(10);
    expect(history?.at(-1)?.session.config.agent_name).toBe('Agent 14');

    const deduped = buildCheckpointHistory(history ?? [], {
      session_id: 'session-1',
      mock_mode: false,
      messages: [],
      config: mockConfig({ agent_name: 'Agent 14' }),
      stats: { tool_count: 1, policy_count: 1, routing_rule_count: 1 },
      evals: null,
      updated_at: 14,
    });

    expect(deduped).toHaveLength(10);
    expect(deduped.at(-1)?.session.config.agent_name).toBe('Agent 14');
  });
});
