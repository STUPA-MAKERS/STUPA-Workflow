import type { BudgetTreeNode } from './budget-tree.api';
import {
  costCentreFigures,
  costCentreIndex,
  costCentreLabel,
  costCentreTrail,
  findBudgetNode,
  findTopBudgetNode,
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
  it('findTopBudgetNode returns the root containing the target id', () => {
    const tree = [node('top-1', [node('child-1')]), node('top-2')];
    expect(findTopBudgetNode(tree, 'child-1')?.id).toBe('top-1');
    expect(findTopBudgetNode(tree, 'top-2')?.id).toBe('top-2');
    expect(findTopBudgetNode(tree, 'ghost')).toBeNull();
  });
});

describe('cost-centre labels', () => {
  /** The child inherits the colour of its parent, in a shade of it. */
  it('indexes every node with its name, path and display colour', () => {
    const child = { ...node('c'), name: 'Kultur', pathKey: 'VS-120' };
    const root = { ...node('r', [child]), color: '#2f7fc1' };
    const index = costCentreIndex([root]);
    expect(index.get('r')).toEqual({ name: 'r', path: 'r', color: '#2f7fc1' });
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

describe('finance helpers', () => {
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
    expect(signedEur('expense', '12.5', 'de-DE').replace(/\s/g, ' ')).toBe('−12,50 €');
    expect(signedEur('income', '12.5', 'en-GB')).toMatch(/^\+€12\.50$/);
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

  it('knows the common VAT rates only', () => {
    expect(vatRate('2428.57', '461.43')).toBe(19);
    expect(vatRate('100', '7')).toBe(7);
    expect(vatRate('100', '0')).toBe(0);
    expect(vatRate('100', '12')).toBeNull();
    expect(vatRate(null, '19')).toBeNull();
    expect(vatRate('100', null)).toBeNull();
    expect(vatRate('0', '0')).toBeNull();
  });
});
