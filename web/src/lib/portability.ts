import type { PortabilityReport } from './types';

export interface PortabilityReportCarrier {
  portability_report?: PortabilityReport | null;
  portability?: PortabilityReport | null;
}

export function getImportPortabilityReport(
  result: PortabilityReportCarrier | null | undefined
): PortabilityReport | null {
  return result?.portability_report ?? result?.portability ?? null;
}
