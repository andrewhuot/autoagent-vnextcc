import { Hammer, Wrench, Search } from 'lucide-react';
import { classNames } from '../../lib/utils';

interface QuickActionsProps {
  suggestions: string[];
  onActionClick: (action: string) => void;
  disabled?: boolean;
}

const ACTION_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  build: Hammer,
  optimize: Wrench,
  explore: Search,
};

function getActionIcon(suggestion: string): React.ComponentType<{ className?: string }> | null {
  const lowerSuggestion = suggestion.toLowerCase();
  if (lowerSuggestion.includes('build')) return ACTION_ICONS.build;
  if (lowerSuggestion.includes('optimize') || lowerSuggestion.includes('fix')) return ACTION_ICONS.optimize;
  if (lowerSuggestion.includes('explore') || lowerSuggestion.includes('search')) return ACTION_ICONS.explore;
  return null;
}

export function QuickActions({ suggestions, onActionClick, disabled = false }: QuickActionsProps) {
  if (suggestions.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {suggestions.map((suggestion, index) => {
        const Icon = getActionIcon(suggestion);
        return (
          <button
            key={index}
            onClick={() => onActionClick(suggestion)}
            disabled={disabled}
            className={classNames(
              'inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition',
              disabled
                ? 'cursor-not-allowed border-gray-200 bg-gray-100 text-gray-400'
                : 'border-gray-300 bg-white text-gray-700 hover:border-gray-400 hover:bg-gray-50'
            )}
          >
            {Icon && <Icon className="h-4 w-4" />}
            {suggestion}
          </button>
        );
      })}
    </div>
  );
}
