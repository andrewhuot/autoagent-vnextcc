export type DeploymentTargetKind = 'autoagent' | 'cx-studio' | 'adk' | 'mcp' | 'custom';

export interface DeploymentTarget {
  target_id: string;
  name: string;
  kind: DeploymentTargetKind;
  description: string;
  selector: string;
  canary_supported: boolean;
  immediate_supported: boolean;
  requires_approval: boolean;
  metadata?: Record<string, unknown>;
}
