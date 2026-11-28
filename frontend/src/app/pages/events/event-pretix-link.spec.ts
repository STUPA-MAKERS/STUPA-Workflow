import { of } from 'rxjs';
import type { SalesApiService } from '@core/api/sales.service';
import { NO_PRETIX, pretixOptions, pretixSteps, pretixValue } from './event-pretix-link';

const EVENTS = [
  { slug: 'a', name: 'A', dateFrom: '2026-12-11', taken: false },
  { slug: 'b', name: 'B', dateFrom: null, taken: true },
  { slug: 'c', name: 'C', dateFrom: null, taken: true },
];

function api() {
  return {
    link: jest.fn(() => of({})),
    unlink: jest.fn(() => of(undefined)),
    setIncomeBudget: jest.fn(() => of({})),
  };
}

const run = (a: ReturnType<typeof api>, before = NO_PRETIX, after = NO_PRETIX, mayBook = true) => {
  const done = jest.fn();
  pretixSteps(a as unknown as SalesApiService, 'e-1', before, after, mayBook).subscribe(done);
  expect(done).toHaveBeenCalledTimes(1);
};

describe('pretixOptions', () => {
  it('offers none, the free events and the own one, with the date', () => {
    expect(pretixOptions(EVENTS, 'b', 'Keine', (d) => `am ${d}`)).toEqual([
      { value: '', label: 'Keine' },
      { value: 'a', label: 'A · am 2026-12-11' },
      { value: 'b', label: 'B' },
    ]);
  });
});

describe('pretixValue', () => {
  it('names the two fields of the form', () => {
    expect(pretixValue({ slug: 'a', incomeBudgetId: 'b-1' })).toEqual({ pretixSlug: 'a', incomeBudgetId: 'b-1' });
  });
});

describe('pretixSteps', () => {
  it('does nothing without a change', () => {
    const a = api();
    run(a, { slug: 'a', incomeBudgetId: 'x' }, { slug: 'a', incomeBudgetId: 'x' });
    expect(a.link).not.toHaveBeenCalled();
    expect(a.setIncomeBudget).not.toHaveBeenCalled();
  });

  it('links a new event and sets its cost centre', () => {
    const a = api();
    run(a, NO_PRETIX, { slug: 'a', incomeBudgetId: 'b-1' });
    expect(a.link).toHaveBeenCalledWith('e-1', 'a');
    expect(a.setIncomeBudget).toHaveBeenCalledWith('e-1', 'b-1');
  });

  it('links without a cost centre and keeps it away without the right', () => {
    const a = api();
    run(a, { slug: 'a', incomeBudgetId: 'b-1' }, { slug: 'c', incomeBudgetId: '' });
    expect(a.link).toHaveBeenCalledWith('e-1', 'c');
    expect(a.setIncomeBudget).not.toHaveBeenCalled();
    const b = api();
    run(b, { slug: 'a', incomeBudgetId: '' }, { slug: 'a', incomeBudgetId: 'b-2' }, false);
    expect(b.setIncomeBudget).not.toHaveBeenCalled();
  });

  it('clears the cost centre and removes the link', () => {
    const a = api();
    run(a, { slug: 'a', incomeBudgetId: 'b-1' }, { slug: 'a', incomeBudgetId: '' });
    expect(a.setIncomeBudget).toHaveBeenCalledWith('e-1', null);
    const b = api();
    run(b, { slug: 'a', incomeBudgetId: 'b-1' }, NO_PRETIX);
    expect(b.unlink).toHaveBeenCalledWith('e-1');
    expect(b.setIncomeBudget).not.toHaveBeenCalled();
  });
});
