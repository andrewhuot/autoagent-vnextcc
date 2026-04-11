/**
 * Empty state for the right preview pane — matches Image 1's "Processes
 * paused, click to wake up" idiom.
 */

import { Sparkles } from 'lucide-react';

interface EmptyPreviewProps {
  title?: string;
  description?: string;
  cta?: string;
  onCta?: () => void;
}

export function EmptyPreview({
  title = 'Nothing to preview yet',
  description = 'Describe an agent on the left and I\u2019ll build it here.',
  cta,
  onCta,
}: EmptyPreviewProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]">
        <Sparkles className="h-5 w-5" />
      </div>
      <div>
        <h3 className="text-sm font-medium text-[color:var(--wb-text)]">{title}</h3>
        <p className="mt-1 max-w-xs text-[12px] leading-5 text-[color:var(--wb-text-dim)]">{description}</p>
      </div>
      {cta && onCta && (
        <button
          type="button"
          onClick={onCta}
          className="rounded-full border border-[color:var(--wb-border-strong)] px-3 py-1 text-[12px] text-[color:var(--wb-text)] hover:bg-[color:var(--wb-bg-hover)]"
        >
          {cta}
        </button>
      )}
    </div>
  );
}
