import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { type OrderPage, OrdersApiService, type PendingPage } from '@core/api/orders.service';
import { AuthService } from '@core/auth/auth.service';
import { type ListQuery, type ListRow, type LoadState, ToastService } from '@stupa-makers/ui-kit';
import { order } from '../../../testing/order-fixtures';
import { BudgetTreeApi } from '../budget/budget-tree.api';
import { ORDERS_PAGE_SIZE, OrdersPageComponent, orderQuery } from './orders-page.component';
import { OrdersRefresh } from './orders-refresh';

const PAGE: OrderPage = {
  items: [order(), order({ id: 'o-2', title: 'Kabel', status: 'delivered', actualAmount: '12.50', supplier: null, applicationTitle: null })],
  total: 3,
};

const PENDING: PendingPage = {
  items: [
    { id: 'a-1', title: 'Technik', gremiumId: 'g-1', gremiumName: 'StuPa', approvedAmount: '500.00' },
    { id: 'a-2', title: '', gremiumId: null, gremiumName: null, approvedAmount: null },
  ],
  total: 2,
};

const query = (filters: Record<string, unknown> = {}, search = ''): ListQuery =>
  ({ search, filters, sort: null }) as unknown as ListQuery;

interface Options {
  readonly permissions?: readonly string[];
  readonly userId?: string | null;
  readonly failOptions?: boolean;
  readonly gremien?: readonly { id: string; name: string }[];
}

async function setup(options: Options = {}) {
  localStorage.setItem('ap.locale', 'de');
  const permissions = options.permissions ?? ['order.manage', 'finance.export'];
  const fail = () => throwError(() => ({ status: 500 }));
  const api = {
    page: jest.fn(() => of(PAGE)),
    pending: jest.fn(() => of(PENDING)),
    exportXlsx: jest.fn(() => of(new Blob(['x']))),
  };
  const budget = {
    listBudgetYears: jest.fn(() =>
      options.failOptions ? fail() : of([{ fiscalYearId: 'fy-1', budgetName: 'Haushalt', display: '2026' }]),
    ),
    tree: jest.fn(() => (options.failOptions ? fail() : of([]))),
  };
  const client = {
    listMeetingFilterGremien: jest.fn(() =>
      options.failOptions ? fail() : of(options.gremien ?? [{ id: 'g-1', name: 'StuPa' }, { id: 'g-2', name: 'AStA' }]),
    ),
  };
  const view = await render(OrdersPageComponent, {
    providers: [
      provideRouter([]),
      { provide: OrdersApiService, useValue: api },
      { provide: BudgetTreeApi, useValue: budget },
      { provide: ApiClient, useValue: client },
      {
        provide: AuthService,
        useValue: {
          can: (p: string) => permissions.includes(p),
          userId: () => (options.userId === undefined ? 'me-1' : options.userId),
        },
      },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const refresh = view.fixture.debugElement.injector.get(OrdersRefresh);
  const rows = (): LoadState<readonly ListRow[]> => cmp.rows();
  return { ...view, cmp, api, budget, client, toast, refresh, rows };
}

describe('OrdersPageComponent', () => {
  afterEach(() => localStorage.clear());

  it('reads the filter of the API from the query of the screen', () => {
    expect(orderQuery(query({ fiscalYear: 'fy-1', budget: 'b-1', gremium: 'g-1', kind: 'outlay', buyer: 'me-1' }, ' Beamer '))).toEqual({
      fiscalYear: 'fy-1',
      budget: 'b-1',
      gremium: 'g-1',
      kind: 'outlay',
      buyer: 'me-1',
      q: 'Beamer',
    });
    expect(orderQuery(query({ fiscalYear: '', kind: null, buyer: 7 }))).toEqual({
      fiscalYear: undefined,
      budget: undefined,
      gremium: undefined,
      kind: undefined,
      buyer: undefined,
      q: undefined,
    });
  });

  /** §F/finance/orders/002883, 002884: the list starts with "Offen" and shows no count. */
  it('lists the Bestellungen of the segment "Offen" with status, price and link', async () => {
    const { cmp, api, rows } = await setup();
    cmp.onQuery(query());
    expect(api.page).toHaveBeenLastCalledWith({ limit: ORDERS_PAGE_SIZE, offset: 0, segment: 'open' });
    const state = rows();
    expect(state).toMatchObject({ state: 'ready', more: true });
    const data = state.state === 'ready' ? state.data : [];
    expect(data[0]).toMatchObject({
      id: 'o-1',
      title: 'Beamer',
      meta: ['Technik für den Sitzungssaal', 'Technikhaus'],
      status: { label: 'Geplant', kind: 'neutral' },
      link: { commands: ['/orders', 'o-1'] },
    });
    expect(data[0].trailing).toMatch(/^100,00\s€$/);
    expect(data[1]).toMatchObject({ meta: [], status: { label: 'Geliefert', kind: 'accent' } });
    expect(screen.getByRole('heading', { name: 'Bestellungen' })).toBeInTheDocument();
    expect(cmp.filters()[0]).toMatchObject({ key: 'segment', value: 'open' });
    expect(cmp.filters()[0].options.map((o: { label: string }) => o.label)).toEqual(['Ohne Bestellung', 'Offen', 'Geliefert', 'Erledigt']);
  });

  /** §F/finance/orders/002934: "Ohne Bestellung" lists the Anträge that wait for a purchase. */
  it('lists the Anträge without a Bestellung and gives the action "Bestellung anlegen" to a person with order.manage', async () => {
    const { cmp, api, rows } = await setup();
    cmp.onQuery(query({ segment: 'pending', gremium: 'g-1' }));
    expect(api.pending).toHaveBeenLastCalledWith({
      gremium: 'g-1',
      limit: ORDERS_PAGE_SIZE,
      offset: 0,
    });
    const state = rows();
    const data = state.state === 'ready' ? state.data : [];
    expect(state).toMatchObject({ state: 'ready', more: false });
    expect(data[0]).toMatchObject({
      id: 'a-1',
      title: 'Technik',
      meta: ['StuPa'],
      link: { commands: ['/applications', 'a-1'] },
      actions: [
        { key: 'order', label: 'Bestellung anlegen', route: { commands: ['/orders', 'new'], query: { application: 'a-1' } } },
      ],
    });
    expect(data[0].trailing).toMatch(/^500,00\s€$/);
    expect(data[1]).toMatchObject({ title: 'Ohne Titel', meta: [], trailing: undefined });
  });

  it('opens the Antrag from "Ohne Bestellung" for a person without order.manage', async () => {
    const { cmp, rows } = await setup({ permissions: ['budget.view'] });
    cmp.onQuery(query({ segment: 'pending' }));
    const state = rows();
    expect(state.state === 'ready' && state.data[0].link).toEqual({ commands: ['/applications', 'a-1'] });
    expect(state.state === 'ready' && state.data[0].actions).toBeUndefined();
    expect(cmp.actions()).toEqual([]);
  });

  it('reads the next rows and adds them to the list', async () => {
    const { cmp, api, rows } = await setup();
    cmp.onQuery(query({ segment: 'delivered' }));
    cmp.more();
    expect(api.page).toHaveBeenLastCalledWith({ limit: ORDERS_PAGE_SIZE, offset: 2, segment: 'delivered' });
    const state = rows();
    expect(state.state === 'ready' && state.data).toHaveLength(4);
    expect(state).toMatchObject({ more: false });
    cmp.onQuery(query({ segment: 'pending' }));
    cmp.more();
    expect(api.pending).toHaveBeenLastCalledWith({ limit: ORDERS_PAGE_SIZE, offset: 2 });
    const pending = rows();
    expect(pending.state === 'ready' && pending.data).toHaveLength(4);
  });

  it('shows the empty state of each kind of segment', async () => {
    const { cmp, api, rows } = await setup();
    api.page.mockReturnValue(of({ items: [], total: 0 }));
    api.pending.mockReturnValue(of({ items: [], total: 0 }));
    cmp.onQuery(query({ segment: 'done' }));
    expect(rows()).toEqual({ state: 'empty', heading: 'Keine Bestellungen', icon: 'package' });
    cmp.onQuery(query({ segment: 'pending' }));
    expect(rows()).toMatchObject({ state: 'empty', icon: 'package' });
    expect((rows() as { heading: string }).heading).not.toBe('Keine Bestellungen');
  });

  it('keeps the old rows while it reads, drops a late answer and offers a retry after a failure', async () => {
    const { cmp, api, rows } = await setup();
    cmp.onQuery(query());
    const late = new Subject<OrderPage>();
    api.page.mockReturnValueOnce(late);
    cmp.onQuery(query({ kind: 'order' }));
    expect(rows()).toMatchObject({ state: 'loading' });
    expect((rows() as { previous?: unknown[] }).previous).toHaveLength(2);
    api.page.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.onQuery(query({ segment: 'unknown' }));
    late.next({ items: [], total: 0 });
    late.error({ status: 500 });
    const failed = rows();
    expect(failed).toMatchObject({ state: 'error', message: 'Die Bestellungen konnten nicht geladen werden.' });
    if (failed.state === 'error') failed.retry?.();
    expect(rows()).toMatchObject({ state: 'ready' });
    expect(api.page).toHaveBeenLastCalledWith({ limit: ORDERS_PAGE_SIZE, offset: 0, segment: 'open' });
  });

  it('drops a late answer and a late failure of "Ohne Bestellung"', async () => {
    const { cmp, api, rows } = await setup();
    const late = new Subject<PendingPage>();
    api.pending.mockReturnValueOnce(late);
    cmp.onQuery(query({ segment: 'pending' }));
    expect(rows()).toEqual({ state: 'loading' });
    api.pending.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.onQuery(query({ segment: 'pending' }));
    late.next(PENDING);
    expect(rows()).toMatchObject({ state: 'error' });
  });

  /** §F/finance/orders/002885: the chips of the filter. */
  it('offers the chips for year, Kostenstelle, Gremium, kind and the own purchases', async () => {
    const { cmp } = await setup();
    expect(cmp.filters().map((f: { key: string }) => f.key)).toEqual(['segment', 'fiscalYear', 'gremium', 'kind', 'buyer']);
    expect(cmp.filters()[1].options).toEqual([{ value: 'fy-1', label: 'Haushalt 2026' }]);
    expect(cmp.filters()[4].options).toEqual([{ value: 'me-1', label: 'Meine Käufe' }]);
  });

  it('leaves a chip out when its options failed, when one Gremium is all, and without an account id', async () => {
    const failed = await setup({ failOptions: true, userId: null });
    expect(failed.cmp.filters().map((f: { key: string }) => f.key)).toEqual(['segment', 'kind']);
  });

  it('shows no Gremium chip to a person with one Gremium', async () => {
    const { cmp } = await setup({ gremien: [{ id: 'g-1', name: 'StuPa' }] });
    expect(cmp.filters().map((f: { key: string }) => f.key)).not.toContain('gremium');
  });

  /** §F/finance/orders/002886: the export takes the filter of the list. */
  it('exports the list with its filter and says when the export fails', async () => {
    const { cmp, api, toast } = await setup();
    const show = jest.spyOn(toast, 'show');
    const created = jest.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: jest.fn() });
    expect(cmp.actions().map((a: { key: string; priority: string }) => [a.key, a.priority])).toEqual([
      ['new', 'fab'],
      ['export', 'menu'],
    ]);
    cmp.onQuery(query({ segment: 'delivered', kind: 'outlay' }));
    cmp.onAction('new');
    expect(api.exportXlsx).not.toHaveBeenCalled();
    cmp.onAction('export');
    expect(api.exportXlsx).toHaveBeenLastCalledWith({ kind: 'outlay', segment: 'delivered' });
    expect(created).toHaveBeenCalled();
    cmp.onQuery(query({ segment: 'pending' }));
    api.exportXlsx.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.onAction('export');
    expect(api.exportXlsx).toHaveBeenLastCalledWith({});
    expect(show).toHaveBeenCalledWith('Der Export ist fehlgeschlagen.', 'error');
  });

  /** §F/finance/orders/002886: the export needs `finance.export`, not `order.manage`. */
  it.each([
    [['order.manage'], ['new']],
    [['budget.view', 'finance.export'], ['export']],
    [['budget.view'], []],
  ])('offers the actions of the permissions %j', async (permissions, keys) => {
    const { cmp } = await setup({ permissions });
    expect(cmp.actions().map((a: { key: string }) => a.key)).toEqual(keys);
  });

  it('reads the list again when the pane changed a Bestellung', async () => {
    const { cmp, api, refresh } = await setup();
    cmp.onQuery(query());
    const before = api.page.mock.calls.length;
    refresh.touch();
    expect(api.page).toHaveBeenCalledTimes(before + 1);
  });
});
