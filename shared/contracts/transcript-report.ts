export interface TranscriptConversation {
  conversation_id: string;
  session_id: string;
  user_message: string;
  agent_response: string;
  outcome: string;
  language: string;
  intent: string;
  transfer_reason: string | null;
  source_file: string;
  procedure_steps: string[];
}

export interface MissingIntent {
  intent: string;
  count: number;
  reason: string;
}

export interface TranscriptInsight {
  insight_id: string;
  title: string;
  summary: string;
  recommendation: string;
  drafted_change_prompt: string;
  metric_name: string;
  share: number;
  count: number;
  total: number;
  evidence: string[];
}

export interface TranscriptProcedureSummary {
  intent: string;
  steps: string[];
  source_conversation_id: string;
}

export interface TranscriptFaqEntry {
  intent: string;
  question: string;
  answer: string;
}

export interface TranscriptWorkflowSuggestion {
  title: string;
  description: string;
}

export interface TranscriptSuggestedTest {
  name: string;
  user_message: string;
  expected_behavior: string;
}

export interface TranscriptKnowledgeAssetSummary {
  asset_id: string;
  entry_count: number;
}

export interface TranscriptReport {
  report_id: string;
  archive_name: string;
  created_at: string;
  conversation_count: number;
  languages: string[];
  missing_intents: MissingIntent[];
  procedure_summaries: TranscriptProcedureSummary[];
  faq_entries: TranscriptFaqEntry[];
  workflow_suggestions: TranscriptWorkflowSuggestion[];
  suggested_tests: TranscriptSuggestedTest[];
  insights: TranscriptInsight[];
  knowledge_asset: TranscriptKnowledgeAssetSummary;
  conversations: TranscriptConversation[];
  intent_accuracy?: number | null;
  intent_accuracy_samples?: number;
  source?: 'cli' | 'api' | 'ui';
  metadata?: Record<string, unknown>;
}

export interface TranscriptReportSummary {
  report_id: string;
  archive_name: string;
  created_at: string;
  conversation_count: number;
  languages: string[];
  knowledge_asset?: TranscriptKnowledgeAssetSummary;
}
