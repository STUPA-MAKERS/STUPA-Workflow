import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin/admin-api.service';
import { BudgetTreeComponent } from './budget-tree.component';
import type { BudgetTreeNode, FiscalYear } from './budget-tree.api';

const FY: FiscalYear = {
  id: 'fy-1',
  budgetId: 'b-vs',
  year: 2026,
  display: '2026',
  startDate: '2026-01-01',
  endDate: '2026-12-31',
  active: true,
};

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

const TREE: BudgetTreeNode[] = [
  fullNode({
    id: 'b-vs',
    key: 'VS',
    pathKey: 'VS',
    name: 'VS-Mittel',
    acceptedStateKeys: ['accepted'],
    deniedStateKeys: ['denied'],
    byFiscalYear: [
      {
        fiscalYearId: 'fy-1',
        allocated: '1000',
        bound: '200',
        expended: '50',
        income: '0',
        committed: '250',
        requested: '40',
        available: '750',
      },
    ],
    children: [
      fullNode({
        id: 'b-800',
        parentId: 'b-vs',
        key: '800',
        pathKey: 'VS-800',
        name: 'Dezentrale Einrichtungen',
        byFiscalYear: [
          {
            fiscalYearId: 'fy-1',
            allocated: '400',
            bound: '80',
            expended: '20',
            income: '0',
            committed: '100',
            requested: '10',
            available: '300',
          },
        ],
      }),
    ],
  }),
];

interface Mocks {
  gremien?: 'ok' | 'error';
  flow?: 'states' | 'null' | 'error';
}

function makeAdminMock(m: Mocks) {
  return {
    listGremienOptions: () =>
      m.gremien === 'error'
        ? throwError(() => new Error('boom'))
        : of([{ id: 'g-1', name: 'StuPa' }]),
    getGlobalFlow: () => {
      if (m.flow === 'error') return throwError(() => new Error('boom'));
      if (m.flow === 'null') return of(null);
      return of({
        states: [
          { key: 'accepted', label: { de: 'Angenommen', en: 'Accepted' } },
          { key: 'orphan', label: {} }, // label['de'] missing → falls back to key
        ],
      });
    },
  };
}

const toastSpy = {
  success: jest.fn(),
  error: jest.fn(),
};

async function setup(m: Mocks = { gremien: 'ok', flow: 'null' }) {
  toastSpy.success.mockClear();
  toastSpy.error.mockClear();
  const view = await render(BudgetTreeComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: AdminApiService, useValue: makeAdminMock(m) },
      { provide: ToastService, useValue: toastSpy },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  // Initial reload(): tree GET + per-top fiscal-years GET (single top b-vs).
  http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(TREE);
  http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
  view.fixture.detectChanges();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, http, c, toast: toastSpy };
}

/** Flush a reload() cycle (tree GET + per-top fiscal-years GET). */
function flushReload(http: HttpTestingController, tree: BudgetTreeNode[] = TREE): void {
  http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(tree);
  for (const top of tree.filter((n) => n.parentId === null)) {
    http.expectOne((r) => r.url.endsWith(`/budgets/${top.id}/fiscal-years`)).flush([FY]);
  }
}

describe('BudgetTreeComponent (#9)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  // ---------------------------------------------------------------- rendering
  it('renders the cost-centre tree with full path keys', async () => {
    await setup();
    expect(screen.getByText('VS')).toBeInTheDocument();
    expect(screen.getByText('VS-800')).toBeInTheDocument();
    expect(screen.getByText('Dezentrale Einrichtungen')).toBeInTheDocument();
  });

  it('flattens nested children into rows (pre-order) with depth', async () => {
    const { c } = await setup();
    expect(c.rows().map((r: { node: { pathKey: string } }) => r.node.pathKey)).toEqual([
      'VS',
      'VS-800',
    ]);
    expect(c.rows()[1].depth).toBe(1);
  });

  it('rows() is empty when no top is selected', async () => {
    const { c } = await setup();
    c.selectedTopId.set('nope');
    expect(c.selectedTop()).toBeNull();
    expect(c.rows()).toEqual([]);
    expect(c.selectedTopLabel()).toBe('');
  });

  it('selectedTopLabel renders "key – name" for the selected top', async () => {
    const { c } = await setup();
    expect(c.selectedTopLabel()).toBe('VS – VS-Mittel');
  });

  it('exposes the columns and identity helpers', async () => {
    const { c } = await setup();
    expect(c.columns().map((col: { key: string }) => col.key)).toEqual([
      'node',
      'allocated',
      'committed',
      'available',
      'color',
      'actions',
    ]);
    const row = { node: TREE[0], depth: 0 };
    expect(c.rowId(row)).toBe('b-vs');
    expect(c.childExpanded(row)).toBe(false);
    c.addingChildOf.set('b-vs');
    expect(c.childExpanded(row)).toBe(true);
  });

  // ---------------------------------------------------------- constructor side
  it('maps gremien into options on construction', async () => {
    const { c } = await setup({ gremien: 'ok', flow: 'null' });
    expect(c.gremiumOptions()).toEqual([{ value: 'g-1', label: 'StuPa' }]);
  });

  it('clears gremium options when the gremien request fails', async () => {
    const { c } = await setup({ gremien: 'error', flow: 'null' });
    expect(c.gremiumOptions()).toEqual([]);
  });

  it('builds state options from the global flow (de label, key fallback)', async () => {
    const { c } = await setup({ gremien: 'ok', flow: 'states' });
    expect(c.stateOptions()).toEqual([
      { value: 'accepted', label: 'Angenommen (accepted)' },
      { value: 'orphan', label: 'orphan (orphan)' },
    ]);
  });

  it('falls back to an empty state list when the flow request fails', async () => {
    const { c } = await setup({ gremien: 'ok', flow: 'error' });
    expect(c.stateOptions()).toEqual([]);
  });

  // ---------------------------------------------------------------- reload()
  it('keeps the selection across reloads when the top still exists', async () => {
    const { c, http } = await setup();
    c.selectedTopId.set('b-vs');
    c['reload']();
    flushReload(http);
    expect(c.selectedTopId()).toBe('b-vs');
    expect(c.fiscalYears()).toEqual([FY]);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('resets fiscal years to empty when no tops exist after reload', async () => {
    const { c, http } = await setup();
    c['reload']();
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush([]);
    expect(c.selectedTopId()).toBe('');
    expect(c.fiscalYears()).toEqual([]);
    expect(c.loading()).toBe(false);
  });

  it('records fiscal years per budget for the left tree and keeps a valid selected fy', async () => {
    const { c } = await setup();
    expect(c.fiscalYearsByBudget()).toEqual({ 'b-vs': [FY] });
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('clears an invalid selected fy on reload (defaults to first)', async () => {
    const { c, http } = await setup();
    c.selectedFyId.set('does-not-exist');
    c['reload']();
    flushReload(http);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('resets the selected fy to "" when the selected top has no fiscal years on reload', async () => {
    const { c, http } = await setup();
    c.selectedFyId.set('fy-1');
    c['reload']();
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(TREE);
    // Empty fiscal-years list for the selected top → fys[0]?.id ?? '' → ''.
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
    expect(c.fiscalYears()).toEqual([]);
    expect(c.selectedFyId()).toBe('');
  });

  it('tolerates a per-top fiscal-years error (no throw, list left untouched)', async () => {
    const { c, http } = await setup();
    c['reload']();
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(TREE);
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years'))
      .flush(null, { status: 500, statusText: 'err' });
    expect(c.loading()).toBe(false);
  });

  it('surfaces a load error when the tree request fails', async () => {
    const { c, http } = await setup();
    c['reload']();
    http
      .expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET')
      .flush(null, { status: 500, statusText: 'err' });
    expect(c.loadError()).toBe(true);
    expect(c.loading()).toBe(false);
  });

  // ------------------------------------------------------------ alloc / money
  it('alloc returns the matching fiscal-year allocation or null', async () => {
    const { c } = await setup();
    expect(c.alloc(TREE[0])?.allocated).toBe('1000');
    c.selectedFyId.set('other');
    expect(c.alloc(TREE[0])).toBeNull();
  });

  it('money formats numbers, empty strings and null as currency', async () => {
    const { c } = await setup();
    const eur = (n: number) =>
      new Intl.NumberFormat(TestBed.inject(I18nService).locale(), {
        style: 'currency',
        currency: 'EUR',
      }).format(n);
    expect(c.money('1234.5', 'EUR')).toBe(eur(1234.5));
    expect(c.money('', 'EUR')).toBe(eur(0));
    expect(c.money(null, 'EUR')).toBe(eur(0));
    expect(c.money(undefined, 'EUR')).toBe(eur(0));
    expect(c.money(42, 'EUR')).toBe(eur(42));
  });

  // -------------------------------------------------------- accepted / denied
  it('reports accepted/denied membership for the selected top', async () => {
    const { c } = await setup();
    expect(c.isAccepted('accepted')).toBe(true);
    expect(c.isAccepted('denied')).toBe(false);
    expect(c.isDenied('denied')).toBe(true);
    expect(c.isDenied('accepted')).toBe(false);
  });

  it('accepted/denied sets are empty when no top is selected', async () => {
    const { c } = await setup();
    c.selectedTopId.set('none');
    expect([...c.acceptedKeys()]).toEqual([]);
    expect([...c.deniedKeys()]).toEqual([]);
  });

  // ---------------------------------------------------------------- selectTop
  it('selectTop sets the budget, clears the fy and loads fiscal years', async () => {
    const { c, http } = await setup();
    c.selectTop('b-vs');
    expect(c.selectedTopId()).toBe('b-vs');
    expect(c.selectedFyId()).toBe('');
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
    expect(c.fiscalYears()).toEqual([FY]);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('loadFiscalYears keeps an already-valid selected fy', async () => {
    const { c, http } = await setup();
    c.selectedFyId.set('fy-1');
    c.selectTop('b-vs');
    // selectTop wiped the fy; loadFiscalYears keeps it only if still present.
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('loadFiscalYears resets the selected fy to "" for an empty list (next path)', async () => {
    const { c, http } = await setup();
    c.selectedFyId.set('fy-1');
    c.selectTop('b-vs');
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
    expect(c.fiscalYears()).toEqual([]);
    expect(c.selectedFyId()).toBe('');
  });

  it('loadFiscalYears empties the list on error', async () => {
    const { c, http } = await setup();
    c.selectTop('b-vs');
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years'))
      .flush(null, { status: 500, statusText: 'err' });
    expect(c.fiscalYears()).toEqual([]);
  });

  it('onYearPicked sets budget + cached fiscal years + fy from the left tree', async () => {
    const { c } = await setup();
    c.onYearPicked({ budgetId: 'b-vs', fiscalYearId: 'fy-1' });
    expect(c.selectedTopId()).toBe('b-vs');
    expect(c.fiscalYears()).toEqual([FY]);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('onYearPicked falls back to an empty fiscal-year list for an uncached budget', async () => {
    const { c } = await setup();
    c.onYearPicked({ budgetId: 'unknown', fiscalYearId: 'fy-x' });
    expect(c.fiscalYears()).toEqual([]);
    expect(c.selectedFyId()).toBe('fy-x');
  });

  // ----------------------------------------------------------------- saveColor
  it('saveColor PATCHes the color, toasts success and reloads', async () => {
    const { c, http, toast } = await setup();
    c.saveColor(TREE[0], '#ff0000');
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ color: '#ff0000' });
    patch.flush({});
    expect(toast.success).toHaveBeenCalled();
    flushReload(http);
  });

  it('saveColor sends an empty string when clearing the color', async () => {
    const { c, http } = await setup();
    c.saveColor(TREE[0], '');
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ color: '' });
    patch.flush({});
    flushReload(http);
  });

  it('saveColor toasts an error and does not reload on failure', async () => {
    const { c, http, toast } = await setup();
    c.saveColor(TREE[0], '#abc');
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
    http.verify();
  });

  // --------------------------------------------------------------- toggleState
  it('toggleState does nothing when no top is selected', async () => {
    const { c, http } = await setup();
    c.selectedTopId.set('none');
    c.toggleState('accepted', 'x');
    http.verify(); // no PATCH was issued
  });

  it('toggleState removes an already-set key', async () => {
    const { c, http } = await setup();
    c.toggleState('accepted', 'accepted'); // currently set → removed
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ acceptedStateKeys: [], deniedStateKeys: ['denied'] });
    patch.flush({});
    flushReload(http);
  });

  it('toggleState adds a new accepted key and removes it from denied (mutual exclusion)', async () => {
    const { c, http } = await setup();
    c.toggleState('accepted', 'denied'); // 'denied' was in deniedKeys → moves to accepted
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({
      acceptedStateKeys: ['accepted', 'denied'],
      deniedStateKeys: [],
    });
    patch.flush({});
    flushReload(http);
  });

  it('toggleState adds a new denied key and removes it from accepted', async () => {
    const { c, http } = await setup();
    c.toggleState('denied', 'accepted');
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({
      acceptedStateKeys: [],
      deniedStateKeys: ['denied', 'accepted'],
    });
    patch.flush({});
    flushReload(http);
  });

  it('toggleState toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.toggleState('accepted', 'new');
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  // ------------------------------------------------------------ top dialog
  it('openTop resets the draft and opens; closeTop closes', async () => {
    const { c } = await setup();
    c.newTop.set({ key: 'X', name: 'Y', fiscalStartMonth: 3, fiscalStartDay: 4 });
    c.openTop();
    expect(c.newTop()).toEqual({ key: '', name: '', fiscalStartMonth: 1, fiscalStartDay: 1 });
    expect(c.topOpen()).toBe(true);
    c.closeTop();
    expect(c.topOpen()).toBe(false);
  });

  it('patchTop updates a single draft field', async () => {
    const { c } = await setup();
    c.patchTop('key', 'AStA');
    c.patchTop('name', 'AStA-Mittel');
    expect(c.newTop().key).toBe('AStA');
    expect(c.newTop().name).toBe('AStA-Mittel');
  });

  it('patchTopStichtag clamps month to 1..12 and day to 1..31, defaulting non-numbers to 1', async () => {
    const { c } = await setup();
    c.patchTopStichtag('fiscalStartMonth', '99');
    expect(c.newTop().fiscalStartMonth).toBe(12);
    c.patchTopStichtag('fiscalStartMonth', '0');
    expect(c.newTop().fiscalStartMonth).toBe(1);
    c.patchTopStichtag('fiscalStartDay', '99');
    expect(c.newTop().fiscalStartDay).toBe(31);
    c.patchTopStichtag('fiscalStartDay', 'abc');
    expect(c.newTop().fiscalStartDay).toBe(1);
    c.patchTopStichtag('fiscalStartMonth', '7.9');
    expect(c.newTop().fiscalStartMonth).toBe(7);
  });

  it('createTop does nothing when key or name is blank', async () => {
    const { c, http } = await setup();
    c.newTop.set({ key: '   ', name: 'Name', fiscalStartMonth: 1, fiscalStartDay: 1 });
    c.createTop(new Event('submit'));
    c.newTop.set({ key: 'Key', name: '  ', fiscalStartMonth: 1, fiscalStartDay: 1 });
    c.createTop(new Event('submit'));
    http.verify();
  });

  it('createTop POSTs, selects the new node, closes and reloads', async () => {
    const { c, http, toast } = await setup();
    c.openTop();
    c.patchTop('key', 'AStA');
    c.patchTop('name', 'AStA-Mittel');
    c.patchTopStichtag('fiscalStartMonth', '7');
    c.createTop(new Event('submit'));
    const post = http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'POST');
    expect(post.request.body).toEqual({
      key: 'AStA',
      name: 'AStA-Mittel',
      fiscalStartMonth: 7,
      fiscalStartDay: 1,
    });
    post.flush({ id: 'b-asta' });
    expect(c.selectedTopId()).toBe('b-asta');
    expect(c.topOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    // reload: TREE has no b-asta → keep=false → falls back to first top b-vs.
    flushReload(http);
    expect(c.selectedTopId()).toBe('b-vs');
  });

  it('createTop toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.openTop();
    c.patchTop('key', 'AStA');
    c.patchTop('name', 'AStA-Mittel');
    c.createTop(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/budgets') && r.method === 'POST')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  // ------------------------------------------------------------ saveStichtag
  it('saveStichtag does nothing without a selected top', async () => {
    const { c, http } = await setup();
    c.selectedTopId.set('none');
    c.saveStichtag('fiscalStartMonth', '5');
    http.verify();
  });

  it('saveStichtag PATCHes the clamped value, toasts, reloads + reloads fiscal years', async () => {
    const { c, http, toast } = await setup();
    c.saveStichtag('fiscalStartMonth', '13');
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ fiscalStartMonth: 12 });
    patch.flush({});
    expect(toast.success).toHaveBeenCalled();
    // reload() then loadFiscalYears(top.id) → 1 tree GET + 2 fiscal-years GETs.
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(TREE);
    http.match((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).forEach((req) => req.flush([FY]));
  });

  it('saveStichtag defaults a non-numeric day to 1 and toasts on error', async () => {
    const { c, http, toast } = await setup();
    c.saveStichtag('fiscalStartDay', 'abc');
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ fiscalStartDay: 1 });
    patch.flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  // ----------------------------------------------------------- dialog toggles
  it('opens and closes the stichtag and state-config dialogs', async () => {
    const { c } = await setup();
    c.openStichtag();
    expect(c.stichtagOpen()).toBe(true);
    c.closeStichtag();
    expect(c.stichtagOpen()).toBe(false);
    c.openStateConfig();
    expect(c.stateConfigOpen()).toBe(true);
    c.closeStateConfig();
    expect(c.stateConfigOpen()).toBe(false);
  });

  // -------------------------------------------------------------- child nodes
  it('startAddChild opens the parent and resets the draft; cancelAddChild closes', async () => {
    const { c } = await setup();
    c.childDraft.set({ key: 'X', name: 'Y' });
    c.startAddChild(TREE[0]);
    expect(c.addingChildOf()).toBe('b-vs');
    expect(c.childDraft()).toEqual({ key: '', name: '' });
    c.cancelAddChild();
    expect(c.addingChildOf()).toBeNull();
  });

  it('patchChild updates a single child-draft field', async () => {
    const { c } = await setup();
    c.patchChild('key', '40');
    c.patchChild('name', 'Sport');
    expect(c.childDraft()).toEqual({ key: '40', name: 'Sport' });
  });

  it('addChild does nothing when key or name is blank', async () => {
    const { c, http } = await setup();
    c.childDraft.set({ key: '  ', name: 'Name' });
    c.addChild(TREE[0]);
    c.childDraft.set({ key: 'Key', name: '  ' });
    c.addChild(TREE[0]);
    http.verify();
  });

  it('addChild POSTs under the parent (inheriting currency), toasts, closes and reloads', async () => {
    const { c, http, toast } = await setup();
    c.startAddChild(TREE[0]);
    c.patchChild('key', '40');
    c.patchChild('name', 'Sport');
    c.addChild(TREE[0]);
    const post = http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'POST');
    expect(post.request.body).toEqual({
      parentId: 'b-vs',
      key: '40',
      name: 'Sport',
      currency: 'EUR',
    });
    post.flush({ id: 'b-40' });
    expect(c.addingChildOf()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
    flushReload(http);
  });

  it('addChild toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.startAddChild(TREE[0]);
    c.patchChild('key', '40');
    c.patchChild('name', 'Sport');
    c.addChild(TREE[0]);
    http
      .expectOne((r) => r.url.endsWith('/budgets') && r.method === 'POST')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  // ---------------------------------------------------------------- deleteNode
  it('deleteNode DELETEs, toasts success and reloads', async () => {
    const { c, http, toast } = await setup();
    c.deleteNode(TREE[0].children[0]);
    http.expectOne((r) => r.url.endsWith('/budgets/b-800') && r.method === 'DELETE').flush(null);
    expect(toast.success).toHaveBeenCalled();
    flushReload(http);
  });

  it('deleteNode toasts a delete error on failure', async () => {
    const { c, http, toast } = await setup();
    c.deleteNode(TREE[0].children[0]);
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-800') && r.method === 'DELETE')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  // ------------------------------------------------------------- edit node
  it('openEditNode prefills key/name/hidden/viewGremium from the node', async () => {
    const { c } = await setup();
    const node = fullNode({
      id: 'b-x',
      key: 'K',
      name: 'Name',
      hiddenInBudget: true,
      viewGremiumId: 'g-9',
    });
    c.openEditNode(node);
    expect(c.editNode()).toBe(node);
    expect(c.editKey()).toBe('K');
    expect(c.editName()).toBe('Name');
    expect(c.editHidden()).toBe(true);
    expect(c.editViewGremium()).toBe('g-9');
  });

  it('openEditNode defaults the view gremium to "" when null', async () => {
    const { c } = await setup();
    c.openEditNode(fullNode({ id: 'b-x', viewGremiumId: null }));
    expect(c.editViewGremium()).toBe('');
  });

  it('closeEditNode clears the edit node', async () => {
    const { c } = await setup();
    c.openEditNode(TREE[0]);
    c.closeEditNode();
    expect(c.editNode()).toBeNull();
  });

  it('saveEditNode does nothing when no node is open', async () => {
    const { c, http } = await setup();
    c.closeEditNode();
    c.saveEditNode();
    http.verify();
  });

  it('saveEditNode does nothing when key or name trims to empty', async () => {
    const { c, http } = await setup();
    c.openEditNode(TREE[0]);
    c.editKey.set('  ');
    c.editName.set('Name');
    c.saveEditNode();
    c.editKey.set('Key');
    c.editName.set('  ');
    c.saveEditNode();
    http.verify();
  });

  it('saveEditNode PATCHes key/name/hidden/viewGremium (null when blank), toasts and reloads', async () => {
    const { c, http, toast } = await setup();
    c.openEditNode(TREE[0]);
    c.editKey.set(' VS ');
    c.editName.set(' VS-Mittel ');
    c.editHidden.set(true);
    c.editViewGremium.set('');
    c.saveEditNode();
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({
      key: 'VS',
      name: 'VS-Mittel',
      hiddenInBudget: true,
      viewGremiumId: null,
    });
    patch.flush({});
    expect(c.editNode()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
    flushReload(http);
  });

  it('saveEditNode keeps a non-empty view gremium and toasts a key error on failure', async () => {
    const { c, http, toast } = await setup();
    c.openEditNode(TREE[0]);
    c.editViewGremium.set('g-1');
    c.saveEditNode();
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body.viewGremiumId).toBe('g-1');
    patch.flush(null, { status: 409, statusText: 'conflict' });
    expect(toast.error).toHaveBeenCalled();
  });

  // -------------------------------------------------------------- limit dialog
  it('openLimit prefills the value from the current allocation', async () => {
    const { c } = await setup();
    c.openLimit(TREE[0]);
    expect(c.limitNode()).toBe(TREE[0]);
    expect(c.limitValue()).toBe('1000');
  });

  it('openLimit defaults the value to "" when there is no matching allocation', async () => {
    const { c } = await setup();
    c.selectedFyId.set('other-fy');
    c.openLimit(TREE[0]);
    expect(c.limitValue()).toBe('');
  });

  it('closeLimit clears the limit node', async () => {
    const { c } = await setup();
    c.openLimit(TREE[0]);
    c.closeLimit();
    expect(c.limitNode()).toBeNull();
  });

  it('saveLimit does nothing without a node or fiscal year', async () => {
    const { c, http } = await setup();
    c.saveLimit(); // no node
    c.openLimit(TREE[0]);
    c.selectedFyId.set('');
    c.saveLimit(); // no fy
    http.verify();
  });

  it('saveLimit does nothing when the value trims to empty', async () => {
    const { c, http } = await setup();
    c.openLimit(TREE[0]);
    c.limitValue.set('   ');
    c.saveLimit();
    http.verify();
  });

  it('saveLimit PUTs the allocation, toasts, closes and reloads', async () => {
    const { c, http, toast } = await setup();
    c.openLimit(TREE[0].children[0]);
    c.limitValue.set('500');
    c.saveLimit();
    const put = http.expectOne((r) => r.url.endsWith('/budgets/b-800/allocations/fy-1'));
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ allocated: '500' });
    put.flush({});
    expect(c.limitNode()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
    flushReload(http);
  });

  it('saveLimit toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.openLimit(TREE[0].children[0]);
    c.limitValue.set('500');
    c.saveLimit();
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-800/allocations/fy-1'))
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  // ------------------------------------------------------------- fiscal years
  it('patchFyYear truncates the year and defaults non-numbers to the current year', async () => {
    const { c } = await setup();
    c.patchFyYear('2027.9');
    expect(c.newFy().year).toBe(2027);
    c.patchFyYear('abc');
    expect(c.newFy().year).toBe(new Date().getFullYear());
  });

  it('openFy resets the draft and opens; closeFy closes', async () => {
    const { c } = await setup();
    c.newFy.set({ year: 1999 });
    c.openFy();
    expect(c.newFy().year).toBe(new Date().getFullYear());
    expect(c.fyOpen()).toBe(true);
    c.closeFy();
    expect(c.fyOpen()).toBe(false);
  });

  it('createFiscalYear does nothing without a selected top', async () => {
    const { c, http } = await setup();
    c.selectedTopId.set('');
    c.createFiscalYear(new Event('submit'));
    http.verify();
  });

  it('createFiscalYear does nothing when the year is falsy', async () => {
    const { c, http } = await setup();
    c.newFy.set({ year: 0 });
    c.createFiscalYear(new Event('submit'));
    http.verify();
  });

  it('createFiscalYear POSTs, toasts, closes and reloads the fiscal years', async () => {
    const { c, http, toast } = await setup();
    c.openFy();
    c.patchFyYear('2027');
    c.createFiscalYear(new Event('submit'));
    const post = http.expectOne(
      (r) => r.url.endsWith('/budgets/b-vs/fiscal-years') && r.method === 'POST',
    );
    expect(post.request.body).toEqual({ year: 2027 });
    post.flush({ ...FY, id: 'fy-2', year: 2027 });
    expect(c.fyOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
  });

  it('createFiscalYear toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.openFy();
    c.patchFyYear('2027');
    c.createFiscalYear(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years') && r.method === 'POST')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });
});
