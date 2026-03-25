interface HealthPulseProps {
  score: number; // 0-1
  label?: string;
  size?: 'sm' | 'md' | 'lg';
}

export function HealthPulse({ score, label = 'Agent Health', size = 'md' }: HealthPulseProps) {
  // Determine color and animation based on score
  const getHealthState = (score: number) => {
    if (score > 0.85) {
      return {
        color: '#10b981', // green
        bgColor: '#d1fae5',
        textColor: 'text-green-900',
        status: 'Excellent',
        animation: 'pulse-healthy 3s ease-in-out infinite',
      };
    } else if (score >= 0.65) {
      return {
        color: '#f59e0b', // amber
        bgColor: '#fef3c7',
        textColor: 'text-amber-900',
        status: 'Good',
        animation: 'pulse-warning 1.5s ease-in-out infinite',
      };
    } else {
      return {
        color: '#ef4444', // red
        bgColor: '#fee2e2',
        textColor: 'text-red-900',
        status: 'Needs Attention',
        animation: 'pulse-critical 0.8s ease-in-out infinite',
      };
    }
  };

  const sizeMap = {
    sm: { width: 80, viewBox: '0 0 80 80', cx: 40, cy: 40, r: 33, rInner: 30, fontSize: 'text-lg' },
    md: { width: 120, viewBox: '0 0 120 120', cx: 60, cy: 60, r: 50, rInner: 45, fontSize: 'text-2xl' },
    lg: { width: 160, viewBox: '0 0 160 160', cx: 80, cy: 80, r: 66, rInner: 60, fontSize: 'text-4xl' },
  };

  const dimensions = sizeMap[size];
  const healthState = getHealthState(score);
  const percentage = Math.round(score * 100);

  return (
    <div className="flex flex-col items-center gap-3">
      <svg
        width={dimensions.width}
        height={dimensions.width}
        viewBox={dimensions.viewBox}
        className="health-pulse-svg"
      >
        {/* Animated pulse ring */}
        <circle
          cx={dimensions.cx}
          cy={dimensions.cy}
          r={dimensions.r}
          fill="none"
          stroke={healthState.color}
          strokeWidth="2"
          className="pulse-ring"
          style={{ animation: healthState.animation }}
        />

        {/* Static background circle */}
        <circle cx={dimensions.cx} cy={dimensions.cy} r={dimensions.rInner} fill={healthState.bgColor} />

        {/* Score text */}
        <text
          x={dimensions.cx}
          y={dimensions.cy + (size === 'sm' ? 6 : size === 'md' ? 8 : 12)}
          textAnchor="middle"
          className={`${dimensions.fontSize} font-bold ${healthState.textColor}`}
        >
          {percentage}
        </text>
      </svg>

      {/* Label and status */}
      <div className="text-center">
        <p className="text-xs font-medium text-gray-500">{label}</p>
        <p className={`text-sm font-semibold ${healthState.textColor}`}>{healthState.status}</p>
      </div>

      <style>{`
        @keyframes pulse-healthy {
          0%, 100% {
            r: ${dimensions.r};
            opacity: 0.8;
          }
          50% {
            r: ${dimensions.r + 5};
            opacity: 0.4;
          }
        }

        @keyframes pulse-warning {
          0%, 100% {
            r: ${dimensions.r};
            opacity: 0.8;
          }
          50% {
            r: ${dimensions.r + 5};
            opacity: 0.4;
          }
        }

        @keyframes pulse-critical {
          0%, 100% {
            r: ${dimensions.r};
            opacity: 1;
          }
          50% {
            r: ${dimensions.r + 6};
            opacity: 0.3;
          }
        }

        .pulse-ring {
          transform-origin: center;
        }
      `}</style>
    </div>
  );
}
