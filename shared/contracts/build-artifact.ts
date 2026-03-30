export type BuildArtifactSource = 'prompt' | 'transcript' | 'builder_chat' | 'cli';

export type BuildArtifactStatus = 'draft' | 'complete' | 'exported';

export interface BuildArtifact {
  id: string;
  selector: string;
  source: BuildArtifactSource;
  status: BuildArtifactStatus;
  created_at: string;
  updated_at: string;
  config_yaml: string;
  prompt_used?: string;
  transcript_report_id?: string;
  builder_session_id?: string;
  eval_draft?: string;
  starter_config_path?: string;
  metadata?: Record<string, unknown>;
}

export interface BuildArtifactListItem {
  id: string;
  selector: string;
  source: BuildArtifactSource;
  status: BuildArtifactStatus;
  created_at: string;
  updated_at: string;
}
