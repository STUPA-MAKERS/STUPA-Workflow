import { TestBed } from '@angular/core/testing';
import { type Observable, Subject, of, throwError } from 'rxjs';
import { render } from '@testing-library/angular';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminApiService } from '../admin/admin-api.service';
import { BudgetTreeComponent } from './budget-tree.component';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from './budget-tree.api';

/**
 * AUD-039 regression: the reload() fan-out (one listFiscalYears per top-budget)
 * must not let an in-flight response from a previous reload/loadFiscalYears
 * resolve after a newer one and overwrite fiscalYears/selectedFyId with stale
 * data. The component bumps a reloadSeq and drops late responses.
 */

function fullNode(over: Partial<BudgetTreeNode>): BudgetTreeNode {
  return {
    id: 'x',
    parentId: null,
    gremiumId: 'g-1',
    key: 'K',
    pathKey: 'K',
    name: 'N',
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
    children: [],
    ...over,
  };
}

const TREE: BudgetTreeNode[] = [fullNode({ id: 'b-vs', key: 'VS', pathKey: 'VS', name: 'VS-Mittel' })];

function fy(id: string): FiscalYear {
  return {
    id,
    budgetId: 'b-vs',
    year: 2026,
    display: id,
    startDate: '2026-01-01',
    endDate: '2026-12-31',
    active: true,
  };
}

const adminMock = {
  listGremienOptions: () => of([{ id: 'g-1', name: 'StuPa' }]),
  getGlobalFlow: () => of(null),
};

const toastSpy = { success: jest.fn(), error: jest.fn() };

/** Mocked BudgetTreeApi whose listFiscalYears returns caller-controllable Subjects. */
class FakeApi {
  /** Queue of pending fiscal-year streams, in call order. */
  readonly fyCalls: Subject<FiscalYear[]>[] = [];

  tree(): Observable<BudgetTreeNode[]> {
    return of(TREE);
  }

  listFiscalYears(): Observable<FiscalYear[]> {
    const s = new Subject<FiscalYear[]>();
    this.fyCalls.push(s);
    return s;
  }

  // Unused by these tests but part of the surface the component may touch.
  updateNode = () => throwError(() => new Error('unused'));
}

async function setup() {
  toastSpy.success.mockClear();
  toastSpy.error.mockClear();
  const api = new FakeApi();
  const view = await render(BudgetTreeComponent, {
    providers: [
      { provide: BudgetTreeApi, useValue: api },
      { provide: AdminApiService, useValue: adminMock },
      { provide: ToastService, useValue: toastSpy },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { c, api };
}

describe('BudgetTreeComponent reload race guard (AUD-039)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('drops a stale reload fan-out response that resolves after a newer reload', async () => {
    const { c, api } = await setup();
    // Constructor already ran reload() → one pending listFiscalYears for b-vs.
    expect(api.fyCalls).toHaveLength(1);
    const stale = api.fyCalls[0];

    // A second reload() fires before the first fan-out resolves (bumps reloadSeq).
    c.reload();
    expect(api.fyCalls).toHaveLength(2);
    const fresh = api.fyCalls[1];

    // The newer response lands first and sets the selection.
    fresh.next([fy('fy-fresh')]);
    expect(c.selectedFyId()).toBe('fy-fresh');
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-fresh']);

    // The stale response resolves late — it must be ignored, not clobber state.
    stale.next([fy('fy-stale')]);
    expect(c.selectedFyId()).toBe('fy-fresh');
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-fresh']);
    expect(c.fiscalYearsByBudget()['b-vs']?.map((f: FiscalYear) => f.id)).toEqual(['fy-fresh']);
  });

  it('lets loadFiscalYears (selectTop) win over an in-flight reload fan-out', async () => {
    const { c, api } = await setup();
    const reloadFy = api.fyCalls[0];

    // User selects a top → loadFiscalYears() bumps reloadSeq with its own request.
    c.selectTop('b-vs');
    const selectFy = api.fyCalls[1];

    selectFy.next([fy('fy-selected')]);
    expect(c.selectedFyId()).toBe('fy-selected');

    // The earlier reload fan-out response arrives late and must be discarded.
    reloadFy.next([fy('fy-old')]);
    expect(c.selectedFyId()).toBe('fy-selected');
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-selected']);
  });

  it('lets onYearPicked (left-tree year click) win over an in-flight reload fan-out', async () => {
    const { c, api } = await setup();
    // Constructor reload() left one pending fan-out request for b-vs.
    expect(api.fyCalls).toHaveLength(1);
    const reloadFy = api.fyCalls[0];

    // The left tree already knows the budget's HHJ → user clicks a year there.
    // onYearPicked() sets the selection synchronously AND bumps reloadSeq so the
    // in-flight reload fan-out below can no longer clobber it.
    c.fiscalYearsByBudget.set({ 'b-vs': [fy('fy-picked')] });
    c.onYearPicked({ budgetId: 'b-vs', fiscalYearId: 'fy-picked' });
    expect(c.selectedTopId()).toBe('b-vs');
    expect(c.selectedFyId()).toBe('fy-picked');
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-picked']);

    // The stale reload fan-out resolves afterward (top.id === sel.budgetId) and
    // must NOT overwrite the user's pick.
    reloadFy.next([fy('fy-stale')]);
    expect(c.selectedFyId()).toBe('fy-picked');
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-picked']);
  });
});
