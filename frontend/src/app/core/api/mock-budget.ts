import type {
  BudgetAllocationView,
  BudgetApplication,
  BudgetTreeNode,
  FiscalYear,
} from '../../pages/budget/budget-tree.api';

/**
 * Demo data of the budget tree for the mock backend (`?mock=1`). Dev and tests only.
 *
 * One top budget with two fiscal years. Three sub cost centres carry their own colour,
 * one sub cost centre inherits it, and the rest have none, so the page shows every
 * colour case (O19). The rollups are consistent: a parent sums its children plus what it
 * keeps for itself.
 */

const FY_CURRENT = 'f1000000-0000-0000-0000-000000000001';
const FY_PREVIOUS = 'f1000000-0000-0000-0000-000000000002';
const ROOT = 'b1000000-0000-0000-0000-000000000001';

/** An allocation view from the five stored amounts. */
function alloc(
  fiscalYearId: string,
  allocated: number,
  bound: number,
  expended: number,
  income = 0,
  requested = 0,
): BudgetAllocationView {
  const committed = bound + expended;
  return {
    fiscalYearId,
    allocated: allocated.toFixed(2),
    bound: bound.toFixed(2),
    expended: expended.toFixed(2),
    income: income.toFixed(2),
    committed: committed.toFixed(2),
    requested: requested.toFixed(2),
    available: (allocated - committed + income).toFixed(2),
  };
}

interface Spec {
  id: string;
  key: string;
  name: string;
  color?: string;
  /** allocated, bound, expended, income, requested in the current year. */
  cur: [number, number, number, number?, number?];
  children?: Spec[];
}

const SPEC: Spec = {
  id: ROOT,
  key: 'HH',
  name: 'Haushalt Studierendenschaft',
  cur: [120000, 15000, 28000, 600, 7400],
  children: [
    {
      id: 'b1000000-0000-0000-0000-000000000010',
      key: '100',
      name: 'Referate',
      cur: [40000, 6000, 15000, 0, 2400],
      children: [
        { id: 'b1000000-0000-0000-0000-000000000011', key: '110', name: 'Öffentlichkeitsarbeit', cur: [15000, 2000, 7000, 0, 900] },
        { id: 'b1000000-0000-0000-0000-000000000012', key: '120', name: 'Kultur und Veranstaltungen', cur: [25000, 4000, 8000, 0, 1500] },
      ],
    },
    {
      id: 'b1000000-0000-0000-0000-000000000020',
      key: '200',
      name: 'Fachschaften',
      cur: [36000, 7000, 9500, 600, 5000],
      children: [
        { id: 'b1000000-0000-0000-0000-000000000021', key: '210', name: 'Fachschaft Technik', color: '#2f7fc1', cur: [12000, 2500, 3500, 0, 1800] },
        { id: 'b1000000-0000-0000-0000-000000000022', key: '220', name: 'Fachschaft Wirtschaft', color: '#e08a1e', cur: [10000, 1500, 3000, 0, 2000] },
        {
          id: 'b1000000-0000-0000-0000-000000000023',
          key: '230',
          name: 'Fachschaft Gestaltung und angewandte Medien',
          color: '#b8323a',
          cur: [14000, 3000, 3000, 600, 1200],
          children: [
            { id: 'b1000000-0000-0000-0000-000000000024', key: '231', name: 'Werkstatt', cur: [4000, 1000, 1200, 600, 0] },
          ],
        },
      ],
    },
    { id: 'b1000000-0000-0000-0000-000000000030', key: '300', name: 'Hochschulsport', cur: [20000, 2000, 3500] },
    { id: 'b1000000-0000-0000-0000-000000000040', key: '900', name: 'Rücklage', cur: [24000, 0, 0] },
  ],
};

function build(spec: Spec, parent: BudgetTreeNode | null): BudgetTreeNode {
  const [allocated, bound, expended, income = 0, requested = 0] = spec.cur;
  const node: BudgetTreeNode = {
    id: spec.id,
    parentId: parent?.id ?? null,
    gremiumId: null,
    key: spec.key,
    pathKey: parent ? `${parent.pathKey}-${spec.key}` : spec.key,
    name: spec.name,
    currency: 'EUR',
    active: true,
    color: spec.color ?? null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [
      alloc(FY_CURRENT, allocated, bound, expended, income, requested),
      // The previous year: the same allocation, all spent.
      alloc(FY_PREVIOUS, allocated, 0, allocated * 0.9),
    ],
    children: [],
  };
  node.children = (spec.children ?? []).map((c) => build(c, node));
  return node;
}

export const MOCK_BUDGET_TREE: BudgetTreeNode[] = [build(SPEC, null)];

const MOCK_FISCAL_YEARS: FiscalYear[] = [
  { id: FY_CURRENT, budgetId: ROOT, year: 2026, display: '2026', startDate: '2026-01-01', endDate: '2026-12-31', active: true },
  { id: FY_PREVIOUS, budgetId: ROOT, year: 2025, display: '2025', startDate: '2025-01-01', endDate: '2025-12-31', active: true },
];

/** GET /budgets/{id}/fiscal-years: the years of the top budget above the node. */
export function mockFiscalYears(_budgetId: string): FiscalYear[] {
  return MOCK_FISCAL_YEARS;
}

const STATE_REVIEW = { label: { de: 'In Prüfung', en: 'In review' }, color: '#d9a400' };
const STATE_AGENDA = { label: { de: 'Auf Tagesordnung', en: 'On the agenda' }, color: '#2f7fc1' };
const STATE_APPROVED = { label: { de: 'Bewilligt', en: 'Approved' }, color: '#3f9a5c' };

const MOCK_BUDGET_APPS: BudgetApplication[] = [
  ['c1000000-0000-0000-0000-000000000001', 'Lötstation für die Projektwerkstatt', '21', '1800.00', STATE_AGENDA, '2026-05-12T09:00:00Z'],
  ['c1000000-0000-0000-0000-000000000002', 'Exkursion zum Logistikzentrum', '22', '2000.00', STATE_REVIEW, '2026-05-20T10:30:00Z'],
  ['c1000000-0000-0000-0000-000000000003', 'Siebdruckrahmen für die Werkstatt', '24', '1200.00', STATE_APPROVED, '2026-04-02T14:00:00Z'],
  ['c1000000-0000-0000-0000-000000000004', 'Plakatdruck Sommerfest', '11', '900.00', STATE_REVIEW, '2026-06-01T08:15:00Z'],
  ['c1000000-0000-0000-0000-000000000005', 'Lesung im Foyer', '12', '1500.00', STATE_AGENDA, '2026-03-18T16:45:00Z'],
].map(([applicationId, title, nodeSuffix, amount, state, createdAt]) => {
  const s = state as typeof STATE_REVIEW;
  const nodeId = `b1000000-0000-0000-0000-0000000000${nodeSuffix as string}`;
  return {
    applicationId: applicationId as string,
    title: title as string,
    budgetId: nodeId,
    pathKey: findNode(MOCK_BUDGET_TREE, nodeId)?.pathKey ?? null,
    fiscalYearId: FY_CURRENT,
    amount: amount as string,
    currency: 'EUR',
    stateId: null,
    stateLabel: s.label,
    stateColor: s.color,
    createdAt: createdAt as string,
  };
});

function findNode(nodes: BudgetTreeNode[], id: string): BudgetTreeNode | null {
  for (const n of nodes) {
    if (n.id === id) return n;
    const hit = findNode(n.children, id);
    if (hit) return hit;
  }
  return null;
}

function subtreeIds(node: BudgetTreeNode): Set<string> {
  const out = new Set<string>([node.id]);
  for (const c of node.children) for (const id of subtreeIds(c)) out.add(id);
  return out;
}

/** GET /budgets/{id}/applications: the applications of the node and its subtree. */
export function mockBudgetApplications(budgetId: string, fiscalYearId: string | null): BudgetApplication[] {
  const node = findNode(MOCK_BUDGET_TREE, budgetId);
  if (!node) return [];
  const ids = subtreeIds(node);
  return MOCK_BUDGET_APPS.filter(
    (a) => a.budgetId !== null && ids.has(a.budgetId) && (!fiscalYearId || a.fiscalYearId === fiscalYearId),
  );
}

/** The answer of a GET on one of the budget routes above. */
export function mockBudgetGet(path: string, fiscalYear: string | null): unknown {
  const fy = /\/budgets\/([^/]+)\/fiscal-years$/.exec(path);
  if (fy) return mockFiscalYears(fy[1]);
  const apps = /\/budgets\/([^/]+)\/applications$/.exec(path);
  if (apps) return mockBudgetApplications(apps[1], fiscalYear);
  return MOCK_BUDGET_TREE;
}
