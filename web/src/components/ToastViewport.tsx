import { X } from 'lucide-react';
import { classNames } from '../lib/utils';
import { useToastStore } from '../lib/toast';

const toneClasses = {
  success: 'border-green-200 bg-green-50 text-green-900',
  error: 'border-red-200 bg-red-50 text-red-900',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  info: 'border-blue-200 bg-blue-50 text-blue-900',
};

export function ToastViewport() {
  const toasts = useToastStore((state) => state.toasts);
  const dismissToast = useToastStore((state) => state.dismissToast);

  return (
    <div className="pointer-events-none fixed right-4 top-4 z-50 flex w-[min(420px,calc(100vw-2rem))] flex-col gap-3">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={classNames(
            'pointer-events-auto rounded-xl border px-4 py-3 shadow-sm backdrop-blur-sm transition-all duration-200',
            toneClasses[toast.tone]
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold leading-5">{toast.title}</p>
              {toast.description && (
                <p className="mt-1 text-sm opacity-90">{toast.description}</p>
              )}
            </div>
            <button
              aria-label="Dismiss notification"
              onClick={() => dismissToast(toast.id)}
              className="mt-0.5 rounded p-1 opacity-70 transition hover:bg-white/50 hover:opacity-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
