import type { FiscalYear } from './budget-tree.api';

/** The newest of some fiscal years (the highest start year), or `null`. */
function newest(fys: readonly FiscalYear[]): FiscalYear | null {
  return fys.reduce<FiscalYear | null>((n, f) => (!n || f.year > n.year ? f : n), null);
}

/**
 * The id of the default fiscal year: the active open year that holds `today`, else the
 * newest active open year, else the newest year. `''` without a year. `today` is an ISO
 * date (`YYYY-MM-DD`).
 */
export function defaultFiscalYearId(
  fys: readonly FiscalYear[],
  today: string = new Date().toISOString().slice(0, 10),
): string {
  const open = fys.filter((f) => f.active && !f.closedAt);
  const current = open.find((f) => f.startDate <= today && today <= f.endDate);
  return (current ?? newest(open) ?? newest(fys))?.id ?? '';
}
