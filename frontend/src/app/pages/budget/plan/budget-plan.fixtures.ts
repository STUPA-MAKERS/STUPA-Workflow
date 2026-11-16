import type { BudgetTreeNode, FiscalYear } from '../budget-tree.api';
import type { BudgetPlan, PlanLine, PlanVersion, Side } from './budget-plan.api';

/** A tree node with every field set. */
export function node(over: Partial<BudgetTreeNode> & { readonly id: string }): BudgetTreeNode {
  return {
    parentId: null,
    gremiumId: null,
    key: over.id,
    pathKey: over.id.toUpperCase(),
    name: `Node ${over.id}`,
    currency: 'EUR',
    active: true,
    color: null,
    viewGremiumId: null,
    fiscalStartMonth: 3,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [],
    ...over,
  };
}

const figures = (fiscalYearId: string, income: string, expended: string) => ({
  fiscalYearId,
  allocated: '0',
  bound: '0',
  expended,
  income,
  committed: '0',
  requested: '0',
  available: '0',
});

/**
 * VSM → fees (income), other (income, no line), staff (expense) → wages,
 * grants (expense).
 */
export const TOP: BudgetTreeNode = node({
  id: 'vsm',
  name: 'VS-Mittel',
  planEnabled: true,
  children: [
    node({ id: 'fees', parentId: 'vsm', name: 'Beiträge', byFiscalYear: [figures('fy-25', '90', '0')] }),
    node({ id: 'other', parentId: 'vsm', name: 'Sonstige Einnahmen' }),
    node({
      id: 'staff',
      parentId: 'vsm',
      name: 'Personal',
      children: [
        node({ id: 'wages', parentId: 'staff', pathKey: 'STAFF-WAGES', name: 'Löhne', byFiscalYear: [figures('fy-25', '0', '55')] }),
        node({ id: 'fees2', parentId: 'staff', name: 'Honorare' }),
      ],
    }),
    node({ id: 'grants', parentId: 'vsm', name: 'Zuschüsse' }),
    node({ id: 'noside', parentId: 'vsm', name: 'Ohne Seite' }),
  ],
});

export const QSM: BudgetTreeNode = node({ id: 'qsm', name: 'QS-Mittel' });

export const fy = (id: string, year: number, over: Partial<FiscalYear> = {}): FiscalYear => ({
  id,
  budgetId: 'vsm',
  year,
  display: `${year}/${(year + 1) % 100}`,
  startDate: `${year}-03-01`,
  endDate: `${year + 1}-02-28`,
  active: true,
  closedAt: null,
  ...over,
});
export const FY25 = fy('fy-25', 2025);
export const FY26 = fy('fy-26', 2026);

/** The side that the server answers for a line: the side of its Titel. `noside` has none. */
const SIDES: Readonly<Record<string, Side>> = {
  fees: 'income',
  other: 'income',
  staff: 'expense',
  wages: 'expense',
  fees2: 'expense',
  grants: 'expense',
};

export const line = (budgetId: string, amount: string, over: Partial<PlanLine> = {}): PlanLine => ({
  budgetId,
  side: SIDES[budgetId] ?? null,
  amount,
  note: null,
  name: null,
  pathKey: null,
  key: null,
  transferable: false,
  coverable: false,
  blocked: '0',
  ...over,
});

export const version = (over: Partial<PlanVersion> = {}): PlanVersion => ({
  id: 'v0',
  number: 0,
  state: 'draft',
  createdAt: '2026-01-02T10:00:00Z',
  inForceAt: null,
  steps: [],
  lines: [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', '30')],
  ...over,
});

export const plan = (versions: readonly PlanVersion[] = [version()], fiscalYearId = 'fy-26'): BudgetPlan => ({
  id: `plan-${fiscalYearId}`,
  budgetId: 'vsm',
  fiscalYearId,
  versions,
});

/** A budget with only the Kostenstellen of the default version, as the parent picker gets it. */
export const planTreeOf = (top: BudgetTreeNode): BudgetTreeNode => {
  const ids = new Set(version().lines.map((l) => l.budgetId));
  const kept = (nodes: readonly BudgetTreeNode[]): readonly BudgetTreeNode[] =>
    nodes.filter((n) => ids.has(n.id)).map((n) => ({ ...n, children: kept(n.children) }));
  return { ...top, children: kept(top.children) };
};
