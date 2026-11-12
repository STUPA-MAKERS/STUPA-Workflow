import {
  addable,
  cents,
  currentVersion,
  inForce,
  memberIds,
  planRows,
  sideSum,
  stepIndex,
} from './budget-plan.util';
import { TOP, line, version } from './budget-plan.fixtures';

describe('budget plan rules', () => {
  const source = { top: TOP, version: version(), base: null, prev: null, prevFiscalYearId: null };

  it('§000818: builds a row for each Kostenstelle with a line, in tree order', () => {
    const rows = planRows(source);
    expect(rows.map((r) => [r.id, r.depth, r.parentId, r.hasChildren])).toEqual([
      ['fees', 0, null, false],
      ['staff', 0, null, true],
      ['wages', 1, 'staff', false],
      ['grants', 0, null, false],
    ]);
    expect(rows[0]).toMatchObject({ name: 'Beiträge', side: 'income', amount: 100, base: null, prev: null, actual: null });
  });

  it('§000821: shows the name and the key that a decided line keeps', () => {
    const decided = version({ state: 'resolved', lines: [line('fees', '1', { name: 'Alt', pathKey: 'OLD-1', note: 'n' })] });
    expect(planRows({ ...source, version: decided })[0]).toMatchObject({ name: 'Alt', pathKey: 'OLD-1', note: 'n' });
  });

  it('adds the version in force, the year before and the marks', () => {
    const rows = planRows({
      top: TOP,
      version: version({ lines: [line('fees', '100', { transferable: true, coverable: true, blocked: '5' }), line('wages', '1'), line('staff', '70'), line('grants', '30')] }),
      base: version({ lines: [line('fees', '80')] }),
      prev: version({ lines: [line('fees', '95')] }),
      prevFiscalYearId: 'fy-25',
    });
    expect(rows[0]).toMatchObject({ base: 80, prev: 95, actual: 90, transferable: true, coverable: true, blocked: 5 });
    expect(rows[2]).toMatchObject({ id: 'wages', actual: 55, base: null, prev: null });
    expect(rows[3]).toMatchObject({ id: 'grants', actual: 0 });
  });

  it('§000807: sums one side over the direct children of the top level', () => {
    const rows = planRows(source);
    expect(sideSum(rows, 'income')).toBe(100);
    expect(sideSum(rows, 'expense')).toBe(100);
    expect(cents(0.1 + 0.2)).toBe(30);
  });

  it('§000819: offers a Kostenstelle without a line whose parent is in the plan', () => {
    expect(addable(TOP, version()).map((n) => n.id)).toEqual(['other', 'fees2']);
    expect(addable(TOP, version({ lines: [] })).map((n) => n.id)).toEqual(['fees', 'other', 'staff', 'grants']);
  });

  it('finds the version in force and the version to work on', () => {
    const stamm = version({ state: 'in_force' });
    const nachtrag = version({ id: 'v1', number: 1 });
    const old = version({ id: 'old', state: 'replaced' });
    expect(inForce([stamm, nachtrag])).toBe(stamm);
    expect(inForce([nachtrag])).toBeNull();
    expect(currentVersion([stamm, nachtrag])).toBe(nachtrag);
    expect(currentVersion([old, stamm])).toBe(stamm);
    expect(currentVersion([old])).toBe(old);
    expect(currentVersion([])).toBeNull();
    expect([...(memberIds(stamm) ?? [])]).toEqual(['fees', 'staff', 'wages', 'grants']);
    expect(memberIds(null)).toBeNull();
  });

  it('§000806: places a version on its step', () => {
    expect((['draft', 'resolved', 'approved', 'in_force', 'replaced'] as const).map(stepIndex)).toEqual([0, 1, 2, 4, 4]);
  });
});
