import { useEffect, useState } from 'react';

interface ConfettiProps {
  trigger: boolean;
  duration?: number;
}

const COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6'];

interface Particle {
  id: number;
  color: string;
  angle: number;
  distance: number;
}

export function Confetti({ trigger, duration = 2000 }: ConfettiProps) {
  const [particles, setParticles] = useState<Particle[]>([]);

  useEffect(() => {
    if (!trigger) return;

    // Generate 20 particles with random properties
    const newParticles: Particle[] = Array.from({ length: 20 }, (_, i) => ({
      id: i,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      angle: Math.random() * 360,
      distance: 100 + Math.random() * 200, // 100-300px
    }));

    setParticles(newParticles);

    // Auto-cleanup after animation completes
    const timer = setTimeout(() => {
      setParticles([]);
    }, duration);

    return () => clearTimeout(timer);
  }, [trigger, duration]);

  if (particles.length === 0) return null;

  return (
    <div className="fixed inset-0 pointer-events-none z-50 flex items-center justify-center">
      {particles.map((particle) => {
        const angleRad = (particle.angle * Math.PI) / 180;
        const x = Math.cos(angleRad) * particle.distance;
        const y = Math.sin(angleRad) * particle.distance;

        return (
          <div
            key={particle.id}
            className="absolute w-2 h-2 rounded-sm"
            style={{
              backgroundColor: particle.color,
              animation: `confetti-burst ${duration}ms ease-out forwards`,
              // @ts-expect-error CSS custom properties
              '--x': `${x}px`,
              '--y': `${y}px`,
            }}
          />
        );
      })}
    </div>
  );
}
