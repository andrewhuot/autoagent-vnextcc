/**
 * SkillLayerBadge — tiny badge showing the skill layer of an artifact.
 *
 * Displays "Build", "Runtime", or nothing (when the layer is "none" or absent).
 * Used inline on artifact cards in the Workbench to make the skill layer
 * visible to operators without adding noise.
 */

import type { SkillLayer } from '../lib/workbench-api';

const LAYER_STYLES: Record<string, string> = {
  build: 'bg-amber-100 text-amber-700',
  runtime: 'bg-teal-100 text-teal-700',
};

const LAYER_LABELS: Record<string, string> = {
  build: 'Build',
  runtime: 'Runtime',
};

interface SkillLayerBadgeProps {
  layer?: SkillLayer | null;
  className?: string;
}

export function SkillLayerBadge({ layer, className = '' }: SkillLayerBadgeProps) {
  if (!layer || layer === 'none') return null;

  const style = LAYER_STYLES[layer] ?? 'bg-zinc-100 text-zinc-600';
  const label = LAYER_LABELS[layer] ?? layer;

  return (
    <span
      className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${style} ${className}`}
    >
      {label}
    </span>
  );
}
