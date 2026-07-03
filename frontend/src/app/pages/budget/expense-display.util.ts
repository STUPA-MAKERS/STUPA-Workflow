import type { BudgetTreeNode } from './budget-tree.api';

/** EUR formatting; money stays a decimal string in the API, `Number` is UI-only. */
export function formatEur(value: number, locale: string): string {
  return value.toLocaleString(locale === 'en' ? 'en-US' : 'de-DE', {
    style: 'currency',
    currency: 'EUR',
  });
}

/** Arrow suffix for the active sort column ('' when inactive). */
export function sortIndicator(active: boolean, order: 'asc' | 'desc'): string {
  if (!active) return '';
  return order === 'asc' ? ' ↑' : ' ↓';
}

/** aria-sort value for a sortable column header. */
export function ariaSortDir(
  active: boolean,
  order: 'asc' | 'desc',
): 'ascending' | 'descending' | 'none' {
  if (!active) return 'none';
  return order === 'asc' ? 'ascending' : 'descending';
}

/** Human-readable `detail` of a problem+json error, or null. */
export function problemDetail(err: unknown): string | null {
  return (err as { error?: { detail?: string } } | null)?.error?.detail || null;
}

/** Machine `code` of a problem+json error, or undefined. */
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
