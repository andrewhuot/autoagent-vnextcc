import type { DiffLine, DiffHunk } from '../lib/types';
import { classNames } from '../lib/utils';

// ---------------------------------------------------------------------------
// Legacy DiffViewer — takes DiffLine[] for config diff pages
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// HunkDiffViewer — takes DiffHunk[] for change review cards
// ---------------------------------------------------------------------------

interface HunkDiffViewerProps {
  hunks: DiffHunk[];
  onAccept?: (hunkId: string) => void;
  onReject?: (hunkId: string) => void;
}

export function HunkDiffViewer({ hunks, onAccept, onReject }: HunkDiffViewerProps) {
  return (
    <div className="space-y-3">
      {hunks.map((hunk) => {
        const lines = hunk.content.split('\n');
        const isPending = hunk.status === 'pending';
        const showActions = isPending && (onAccept !== undefined || onReject !== undefined);

        return (
          <div key={hunk.hunk_id} className="rounded-lg border border-gray-200 bg-white overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
              <span className="font-mono text-xs text-gray-700 font-medium">{hunk.file_path}</span>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-gray-400 font-mono">
                  @@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@
                </span>
                <span
                  className={classNames(
                    'rounded-md px-1.5 py-0.5 text-[10px] font-medium',
                    hunk.status === 'accepted'
                      ? 'bg-green-50 text-green-700'
                      : hunk.status === 'rejected'
                        ? 'bg-red-50 text-red-700'
                        : 'bg-gray-100 text-gray-600'
                  )}
                >
                  {hunk.status}
                </span>
              </div>
            </div>

            {/* Body — parsed diff content */}
            <pre className="max-h-64 overflow-auto p-3 text-xs font-mono">
              {lines.map((line, i) => (
                <div
                  key={`${hunk.hunk_id}-${i}`}
                  className={classNames(
                    'px-1',
                    line.startsWith('+') ? 'bg-green-50 text-green-800' : '',
                    line.startsWith('-') ? 'bg-red-50 text-red-800' : '',
                    !line.startsWith('+') && !line.startsWith('-') ? 'text-gray-600' : ''
                  )}
                >
                  {line}
                </div>
              ))}
            </pre>

            {/* Footer — Accept/Reject buttons (pending only) */}
            {showActions && (
              <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-3 py-2">
                {onReject && (
                  <button
                    onClick={() => onReject(hunk.hunk_id)}
                    className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700 transition hover:bg-red-100"
                  >
                    Reject hunk
                  </button>
                )}
                {onAccept && (
                  <button
                    onClick={() => onAccept(hunk.hunk_id)}
                    className="inline-flex items-center rounded-md border border-green-200 bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 transition hover:bg-green-100"
                  >
                    Accept hunk
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
