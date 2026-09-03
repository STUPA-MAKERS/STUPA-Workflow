import type { BudgetTreeNode } from './budget-tree.api';
import { toFormatLocale } from '@core/i18n/i18n.service';

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
