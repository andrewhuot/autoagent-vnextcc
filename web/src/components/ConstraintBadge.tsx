import { Check, X } from 'lucide-react';

interface ConstraintBadgeProps {
  passed: boolean;
  label: string;
}

export function ConstraintBadge({ passed, label }: ConstraintBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${
        passed
          ? 'bg-green-50 text-green-700'
          : 'bg-red-50 text-red-700'
      }`}
    >
      {passed ? (
        <Check className="h-3 w-3" />
      ) : (
        <X className="h-3 w-3" />
      )}
      {label}
    </span>
  );
}
