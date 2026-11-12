import {
  addable,
  cents,
  currentVersion,
  inForce,
  memberIds,
  planRows,
  nextStep,
  sideSum,
  stepIndex,
  voteRuns,
  yearMembers,
} from './budget-plan.util';
import { TOP, line, node, version } from './budget-plan.fixtures';

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
    const decided = version({ state: 'in_progress', lines: [line('fees', '1', { name: 'Alt', pathKey: 'OLD-1', note: 'n' })] });
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

  it('§000806: places a version on its entry of the step display', () => {
    const steps = [
      { name: 'Beschluss', gremiumId: 'g1', passedAt: '2026-02-01T10:00:00Z' },
      { name: 'Genehmigung', gremiumId: null, passedAt: null },
    ];
    expect(stepIndex(version({ steps }))).toBe(0);
    expect(stepIndex(version({ steps, state: 'in_progress' }))).toBe(2);
    expect(stepIndex(version({ steps, state: 'in_force' }))).toBe(4);
    expect(stepIndex(version({ state: 'replaced' }))).toBe(2);
    expect(nextStep(version({ steps }))?.name).toBe('Genehmigung');
    expect(nextStep(version())).toBeNull();
  });

  it('§000826: a vote runs while it is a draft or open', () => {
    const step = { name: 'Beschluss', gremiumId: 'g1' };
    expect(voteRuns({ ...step, voteStatus: 'draft' })).toBe(true);
    expect(voteRuns({ ...step, voteStatus: 'open' })).toBe(true);
    expect(voteRuns({ ...step, voteStatus: 'closed' })).toBe(false);
    expect(voteRuns(step)).toBe(false);
  });

  it('shows in a year with a plan in force only its Kostenstellen and the used ones', () => {
    const used = { fiscalYearId: 'fy-1', allocated: '5', bound: '0', expended: '0', income: '1', committed: '0', requested: '0', available: '0' };
    const top = node({
      id: 't',
      children: [
        node({ id: 'in', children: [node({ id: 'in-out' }), node({ id: 'in-in' })] }),
        node({ id: 'used', byFiscalYear: [used] }),
        node({ id: 'other-year', byFiscalYear: [{ ...used, fiscalYearId: 'fy-0' }] }),
        node({ id: 'only-allocated', byFiscalYear: [{ ...used, income: '0' }] }),
      ],
    });
    const shown = yearMembers(top, new Set(['in', 'in-in']), 'fy-1');
    expect(shown.children.map((n) => n.id)).toEqual(['in', 'used']);
    expect(shown.children[0].children.map((n) => n.id)).toEqual(['in-in']);
  });
});
