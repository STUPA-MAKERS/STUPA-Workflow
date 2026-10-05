import { type Observable, Subject, of, throwError } from 'rxjs';
import { render } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin/admin-api.service';
import { BudgetTreeComponent } from './budget-tree.component';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from './budget-tree.api';

/**
 * Regression test for the reload() fan-out. The fan-out calls listFiscalYears once
 * per top budget. A response of an earlier reload() or loadFiscalYears() must not
 * resolve after a newer one. Such a late response would overwrite fiscalYears and
 * selectedFyId with stale data. The component raises a reloadSeq and drops late
 * responses.
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

/** A FakeApi whose tree reads also stay open until the test resolves them. */
class DeferredTreeApi extends FakeApi {
  readonly treeCalls: Subject<BudgetTreeNode[]>[] = [];

  override tree(): Observable<BudgetTreeNode[]> {
    const s = new Subject<BudgetTreeNode[]>();
    this.treeCalls.push(s);
    return s;
  }
}

async function setup<A extends FakeApi = FakeApi>(api: A = new FakeApi() as A) {
  toastSpy.success.mockClear();
  toastSpy.error.mockClear();
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

    // The stale response resolves late. The component must ignore it and keep the state.
    stale.next([fy('fy-stale')]);
    expect(c.selectedFyId()).toBe('fy-fresh');
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-fresh']);
  });

  it('lets loadFiscalYears (selectTop) win over an in-flight reload fan-out', async () => {
    const { c, api } = await setup();
    const reloadFy = api.fyCalls[0];

    // User selects a top → loadFiscalYears() bumps reloadSeq with its own request.
    c.selectTop('b-vs');
    const selectFy = api.fyCalls[1];

    selectFy.next([fy('fy-selected')]);
    expect(c.selectedFyId()).toBe('fy-selected');

    // The earlier reload fan-out response arrives late. The component must drop it.
    reloadFy.next([fy('fy-old')]);
    expect(c.selectedFyId()).toBe('fy-selected');
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-selected']);
  });

  it('keeps a fiscal year that the user picked while the year list loads', async () => {
    const { c, api } = await setup();
    // Constructor reload() left one pending request for the years of b-vs.
    expect(api.fyCalls).toHaveLength(1);
    const pending = api.fyCalls[0];

    // The user picks a year of the segmented control before the list arrives.
    c.selectFy('fy-picked');
    expect(c.selectedFyId()).toBe('fy-picked');

    // The list holds the picked year, so the pick stays.
    pending.next([fy('fy-other'), fy('fy-picked')]);
    expect(c.selectedFyId()).toBe('fy-picked');
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-other', 'fy-picked']);
  });

  it('drops a stale tree answer and a stale tree error after a newer reload', async () => {
    const { c, api } = await setup(new DeferredTreeApi());
    const stale = api.treeCalls[0];
    c.reload();
    api.treeCalls[1].next(TREE);
    expect(c.selectedTopId()).toBe('b-vs');
    stale.error(new Error('late'));
    expect(c.loadError()).toBe(false);
    stale.next([]);
    expect(c.tree()).toEqual(TREE);
  });

  it('drops a stale fiscal-year error after a newer year list', async () => {
    const { c, api } = await setup();
    const stale = api.fyCalls[0];
    c.selectTop('b-vs');
    api.fyCalls[1].next([fy('fy-new')]);
    stale.error(new Error('late'));
    expect(c.fiscalYears().map((f: FiscalYear) => f.id)).toEqual(['fy-new']);
  });
});
