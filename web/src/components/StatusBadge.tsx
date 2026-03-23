import { classNames, statusLabel } from '../lib/utils';

type Variant = 'success' | 'error' | 'warning' | 'pending' | 'running';

interface StatusBadgeProps {
  variant: Variant;
  label: string;
}

const variantStyles: Record<Variant, string> = {
  success: 'bg-green-50 text-green-700 border-green-200',
  error: 'bg-red-50 text-red-700 border-red-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  pending: 'bg-gray-50 text-gray-600 border-gray-200',
  running: 'bg-blue-50 text-blue-700 border-blue-200',
};

export function StatusBadge({ variant, label }: StatusBadgeProps) {
  return (
    <span
      className={classNames(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium capitalize',
        variantStyles[variant]
      )}
    >
      {variant === 'running' && (
        <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
      )}
      {statusLabel(label)}
    </span>
  );
}
