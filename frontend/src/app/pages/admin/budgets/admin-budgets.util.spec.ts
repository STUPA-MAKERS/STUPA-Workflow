import { clampCutoff, cutoffLabel, fyBlockerKey, movedStep, stepsToSave } from './admin-budgets.util';

describe('admin-budgets.util', () => {
  it('keeps a part of the start of the fiscal year in its range', () => {
    expect(clampCutoff('day', '31')).toBe(28);
    expect(clampCutoff('day', '0')).toBe(1);
    expect(clampCutoff('day', 'x')).toBe(1);
    expect(clampCutoff('day', 14.7)).toBe(14);
    expect(clampCutoff('month', '13')).toBe(12);
    expect(clampCutoff('month', '-2')).toBe(1);
  });

  it('writes the start of the fiscal year as day and month', () => {
    expect(cutoffLabel({ fiscalStartDay: 1, fiscalStartMonth: 3 })).toBe('01.03.');
    expect(cutoffLabel({ fiscalStartDay: 15, fiscalStartMonth: 10 })).toBe('15.10.');
  });

  it('moves a step one place and leaves the ends alone', () => {
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

  it('sends trimmed names and null for no Gremium', () => {
    expect(stepsToSave([{ name: ' Beschluss ', gremiumId: 'g' }, { name: 'Genehmigung', gremiumId: '' }])).toEqual([
      { name: 'Beschluss', gremiumId: 'g' },
      { name: 'Genehmigung', gremiumId: null },
    ]);
  });

  it('names the reason why a fiscal year cannot be deleted', () => {
    expect(fyBlockerKey('has bookings')).toBe('budget.tree.fyBlocked.bookings');
    expect(fyBlockerKey('has allocations')).toBe('budget.tree.fyBlocked.allocations');
    expect(fyBlockerKey('has applications')).toBe('budget.tree.fyBlocked.applications');
    expect(fyBlockerKey(undefined)).toBe('budget.tree.fyBlocked.generic');
  });
});
