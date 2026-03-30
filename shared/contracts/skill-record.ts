export type SkillRecordKind = 'build' | 'runtime';

export type SkillRecordStatus = 'active' | 'draft' | 'deprecated';

export type SkillRecordOperator = 'gt' | 'lt' | 'gte' | 'lte' | 'eq';

export interface SkillRecordTrigger {
  failure_family?: string | null;
  metric_name?: string | null;
  threshold?: number | null;
  operator?: SkillRecordOperator;
  blame_pattern?: string | null;
}

export interface SkillRecordEvalCriterion {
  metric: string;
  target: number;
  operator: SkillRecordOperator;
  weight: number;
}

export interface SkillRecordToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  returns?: Record<string, unknown> | null;
  implementation?: string | null;
  sandbox_policy?: string;
}

export interface SkillRecordPolicy {
  name: string;
  description: string;
  rule_type: string;
  condition: string;
  action: string;
  severity?: string;
}

export interface SkillRecordTestCase {
  name: string;
  description: string;
  input: Record<string, unknown>;
  expected_output?: Record<string, unknown> | null;
  expected_behavior?: string | null;
  assertions: string[];
}

export interface SkillRecordEffectiveness {
  times_applied: number;
  success_count: number;
  success_rate: number;
  avg_improvement: number;
  total_improvement: number;
  last_applied?: number | null;
}

export interface SkillRecordDependency {
  skill_id: string;
  version_constraint: string;
  optional: boolean;
}

export interface SkillRecord {
  skill_id: string;
  name: string;
  kind: SkillRecordKind;
  version: string;
  domain: string;
  description: string;
  status: SkillRecordStatus;
  tags: string[];
  triggers: SkillRecordTrigger[];
  eval_criteria: SkillRecordEvalCriterion[];
  tools: SkillRecordToolDefinition[];
  policies: SkillRecordPolicy[];
  test_cases: SkillRecordTestCase[];
  dependencies: SkillRecordDependency[];
  effectiveness: SkillRecordEffectiveness;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
}
