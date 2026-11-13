import { node, TOP } from '../plan/budget-plan.fixtures';
import { NAME_MAX, activeOnly, costCentreError, findNode, hasSide, keyProblem, pickable, usedIn, withDescendants } from './cost-centre.util';

describe('CostCentreUtil', () => {
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

  it('§F/finance/budget/000246: a key holds only letters and digits and at most 64 characters', () => {
    expect(keyProblem('')).toBe(false);
    expect(keyProblem('A1b')).toBe(false);
    expect(keyProblem('A-1')).toBe(true);
    expect(keyProblem('ä')).toBe(true);
    expect(keyProblem('a'.repeat(64))).toBe(false);
    expect(keyProblem('a'.repeat(65))).toBe(true);
    expect(NAME_MAX).toBe(200);
  });

  it('a Kostenstelle is used in a year with a booking or an Antrag', () => {
    const figures = { fiscalYearId: 'fy', allocated: '5', bound: '0', expended: '0', income: '0', committed: '0', requested: '0', available: '0' };
    expect(usedIn(node({ id: 'a' }), 'fy')).toBe(false);
    expect(usedIn(node({ id: 'a', byFiscalYear: [figures] }), 'fy')).toBe(false);
    expect(usedIn(node({ id: 'a', byFiscalYear: [{ ...figures, requested: '1' }] }), 'fy')).toBe(true);
    expect(usedIn(node({ id: 'a', byFiscalYear: [{ ...figures, bound: '1' }] }), 'other')).toBe(false);
  });

  it('§F/finance/budget/000822 §F/finance/budget/000834: a picker offers no inactive Kostenstelle and, in a planned year, only those of the plan or in use', () => {
    const figures = { fiscalYearId: 'fy', allocated: '0', bound: '0', expended: '2', income: '0', committed: '0', requested: '0', available: '0' };
    const planned = node({
      id: 'p',
      plannedIn: ['fy'],
      children: [
        node({ id: 'in', plannedIn: ['fy'], children: [node({ id: 'in-out' }), node({ id: 'in-in', plannedIn: ['fy'] })] }),
        node({ id: 'out' }),
        node({ id: 'used', byFiscalYear: [figures] }),
        node({ id: 'off', plannedIn: ['fy'], active: false }),
      ],
    });
    const free = node({ id: 'f', children: [node({ id: 'f1' }), node({ id: 'f2', active: false })] });
    const ids = (forest: readonly ReturnType<typeof node>[]) => forest.flatMap(withDescendants).map((n) => n.id);
    expect(ids(pickable([planned, free], () => ['fy']))).toEqual(['p', 'in', 'in-in', 'used', 'f', 'f1']);
    expect(ids(pickable([planned], () => ['', 'other']))).toEqual(['p', 'in', 'in-out', 'in-in', 'out', 'used']);
    expect(ids(pickable([planned], () => []))).toEqual(['p', 'in', 'in-out', 'in-in', 'out', 'used']);
    expect(ids(pickable([planned], () => ['other', 'fy']))).toEqual(['p', 'in', 'in-in', 'used']);
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
