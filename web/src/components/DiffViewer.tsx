import type { DiffLine } from '../lib/types';
import { classNames } from '../lib/utils';

interface DiffViewerProps {
  lines: DiffLine[];
  versionA: number;
  versionB: number;
}

export function DiffViewer({ lines, versionA, versionB }: DiffViewerProps) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="grid grid-cols-2 border-b border-gray-200">
        <div className="px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500">
          Version {versionA}
        </div>
        <div className="px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 border-l border-gray-200">
          Version {versionB}
        </div>
      </div>
      <div className="overflow-x-auto">
        <div className="grid grid-cols-2 font-mono text-sm">
          <div className="border-r border-gray-200">
            {lines.map((line, i) => (
              <div
                key={`a-${i}`}
                className={classNames(
                  'flex px-4 py-0.5 min-h-[1.5rem]',
                  line.type === 'removed' && 'bg-red-50 text-red-800',
                  line.type === 'added' && 'invisible'
                )}
              >
                {line.type !== 'added' && (
                  <>
                    <span className="w-8 text-right text-gray-400 select-none pr-3 flex-shrink-0">
                      {line.line_a}
                    </span>
                    <span className="flex-1 whitespace-pre">
                      {line.type === 'removed' ? `- ${line.content}` : `  ${line.content}`}
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
          <div>
            {lines.map((line, i) => (
              <div
                key={`b-${i}`}
                className={classNames(
                  'flex px-4 py-0.5 min-h-[1.5rem]',
                  line.type === 'added' && 'bg-green-50 text-green-800',
                  line.type === 'removed' && 'invisible'
                )}
              >
                {line.type !== 'removed' && (
                  <>
                    <span className="w-8 text-right text-gray-400 select-none pr-3 flex-shrink-0">
                      {line.line_b}
                    </span>
                    <span className="flex-1 whitespace-pre">
                      {line.type === 'added' ? `+ ${line.content}` : `  ${line.content}`}
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
