import type { BudgetTreeNode } from './budget-tree.api';
import {
  ariaSortDir,
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
