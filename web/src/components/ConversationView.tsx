import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { ConversationTurn } from '../lib/types';
import { StatusBadge } from './StatusBadge';
import { classNames, statusVariant } from '../lib/utils';

interface ConversationViewProps {
  turns: ConversationTurn[];
  outcome: string;
}

function ToolCallBlock({ turn }: { turn: ConversationTurn }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mx-8 my-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors duration-150"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span className="font-mono">{turn.tool_name}</span>
      </button>
      {expanded && (
        <div className="mt-1 ml-4 space-y-1">
          {turn.tool_input && (
            <div className="bg-gray-50 rounded p-2 text-xs font-mono text-gray-700 overflow-x-auto">
              <div className="text-gray-400 text-[10px] uppercase mb-1">Input</div>
              <pre className="whitespace-pre-wrap">{turn.tool_input}</pre>
            </div>
          )}
          {turn.tool_output && (
            <div className="bg-gray-50 rounded p-2 text-xs font-mono text-gray-700 overflow-x-auto">
              <div className="text-gray-400 text-[10px] uppercase mb-1">Output</div>
              <pre className="whitespace-pre-wrap">{turn.tool_output}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ConversationView({ turns, outcome }: ConversationViewProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <StatusBadge variant={statusVariant(outcome)} label={outcome} />
      </div>
      <div className="space-y-2">
        {turns.map((turn, i) => {
          if (turn.role === 'tool') {
            return <ToolCallBlock key={i} turn={turn} />;
          }

          const isUser = turn.role === 'user';
          const isAgent = turn.role === 'agent';
          return (
            <div
              key={i}
              className={classNames(
                'flex',
                isUser ? 'justify-end' : 'justify-start'
              )}
            >
              <div
                className={classNames(
                  'max-w-[75%] rounded-lg px-3 py-2 text-sm',
                  isUser
                    ? 'bg-blue-600 text-white'
                    : isAgent
                      ? 'bg-gray-100 text-gray-900'
                      : 'bg-amber-50 text-amber-900'
                )}
              >
                <p className="whitespace-pre-wrap">{turn.content}</p>
                {turn.timestamp && (
                  <p
                    className={classNames(
                      'text-[10px] mt-1',
                      isUser ? 'text-blue-200' : 'text-gray-400'
                    )}
                  >
                    {new Date(turn.timestamp).toLocaleTimeString()}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
