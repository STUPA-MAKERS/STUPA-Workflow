import { Component, signal } from '@angular/core';
import { render } from '@testing-library/angular';
import { of, throwError } from 'rxjs';

import { BudgetTreeApi, type BudgetYear } from '../budget-tree.api';
import { BudgetYearSelectComponent } from './budget-year-select.component';
import { budgetYearLabel, defaultBudgetYear } from './budget-year-select.util';

const PAIR = (budgetId: string, fiscalYearId: string, current: boolean): BudgetYear => ({
  budgetId,
  budgetName: budgetId === 'vsm' ? 'VS-Mittel' : 'QSM',
  fiscalYearId,
  display: fiscalYearId.endsWith('27') ? '2027/28' : '2026/27',
  current,
});

const PAIRS = [
  PAIR('vsm', 'vsm-26', true),
  PAIR('vsm', 'vsm-27', false),
  PAIR('qsm', 'qsm-27', false),
];

@Component({
  standalone: true,
  imports: [BudgetYearSelectComponent],
  template: `<app-budget-year-select
    [fiscalYearId]="year()"
    [preferBudgetId]="prefer()"
    (picked)="onPair($event)"
  />`,
})
class HostComponent {
  readonly year = signal('');
  readonly prefer = signal('');
  readonly got: BudgetYear[] = [];
  onPair(pair: BudgetYear): void {
    this.got.push(pair);
    this.year.set(pair.fiscalYearId);
  }
}

async function setup(pairs: BudgetYear[] | 'error', init: Partial<{ year: string; prefer: string }> = {}) {
  const api = {
    listBudgetYears: () => (pairs === 'error' ? throwError(() => new Error('x')) : of(pairs)),
  };
  const view = await render(HostComponent, {
    providers: [{ provide: BudgetTreeApi, useValue: api }],
  });
  const host = view.fixture.componentInstance;
  host.year.set(init.year ?? '');
  host.prefer.set(init.prefer ?? '');
  view.fixture.detectChanges();
  const inner = view.fixture.debugElement.children[0].componentInstance as unknown as {
    pick: (id: string) => void;
    options: () => { value: string; label: string }[];
  };
  return { host, inner, view };
}

describe('BudgetYearSelectComponent', () => {
  beforeEach(() => localStorage.clear());

  it('starts with the current year and tells the form the pair', async () => {
    const { host, inner } = await setup(PAIRS);
    expect(inner.options().map((o) => o.label)).toEqual([
      'VS-Mittel 2026/27',
      'VS-Mittel 2027/28',
      'QSM 2027/28',
    ]);
    expect(host.got.map((p) => p.fiscalYearId)).toEqual(['vsm-26']);
  });

  it('keeps the year of the form and remembers the budget of a choice', async () => {
    const { host, inner } = await setup(PAIRS);
    inner.pick('qsm-27');
    inner.pick('gone');
    expect(host.got.map((p) => p.fiscalYearId)).toEqual(['vsm-26', 'qsm-27']);
    expect(localStorage.getItem('ap.budgetYear.lastBudget')).toBe('qsm');
  });

  it('works without the storage of the browser', async () => {
    const get = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const set = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const { host, inner } = await setup(PAIRS);
    inner.pick('vsm-27');
    expect(host.got.map((p) => p.fiscalYearId)).toEqual(['vsm-26', 'vsm-27']);
    get.mockRestore();
    set.mockRestore();
  });

  it('tells nothing when no pair can be chosen', async () => {
    expect((await setup([])).host.got).toEqual([]);
    expect((await setup('error')).host.got).toEqual([]);
  });
});

describe('defaultBudgetYear', () => {
  it('takes the preferred budget, then the last one, then the first current year', () => {
    expect(defaultBudgetYear(PAIRS, 'qsm', 'vsm')?.fiscalYearId).toBe('qsm-27');
    expect(defaultBudgetYear(PAIRS, '', 'qsm')?.fiscalYearId).toBe('qsm-27');
    expect(defaultBudgetYear(PAIRS, '', '')?.fiscalYearId).toBe('vsm-26');
    expect(defaultBudgetYear(PAIRS.slice(1), '', '')?.fiscalYearId).toBe('vsm-27');
    expect(defaultBudgetYear([], '', '')).toBeNull();
    expect(budgetYearLabel(PAIRS[0])).toBe('VS-Mittel 2026/27');
  });
});
