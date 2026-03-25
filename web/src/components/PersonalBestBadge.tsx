import { useEffect, useState } from 'react';

interface PersonalBestBadgeProps {
  show: boolean;
  onHide: () => void;
}

export function PersonalBestBadge({ show, onHide }: PersonalBestBadgeProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (show) {
      setIsVisible(true);

      // Auto-hide after 5 seconds with fade out
      const timer = setTimeout(() => {
        setIsVisible(false);
        setTimeout(onHide, 300); // Wait for fade out animation
      }, 5000);

      return () => clearTimeout(timer);
    }
  }, [show, onHide]);

  if (!show && !isVisible) return null;

  return (
    <div
      className={`fixed top-4 right-4 z-50 transition-all duration-300 ${
        isVisible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-full'
      }`}
      style={{
        animation: isVisible ? 'slideInRight 0.3s ease-out' : undefined,
      }}
    >
      <div className="bg-gradient-to-r from-yellow-400 to-orange-500 text-white px-6 py-3 rounded-lg shadow-lg flex items-center gap-3">
        <span className="text-2xl">✨</span>
        <span className="font-semibold text-lg">New personal best!</span>
      </div>
    </div>
  );
}
