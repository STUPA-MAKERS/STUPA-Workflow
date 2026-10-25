import type { BudgetAllocationView, BudgetTreeNode, ExpenseKind } from './budget-tree.api';
import { formatMoney } from '@shared/format-money';
import { simplifyPathKey } from '@shared/budget-path';
import { nodeColors } from './budget-color.util';

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
  /** The display colour of the budget page. `null` for an unknown cost centre. */
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
 * The amount with its sign: "−" for an expense, "+" for an income. The sign comes from the
 * kind, not from the number, because the API keeps every amount positive. `locale` is the
 * format locale (`de-DE` / `en-GB`).
 */
export function signedEur(kind: ExpenseKind, amount: string, locale: string): string {
  return (kind === 'income' ? '+' : '−') + formatMoney(amount, locale);
}

/** A node of the forest by id, or null. */
export function findBudgetNode(nodes: readonly BudgetTreeNode[], id: string): BudgetTreeNode | null {
  for (const n of nodes) {
    if (n.id === id) return n;
    const hit = findBudgetNode(n.children, id);
    if (hit) return hit;
  }
  return null;
}

/**
 * The names on the way to a cost centre below its root, for example "Fachschaften ›
 * Maschinenbau". The root (the whole budget) is left out unless it is the cost centre
 * itself. Null for a cost centre outside the forest.
 */
export function costCentreTrail(nodes: readonly BudgetTreeNode[], id: string): string | null {
  const walk = (list: readonly BudgetTreeNode[], trail: string[]): string[] | null => {
    for (const n of list) {
      const next = [...trail, n.name];
      if (n.id === id) return next;
      const hit = walk(n.children, next);
      if (hit) return hit;
    }
    return null;
  };
  const names = walk(nodes, []);
  if (!names) return null;
  return (names.length > 1 ? names.slice(1) : names).join(' › ');
}

/** The figures of a cost centre in one fiscal year, as numbers. */
export interface CostCentreFigures {
  allocated: number;
  expended: number;
  bound: number;
  available: number;
}

/** The figures of a node in a fiscal year, or null when the year has no allocation row. */
export function costCentreFigures(
  node: BudgetTreeNode | null,
  fiscalYearId: string,
): CostCentreFigures | null {
  const row: BudgetAllocationView | undefined = node?.byFiscalYear.find(
    (f) => f.fiscalYearId === fiscalYearId,
  );
  if (!row) return null;
  return {
    allocated: Number(row.allocated),
    expended: Number(row.expended),
    bound: Number(row.bound),
    available: Number(row.available),
  };
}

/** The common VAT rates in percent. Only these show as a rate. */
const VAT_RATES = [0, 5, 7, 16, 19];

/**
 * The VAT rate of an invoice in percent, when tax / net gives one of the common rates
 * (to 0.1 percentage points). Null otherwise, or when net or tax is missing.
 */
export function vatRate(net: string | null, tax: string | null): number | null {
  if (net === null || tax === null) return null;
  const n = Number(net);
  const t = Number(tax);
  if (!(n > 0) || !Number.isFinite(t)) return null;
  const rate = (t / n) * 100;
  return VAT_RATES.find((r) => Math.abs(r - rate) < 0.1) ?? null;
}
