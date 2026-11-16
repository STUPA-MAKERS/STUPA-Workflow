import { cutoffLabel, cutoffProblem, cutoffValue, fyBlockerKey, movedStep, nextYear, stepsToSave, yearProblem } from './admin-budgets.util';

describe('AdminBudgetsUtil', () => {
  it('reads a part of the start of the fiscal year as a whole number and names a value out of its range', () => {
    expect(['31', 'x', '', 14.7].map(cutoffValue)).toEqual([31, 0, 0, 14]);
    expect([0, 1, 28, 29].map((v) => cutoffProblem('day', v))).toEqual([true, false, false, true]);
    expect([-2, 1, 12, 13].map((v) => cutoffProblem('month', v))).toEqual([true, false, false, true]);
  });

  it('writes the start of the fiscal year as day and month', () => {
    expect(cutoffLabel({ fiscalStartDay: 1, fiscalStartMonth: 3 })).toBe('01.03.');
    expect(cutoffLabel({ fiscalStartDay: 15, fiscalStartMonth: 10 })).toBe('15.10.');
  });

  it('§F/finance/budget/000827: moves a step one place and leaves the ends alone', () => {
    const steps = [
      { name: 'a', gremiumId: '' },
      { name: 'b', gremiumId: 'g' },
      { name: 'c', gremiumId: '' },
    ];
    expect(movedStep(steps, 0, 1).map((s) => s.name)).toEqual(['b', 'a', 'c']);
    expect(movedStep(steps, 2, -1).map((s) => s.name)).toEqual(['a', 'c', 'b']);
    expect(movedStep(steps, 0, -1)).toBe(steps);
    expect(movedStep(steps, 2, 1)).toBe(steps);
  });

  it('§F/finance/budget/000827: sends trimmed names and null for no Gremium', () => {
    expect(stepsToSave([{ name: ' Beschluss ', gremiumId: 'g' }, { name: 'Genehmigung', gremiumId: '' }])).toEqual([
      { name: 'Beschluss', gremiumId: 'g' },
      { name: 'Genehmigung', gremiumId: null },
    ]);
  });

  it('§F/finance/budget/000836: names the reason of a refused fiscal-year write by its code, else the fallback', () => {
    const fallback = 'budget.tree.fyBlocked.generic';
    expect(fyBlockerKey('fiscal_year_has_bookings', fallback)).toBe('budget.tree.fyBlocked.bookings');
    expect(fyBlockerKey('fiscal_year_has_allocations', fallback)).toBe('budget.tree.fyBlocked.allocations');
    expect(fyBlockerKey('fiscal_year_has_applications', fallback)).toBe('budget.tree.fyBlocked.applications');
    expect(fyBlockerKey('fiscal_year_has_plan', fallback)).toBe('budget.tree.fyBlocked.plan');
    expect(fyBlockerKey('fiscal_year_closed', fallback)).toBe('budget.fy.closedError');
    expect(fyBlockerKey('plan_in_progress', fallback)).toBe('budget.plan.error.inProgress');
    expect(fyBlockerKey('', fallback)).toBe(fallback);
  });

  it('a year is a whole number from 1900 to 2200', () => {
    expect(['1900', '2026', '2200'].map(yearProblem)).toEqual([false, false, false]);
    expect(['', ' ', 'x', '2026.5', '1899', '2201'].map(yearProblem)).toEqual([true, true, true, true, true, true]);
  });

  it('a new fiscal year starts after the newest one, else with this year', () => {
    expect(nextYear([{ year: 2024 }, { year: 2026 }, { year: 2025 }], 2030)).toBe(2027);
    expect(nextYear([], 2030)).toBe(2030);
  });
});
