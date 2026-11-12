import { node, TOP } from '../plan/budget-plan.fixtures';
import { activeOnly, costCentreError, findNode, hasSide, parentOptions, withDescendants } from './cost-centre.util';

describe('cost-centre.util', () => {
  it('names the message of a problem code, else the fallback', () => {
    expect(costCentreError('budget_key_exists')).toBe('budget.cc.error.keyExists');
    expect(costCentreError('other')).toBe('budget.cc.error.failed');
    expect(costCentreError('other', 'budget.cc.error.allocation')).toBe('budget.cc.error.allocation');
  });

  it('gives a side only to a direct child of a budget with a Haushaltsplan', () => {
    expect(hasSide({ parentId: 'vsm' }, TOP)).toBe(true);
    expect(hasSide({ parentId: 'staff' }, TOP)).toBe(false);
    expect(hasSide({ parentId: 'vsm' }, { ...TOP, planEnabled: false })).toBe(false);
    expect(hasSide({ parentId: 'vsm' }, null)).toBe(false);
  });

  it('lists the budget first among the parents, then each Kostenstelle with its path', () => {
    expect(parentOptions(TOP, [{ id: 'wages', name: 'Löhne', pathKey: 'STAFF-WAGES' }], 'Budget')).toEqual([
      { value: 'vsm', label: 'VS-Mittel (Budget)' },
      { value: 'wages', label: 'Löhne (STAFF-WAGES)' },
    ]);
  });

  it('walks a node and the nodes below it in tree order', () => {
    expect(withDescendants(TOP).map((n) => n.id)).toEqual(['vsm', 'fees', 'other', 'staff', 'wages', 'fees2', 'grants', 'noside']);
  });

  it('finds a node in a forest by its id', () => {
    expect(findNode([TOP], 'wages')?.name).toBe('Löhne');
    expect(findNode([TOP], 'nope')).toBeNull();
  });

  it('drops an inactive node together with the nodes below it', () => {
    const forest = [
      node({ id: 'a', children: [node({ id: 'a1', active: false, children: [node({ id: 'a11' })] }), node({ id: 'a2' })] }),
      node({ id: 'b', active: false }),
    ];
    expect(activeOnly(forest).flatMap(withDescendants).map((n) => n.id)).toEqual(['a', 'a2']);
  });
});
