import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { BudgetTreeApi } from '../../pages/budget/budget-tree.api';
import { PrefetchService } from './prefetch.service';

describe('PrefetchService', () => {
  function setup(opts: { authed?: boolean; perms?: string[]; scoped?: boolean; roots?: unknown[] } = {}) {
    const authed = signal(opts.authed ?? true);
    const perms = new Set(opts.perms ?? ['budget.view']);
    const tree = jest.fn(() => of(opts.roots ?? []));
    const cachedFiscalYears = jest.fn(() => of([]));
    TestBed.configureTestingModule({
      providers: [
        {
          provide: AuthService,
          useValue: {
            isAuthenticated: authed,
            canAny: (...p: string[]) => p.some((x) => perms.has(x)),
            hasScopedBudgetView: () => opts.scoped ?? false,
          },
        },
        { provide: BudgetTreeApi, useValue: { tree, cachedFiscalYears } },
      ],
    });
    return { authed, tree, cachedFiscalYears };
  }

  it('warms the cost-centre tree once the caller is signed in', () => {
    const { tree } = setup();
    TestBed.inject(PrefetchService);
    TestBed.tick();
    expect(tree).toHaveBeenCalledTimes(1);
  });

  /** The budget page shows no amount before these years are in. */
  it('warms the fiscal years of every root the budget page shows', () => {
    const { cachedFiscalYears } = setup({
      roots: [
        { id: 'a', active: true },
        { id: 'b', active: false },
        { id: 'c', active: true },
      ],
    });
    TestBed.inject(PrefetchService);
    TestBed.tick();
    expect(cachedFiscalYears.mock.calls).toEqual([['a'], ['c']]);
  });

  it('stays silent when a fiscal-year prefetch fails', () => {
    const { cachedFiscalYears } = setup({ roots: [{ id: 'a', active: true }] });
    cachedFiscalYears.mockReturnValue(throwError(() => new Error('down')));
    expect(() => {
      TestBed.inject(PrefetchService);
      TestBed.tick();
    }).not.toThrow();
    expect(cachedFiscalYears).toHaveBeenCalledTimes(1);
  });

  it('waits until there is a caller at all', () => {
    const { authed, tree } = setup({ authed: false });
    TestBed.inject(PrefetchService);
    TestBed.tick();
    expect(tree).not.toHaveBeenCalled();

    authed.set(true);
    TestBed.tick();
    expect(tree).toHaveBeenCalledTimes(1);
  });

  /** A prefetch for them would only get a 403. */
  it('spends no request on someone who may not see the budget', () => {
    const { tree } = setup({ perms: [] });
    TestBed.inject(PrefetchService);
    TestBed.tick();
    expect(tree).not.toHaveBeenCalled();
  });

  it('does warm it for a scoped budget viewer, who has a tree of their own', () => {
    const { tree } = setup({ perms: [], scoped: true });
    TestBed.inject(PrefetchService);
    TestBed.tick();
    expect(tree).toHaveBeenCalledTimes(1);
  });

  /**
   * The effect runs again whenever anything it reads changes. Without the guard, a token refresh
   * refetches the whole tree for no reason.
   */
  it('runs once, not on every signal change', () => {
    const { authed, tree } = setup();
    TestBed.inject(PrefetchService);
    TestBed.tick();
    authed.set(false);
    TestBed.tick();
    authed.set(true);
    TestBed.tick();
    expect(tree).toHaveBeenCalledTimes(1);
  });

  /**
   * Nothing waits on it, and the page that really needs the tree asks again and reports its own
   * error.
   */
  it('stays silent when the prefetch fails', () => {
    const tree = jest.fn(() => throwError(() => new Error('down')));
    TestBed.configureTestingModule({
      providers: [
        {
          provide: AuthService,
          useValue: {
            isAuthenticated: signal(true),
            canAny: () => true,
            hasScopedBudgetView: () => false,
          },
        },
        { provide: BudgetTreeApi, useValue: { tree } },
      ],
    });
    expect(() => {
      TestBed.inject(PrefetchService);
      TestBed.tick();
    }).not.toThrow();
  });
});
