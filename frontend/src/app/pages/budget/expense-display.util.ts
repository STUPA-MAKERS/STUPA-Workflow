import type { BudgetTreeNode } from './budget-tree.api';
import { toFormatLocale } from '@core/i18n/i18n.service';
import { simplifyPathKey } from '@shared/budget-path';
import { nodeColors } from './budget-color.util';

/** Format a value as EUR. Money stays a decimal string in the API, so `Number` is UI-only. */
export function formatEur(value: number, locale: string): string {
  return value.toLocaleString(toFormatLocale(locale), {
    style: 'currency',
    currency: 'EUR',
  });
}

export function sortIndicator(active: boolean, order: 'asc' | 'desc'): string {
  if (!active) return '';
  return order === 'asc' ? ' ↑' : ' ↓';
}

export function ariaSortDir(
  active: boolean,
  order: 'asc' | 'desc',
): 'ascending' | 'descending' | 'none' {
  if (!active) return 'none';
  return order === 'asc' ? 'ascending' : 'descending';
}

/** Human-readable `detail` of a problem+json error. */
export function problemDetail(err: unknown): string | null {
  return (err as { error?: { detail?: string } } | null)?.error?.detail || null;
}

/** Machine `code` of a problem+json error. */
export function problemCode(err: unknown): string | undefined {
  return (err as { error?: { code?: string } } | null)?.error?.code;
}

/** Top-level node whose subtree contains `targetId` (fiscal years live at the top). */
export function findTopBudgetNode(
  nodes: BudgetTreeNode[],
  targetId: string,
): BudgetTreeNode | null {
  const contains = (n: BudgetTreeNode): boolean =>
    n.id === targetId || n.children.some(contains);
  return nodes.find((root) => contains(root)) ?? null;
}

/** How a booking row names its cost centre: the name, the path and the swatch colour. */
export interface CostCentreLabel {
  name: string;
  path: string;
  /** The display colour of the budget page (O19). `null` for an unknown cost centre. */
  color: string | null;
}

/** The label of every cost centre of a forest, by id. */
export function costCentreIndex(roots: readonly BudgetTreeNode[]): Map<string, CostCentreLabel> {
  const colors = nodeColors(roots);
  const out = new Map<string, CostCentreLabel>();
  const walk = (nodes: readonly BudgetTreeNode[]): void => {
    for (const n of nodes) {
      out.set(n.id, {
        name: n.name,
        path: simplifyPathKey(n.pathKey),
        color: colors.get(n.id) ?? null,
      });
      walk(n.children);
    }
  };
  walk(roots);
  return out;
}

/**
 * The label of one cost centre. A cost centre outside the loaded tree (a scoped reader,
 * or a tree that failed to load) falls back to its path, which every booking carries.
 */
export function costCentreLabel(
  index: ReadonlyMap<string, CostCentreLabel>,
  id: string,
  pathKey: string | null,
): CostCentreLabel {
  const known = index.get(id);
  if (known) return known;
  const path = pathKey ? simplifyPathKey(pathKey) : '—';
  return { name: path, path, color: null };
}

/**
 * How many columns a bookings or invoice table shows.
 *
 * * `full` — every column. A phone also gets every column: the table stacks into cards
 *   there, and each column says by its card role whether the card shows it.
 * * `compact` — below 1400px the secondary columns go (invoice date and kind of a
 *   booking; net and tax of an invoice), so the description keeps a readable width.
 * * `tight` — below 1000px a third one goes as well.
 *
 * A dropped column moves into a kept cell, as a second line or a tooltip: the payee
 * under the description of a booking and its invoice date into the tooltip of the
 * payment date; the due date under the issue date of an invoice, and net and tax under
 * its gross. A reader without `budget.book` has no dialog, so the value must stay on
 * the row.
 */
export type ColumnSet = 'full' | 'compact' | 'tight';

/** The viewport from which a table shows every column. */
export const COLUMNS_FULL_MEDIA = '(min-width: 1400px)';
/** The viewport below which a table drops to its tightest set. */
export const COLUMNS_TIGHT_MEDIA = '(max-width: 999.98px)';

/** The column set for the viewport flags. */
export function columnSet(flags: { phone: boolean; full: boolean; tight: boolean }): ColumnSet {
  if (flags.phone || flags.full) return 'full';
  return flags.tight ? 'tight' : 'compact';
}
