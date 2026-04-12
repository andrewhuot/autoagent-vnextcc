/**
 * Compact inline artifact card shown in the conversation feed.
 *
 * Matches the reference UI: a labeled card with the artifact name, a small
 * summary, and a "view" affordance that focuses it in the right pane.
 */

import { FileCode2, FileJson, FileText, Shield, Sparkles, TestTube2, Wrench } from 'lucide-react';
import { classNames } from '../../lib/utils';
import type { WorkbenchArtifact } from '../../lib/workbench-api';
import { useWorkbenchStore } from '../../lib/workbench-store';
import { SkillLayerBadge } from '../SkillLayerBadge';

const CATEGORY_ICONS: Record<string, typeof Sparkles> = {
  agent: Sparkles,
  tool: Wrench,
  guardrail: Shield,
  eval: TestTube2,
  environment: FileCode2,
  deployment: FileCode2,
  api_call: FileJson,
  plan: FileText,
  note: FileText,
};

interface ArtifactCardProps {
  artifact: WorkbenchArtifact;
  compact?: boolean;
}

export function ArtifactCard({ artifact, compact = false }: ArtifactCardProps) {
  const setActiveArtifact = useWorkbenchStore((s) => s.setActiveArtifact);
  const activeArtifactId = useWorkbenchStore((s) => s.activeArtifactId);
  const Icon = CATEGORY_ICONS[artifact.category] ?? FileText;
  const isActive = activeArtifactId === artifact.id;

  return (
    <button
      type="button"
      onClick={() => setActiveArtifact(artifact.id)}
      className={classNames(
        'group flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition',
        'border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] hover:border-[color:var(--wb-border-strong)]',
        isActive && 'border-[color:var(--wb-accent-border)] bg-[color:var(--wb-accent-weak)]'
      )}
    >
      <span className="mt-0.5 flex h-6 w-6 items-center justify-center rounded bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-soft)]">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className="text-[12px] font-semibold text-[color:var(--wb-text)]">{artifact.name}</span>
          <span className="text-[10px] uppercase tracking-wide text-[color:var(--wb-text-dim)]">
            {artifact.category}
          </span>
          <SkillLayerBadge layer={artifact.skill_layer} />
        </span>
        {!compact && (
          <span className="mt-0.5 block text-[12px] leading-4 text-[color:var(--wb-text-dim)]">
            {artifact.summary}
          </span>
        )}
      </span>
    </button>
  );
}
