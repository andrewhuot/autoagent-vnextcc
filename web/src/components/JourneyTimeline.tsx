interface TimelineNode {
  version: string;
  score: number;
  change: string;
  status: 'accepted' | 'rejected' | 'baseline';
  timestamp: number;
}

interface JourneyTimelineProps {
  nodes: TimelineNode[];
  onNodeClick?: (version: string) => void;
}

function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + '...';
}

export function JourneyTimeline({ nodes, onNodeClick }: JourneyTimelineProps) {
  if (nodes.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-8 text-center text-sm text-gray-500">
        No optimization history yet. Run your first cycle to see your journey.
      </div>
    );
  }

  const totalWidth = nodes.length * 150;
  const currentNodeIndex = nodes.findIndex(node => node.status === 'baseline' || node.version === 'current');

  return (
    <div className="relative">
      <div className="overflow-x-auto pb-4">
        <div className="relative" style={{ minWidth: `${totalWidth}px`, height: '180px' }}>
          {/* SVG line connecting nodes */}
          <svg className="absolute left-0 top-16 h-1" style={{ width: `${totalWidth}px` }}>
            <path
              d={`M 75 0 L ${totalWidth - 75} 0`}
              stroke="#d1d5db"
              strokeWidth="2"
              className="timeline-path"
            />
          </svg>

          {/* Timeline nodes */}
          <div className="relative">
            {nodes.map((node, i) => {
              const isCurrent = i === currentNodeIndex || (currentNodeIndex === -1 && i === nodes.length - 1);
              const statusClass =
                node.status === 'accepted'
                  ? 'bg-green-500 border-green-600'
                  : node.status === 'rejected'
                  ? 'bg-red-500 border-red-600'
                  : 'bg-gray-400 border-gray-500';

              return (
                <div
                  key={node.version}
                  className="absolute"
                  style={{ left: `${i * 150}px`, top: 0, width: '150px' }}
                >
                  {/* Change description above */}
                  <div className="mb-2 text-center text-xs text-gray-600" style={{ height: '32px' }}>
                    {truncate(node.change, 20)}
                  </div>

                  {/* Node circle */}
                  <div className="flex justify-center">
                    <button
                      onClick={() => onNodeClick?.(node.version)}
                      className={`relative flex h-12 w-12 items-center justify-center rounded-full border-2 transition-all hover:scale-110 ${statusClass} ${
                        isCurrent ? 'node-circle-current ring-4 ring-blue-200 ring-opacity-50' : ''
                      }`}
                    >
                      <span className="text-xs font-semibold text-white">{node.version}</span>
                    </button>
                  </div>

                  {/* Score below */}
                  <div className="mt-2 text-center text-sm font-medium text-gray-900">
                    {node.score.toFixed(4)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <style>{`
        .timeline-path {
          stroke-dasharray: 1000;
          animation: draw-line 2s ease-out forwards;
        }

        @keyframes draw-line {
          from { stroke-dashoffset: 1000; }
          to { stroke-dashoffset: 0; }
        }

        .node-circle-current {
          animation: pulse-ring 2s infinite;
        }

        @keyframes pulse-ring {
          0%, 100% {
            transform: scale(1);
            opacity: 1;
          }
          50% {
            transform: scale(1.05);
            opacity: 0.9;
          }
        }
      `}</style>
    </div>
  );
}
