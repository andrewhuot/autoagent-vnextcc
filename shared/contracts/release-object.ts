export type ReleaseObjectStatus = 'DRAFT' | 'SIGNED' | 'DEPLOYED' | 'ROLLED_BACK' | 'SUPERSEDED';

export interface ReleaseObject {
  release_id: string;
  version: string;
  status: ReleaseObjectStatus;
  code_diff: Record<string, unknown>;
  config_diff: Record<string, unknown>;
  prompt_diff: Record<string, unknown>;
  dataset_version: string;
  eval_results: Record<string, unknown>;
  grader_versions: Record<string, string>;
  judge_versions: Record<string, string>;
  skill_versions: Record<string, string>;
  model_version: string;
  risk_class: string;
  approval_chain: Array<Record<string, unknown>>;
  canary_plan: Record<string, unknown>;
  rollback_instructions: string;
  business_outcomes: Record<string, unknown>;
  created_at: string;
  signed_at?: string | null;
  signature?: string | null;
  metadata?: Record<string, unknown>;
}
