import type { DiffLine } from '../lib/types';
import { DiffViewer } from './DiffViewer';

interface YamlDiffProps {
  lines: DiffLine[];
  versionA: number;
  versionB: number;
}

export function YamlDiff({ lines, versionA, versionB }: YamlDiffProps) {
  return <DiffViewer lines={lines} versionA={versionA} versionB={versionB} />;
}
