import type { BudgetTreeNode } from './budget-tree.api';
import {
  costCentreFigures,
  costCentreIndex,
  costCentreLabel,
  costCentreTrail,
  daysUntil,
  findBudgetNode,
  findTopBudgetNode,
  formatEur,
  monthGroups,
  problemCode,
  problemDetail,
  shortDate,
  signedEur,
  vatRate,
} from './expense-display.util';

function node(id: string, children: BudgetTreeNode[] = []): BudgetTreeNode {
  return {
    id,
    parentId: null,
    gremiumId: null,
    key: id,
    pathKey: id,
    name: id,
    currency: 'EUR',
    active: true,
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children,
  };
}

describe('expense-display.util', () => {
  it('formatEur formats per locale', () => {
    expect(formatEur(120, 'de').replace(/\s/g, ' ')).toContain('120,00');
    expect(formatEur(120, 'en')).toMatch(/120\.00/);
    expect(formatEur(-42.5, 'de').replace(/\s/g, ' ')).toContain('-42,50');
  });

  it('problemDetail / problemCode read problem+json fields defensively', () => {
    expect(problemDetail({ error: { detail: 'Zu wenig Budget' } })).toBe('Zu wenig Budget');
    expect(problemDetail({ error: {} })).toBeNull();
    expect(problemDetail(undefined)).toBeNull();
    expect(problemDetail({ error: { detail: '' } })).toBeNull();
    expect(problemCode({ error: { code: 'x' } })).toBe('x');
    expect(problemCode(null)).toBeUndefined();
  });

  it('findTopBudgetNode returns the root containing the target id', () => {
    const tree = [node('top-1', [node('child-1')]), node('top-2')];
    expect(findTopBudgetNode(tree, 'child-1')?.id).toBe('top-1');
    expect(findTopBudgetNode(tree, 'top-2')?.id).toBe('top-2');
    expect(findTopBudgetNode(tree, 'ghost')).toBeNull();
  });
});

describe('cost-centre labels', () => {
  it('indexes every node with its name, path and display colour', () => {
    const child = { ...node('c'), name: 'Kultur', pathKey: 'VS-120' };
    const root = { ...node('r', [child]), color: '#2f7fc1' };
    const index = costCentreIndex([root]);
    expect(index.get('r')).toEqual({ name: 'r', path: 'r', color: '#2f7fc1' });
    // The child inherits the colour of its parent (O19), in a shade of it.
    expect(index.get('c')?.name).toBe('Kultur');
    expect(index.get('c')?.path).toBe('VS-120');
    expect(index.get('c')?.color).toMatch(/^#/);
  });

  it('falls back to the path, or a dash, outside the tree', () => {
    const index = costCentreIndex([]);
    expect(costCentreLabel(index, 'x', 'VS-900')).toEqual({ name: 'VS-900', path: 'VS-900', color: null });
    expect(costCentreLabel(index, 'x', null)).toEqual({ name: '—', path: '—', color: null });
  });
});

describe('finance helpers (FE10c)', () => {
  const tree = [
    {
      ...node('top', [
        {
          ...node('fs', [
            {
              ...node('mb'),
              name: 'Maschinenbau',
              byFiscalYear: [
                {
                  fiscalYearId: 'fy',
                  allocated: '100',
                  bound: '10',
                  expended: '20',
                  income: '0',
                  committed: '30',
                  requested: '0',
                  available: '70',
                },
              ],
            },
          ]),
          name: 'Fachschaften',
        },
      ]),
      name: 'Gesamthaushalt',
    },
  ];

  it('signs an amount by its kind', () => {
    expect(signedEur('expense', '12.5', 'de').replace(/\s/g, ' ')).toBe('−12,50 €');
    expect(signedEur('income', '12.5', 'en')).toMatch(/^\+€12\.50$/);
  });

  it('finds a node and its trail below the root', () => {
    expect(findBudgetNode(tree, 'mb')?.name).toBe('Maschinenbau');
    expect(findBudgetNode(tree, 'none')).toBeNull();
    expect(costCentreTrail(tree, 'mb')).toBe('Fachschaften › Maschinenbau');
    expect(costCentreTrail(tree, 'top')).toBe('Gesamthaushalt');
    expect(costCentreTrail(tree, 'none')).toBeNull();
  });

  it('reads the figures of a node in a fiscal year', () => {
    expect(costCentreFigures(findBudgetNode(tree, 'mb'), 'fy')).toEqual({
      allocated: 100,
      expended: 20,
      bound: 10,
      available: 70,
    });
    expect(costCentreFigures(findBudgetNode(tree, 'mb'), 'other')).toBeNull();
    expect(costCentreFigures(null, 'fy')).toBeNull();
  });

  it('groups rows by month in their order, a row without a date on its own', () => {
    const rows = ['2026-09-28', '2026-09-01', null, '2026-08-12', '2026-09-03'];
    const groups = monthGroups(rows, (r) => r, 'de');
    expect(groups.map((g) => [g.key, g.label, g.items.length])).toEqual([
      ['2026-09', 'September 2026', 2],
      ['none', '', 1],
      ['2026-08', 'August 2026', 1],
      ['2026-09', 'September 2026', 1],
    ]);
    expect(monthGroups(rows, (r) => r, 'de', false)).toEqual([{ key: 'all', label: '', items: rows }]);
    expect(monthGroups([], (r) => r, 'de')).toEqual([]);
    expect(monthGroups(['2026-01-02'], (r) => r, 'en')[0].label).toBe('January 2026');
  });

  it('shows a short date and nothing for a missing or broken one', () => {
    expect(shortDate('2026-09-28', 'de')).toBe('28.09.');
    expect(shortDate('2026-09-28T10:00:00Z', 'en')).toBe('28/09');
    expect(shortDate(null, 'de')).toBe('');
    expect(shortDate('x', 'de')).toBe('');
  });

  it('knows the common VAT rates only', () => {
    expect(vatRate('2428.57', '461.43')).toBe(19);
    expect(vatRate('100', '7')).toBe(7);
    expect(vatRate('100', '0')).toBe(0);
    expect(vatRate('100', '12')).toBeNull();
    expect(vatRate(null, '19')).toBeNull();
    expect(vatRate('100', null)).toBeNull();
    expect(vatRate('0', '0')).toBeNull();
  });

  it('counts the calendar days to a date', () => {
    const today = new Date(2026, 9, 5, 23, 30);
    expect(daysUntil('2026-10-08', today)).toBe(3);
    expect(daysUntil('2026-10-05', today)).toBe(0);
    expect(daysUntil('2026-10-01', today)).toBe(-4);
    expect(typeof daysUntil('2026-10-01')).toBe('number');
  });
});
