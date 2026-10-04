import type { BudgetTreeNode } from './budget-tree.api';
import {
  ariaSortDir,
  BOOKINGS_COLUMNS_FULL_MEDIA,
  columnSet,
  COLUMNS_FULL_MEDIA,
  costCentreIndex,
  costCentreLabel,
  findTopBudgetNode,
  formatEur,
  problemCode,
  problemDetail,
  sortIndicator,
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

  it('sortIndicator / ariaSortDir describe the active column only', () => {
    expect(sortIndicator(false, 'desc')).toBe('');
    expect(sortIndicator(true, 'desc')).toBe(' ↓');
    expect(sortIndicator(true, 'asc')).toBe(' ↑');
    expect(ariaSortDir(false, 'asc')).toBe('none');
    expect(ariaSortDir(true, 'asc')).toBe('ascending');
    expect(ariaSortDir(true, 'desc')).toBe('descending');
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

describe('columnSet', () => {
  it('shows every column on a phone (cards) and on a wide viewport', () => {
    expect(columnSet({ phone: true, full: false, tight: true })).toBe('full');
    expect(columnSet({ phone: false, full: true, tight: false })).toBe('full');
  });
  it('drops columns below the full width and more below 1000px', () => {
    expect(columnSet({ phone: false, full: false, tight: false })).toBe('compact');
    expect(columnSet({ phone: false, full: false, tight: true })).toBe('tight');
  });
  it('gives the bookings table a higher full width than the invoices table', () => {
    expect(COLUMNS_FULL_MEDIA).toBe('(min-width: 1400px)');
    expect(BOOKINGS_COLUMNS_FULL_MEDIA).toBe('(min-width: 1536px)');
  });
});
