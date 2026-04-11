export interface CompatInfo {
  adk: boolean;
  cx: boolean;
}

export const WORKBENCH_COMPAT: Record<string, CompatInfo> = {
  // tools
  'web_search': { adk: true, cx: true },
  'http_request': { adk: true, cx: true },
  'code_interpreter': { adk: true, cx: false },
  'rag_retrieval': { adk: true, cx: true },
  'function_call': { adk: true, cx: true },
  // policies
  'pii_redaction': { adk: true, cx: true },
  'content_filter': { adk: true, cx: true },
  'rate_limit': { adk: true, cx: true },
  'auth_required': { adk: true, cx: true },
  // routing
  'multi_agent': { adk: true, cx: false },
  'streaming': { adk: true, cx: true },
  'memory_persistent': { adk: true, cx: true },
};

export function getCompat(feature: string): CompatInfo {
  return WORKBENCH_COMPAT[feature] ?? { adk: true, cx: true };
}
