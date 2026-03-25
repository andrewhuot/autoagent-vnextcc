interface LiveCycleCardProps {
  cycle: number;
  changeDescription: string;
  scoreDelta: number;
  accepted: boolean;
}

export function LiveCycleCard({ cycle, changeDescription, scoreDelta, accepted }: LiveCycleCardProps) {
  return (
    <div className="live-cycle-card border border-gray-200 rounded-lg p-4 bg-white shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-gray-700">Cycle #{cycle}</h4>
        <span
          className={`
            px-2 py-1 rounded text-xs font-medium
            ${accepted ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}
          `}
        >
          {accepted ? 'Accepted' : 'Rejected'}
        </span>
      </div>

      {/* Change Description */}
      <p className="text-sm text-gray-600 mb-3 line-clamp-2">
        {changeDescription}
      </p>

      {/* Score Delta */}
      <div className="flex items-center gap-1 text-sm">
        <span className="text-gray-500">Score:</span>
        <span className={`font-medium ${scoreDelta > 0 ? 'text-green-600' : 'text-red-600'}`}>
          {scoreDelta > 0 ? '↑' : '↓'} {Math.abs(scoreDelta).toFixed(4)}
        </span>
      </div>

      <style>{`
        @keyframes slideInUp {
          from {
            transform: translateY(20px);
            opacity: 0;
          }
          to {
            transform: translateY(0);
            opacity: 1;
          }
        }

        .live-cycle-card {
          animation: slideInUp 0.4s ease-out;
        }

        .line-clamp-2 {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
      `}</style>
    </div>
  );
}
