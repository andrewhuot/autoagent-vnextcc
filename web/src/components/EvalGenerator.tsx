import { useEffect, useState } from 'react';
import { Wand2, Loader2, ArrowRight } from 'lucide-react';
import { useGenerateEvals } from '../lib/api';
import { toastError, toastSuccess } from '../lib/toast';

interface EvalGeneratorProps {
  onSuiteGenerated?: (suiteId: string) => void;
  defaultAgentName?: string;
  defaultAgentConfig?: Record<string, unknown> | null;
}

const PLACEHOLDER_CONFIG = JSON.stringify(
  {
    model: 'claude-sonnet-4-20250514',
    system_prompt: 'You are a helpful assistant...',
    tools: ['web_search', 'code_interpreter'],
    temperature: 0.7,
  },
  null,
  2,
);

export function EvalGenerator({
  onSuiteGenerated,
  defaultAgentName = '',
  defaultAgentConfig = null,
}: EvalGeneratorProps) {
  const [agentName, setAgentName] = useState(defaultAgentName);
  const [agentConfig, setAgentConfig] = useState('');
  const [suiteResult, setSuiteResult] = useState<{
    suite_id: string;
    total_cases: number;
  } | null>(null);

  const generateEvals = useGenerateEvals();

  useEffect(() => {
    if (!defaultAgentName) {
      return;
    }
    setAgentName(defaultAgentName);
  }, [defaultAgentName]);

  useEffect(() => {
    if (!defaultAgentConfig) {
      return;
    }
    setAgentConfig(JSON.stringify(defaultAgentConfig, null, 2));
  }, [defaultAgentConfig]);

  const handleGenerate = () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(agentConfig);
    } catch {
      toastError('Invalid JSON in agent config');
      return;
    }

    generateEvals.mutate(
      { agent_config: parsed, agent_name: agentName || undefined },
      {
        onSuccess: (data) => {
          toastSuccess(`Generated ${data.total_cases} eval cases`);
          setSuiteResult({ suite_id: data.suite_id, total_cases: data.total_cases });
          onSuiteGenerated?.(data.suite_id);
        },
        onError: (err) => {
          toastError(err.message || 'Failed to generate evals');
        },
      },
    );
  };

  if (suiteResult) {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-6">
        <h3 className="text-lg font-semibold text-green-900">Eval Suite Generated</h3>
        <p className="mt-2 text-sm text-green-700">
          Suite <span className="font-mono font-medium">{suiteResult.suite_id}</span> created
          with {suiteResult.total_cases} eval cases.
        </p>
        <div className="mt-4 flex gap-3">
          <button
            onClick={() => setSuiteResult(null)}
            className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
          >
            Generate Another
          </button>
          <button
            onClick={() => onSuiteGenerated?.(suiteResult.suite_id)}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
          >
            Review Generated Evals
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <h3 className="text-lg font-semibold text-gray-900">Generate Eval Suite</h3>
      <p className="mt-1 text-sm text-gray-500">
        Generate a tailored eval suite from the selected agent without copy and paste.
      </p>

      <div className="mt-5 space-y-4">
        <div>
          <label htmlFor="agent-name" className="block text-sm font-medium text-gray-700">
            Agent Name
          </label>
          <input
            id="agent-name"
            type="text"
            value={agentName}
            onChange={(e) => setAgentName(e.target.value)}
            placeholder="e.g. customer-support-agent"
            className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
          />
        </div>

        <div>
          <label htmlFor="agent-config" className="block text-sm font-medium text-gray-700">
            Agent Config (JSON)
          </label>
          {defaultAgentConfig && (
            <p className="mt-1 text-xs text-gray-500">
              Loaded from the currently selected agent. You can tweak it here before generating if needed.
            </p>
          )}
          <textarea
            id="agent-config"
            rows={8}
            value={agentConfig}
            onChange={(e) => setAgentConfig(e.target.value)}
            placeholder={PLACEHOLDER_CONFIG}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 font-mono text-sm text-gray-900 placeholder:text-gray-400 focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
          />
        </div>

        <button
          onClick={handleGenerate}
          disabled={!agentConfig.trim() || generateEvals.isPending}
          className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
        >
          {generateEvals.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Wand2 className="h-4 w-4" />
              Generate Eval Suite
            </>
          )}
        </button>
      </div>
    </div>
  );
}
