import { DEFAULT_STATUS_LISTS, nextStatus, provideTestStatuses } from '@core/api/statuses.service';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { BehaviorSubject, type Observable, Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Application, Transition } from '@core/api/models';
import { type Order, type OrderList, OrdersApiService } from '@core/api/orders.service';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { NO_ORDER_LIST, order } from '../../../testing/order-fixtures';
import { NO_LINKED_TODOS } from '../../../testing/todo-fixtures';
import { BudgetTreeApi } from '../budget/budget-tree.api';
import { OrderDetailComponent } from './order-detail.component';
import { OrdersRefresh } from './orders-refresh';

const APPLICATION = {
  id: 'a-1',
  currency: 'EUR',
  data: {
    costs: [
      { id: 'p-1', label: 'Beamer', offers: [{ label: 'Technikhaus', value: 90, preferred: true }] },
    ],
  },
} as unknown as Application;

const LIST: OrderList = { ...NO_ORDER_LIST, items: [], total: '212.50', approvedAmount: '200.00', overBy: '12.50', canManage: true };

const transition = (over: Partial<Transition> = {}): Transition =>
  ({ id: 't-1', fromStateId: 's1', toStateId: 's2', label: 'Als beschafft markieren', color: null, addsToAgenda: false, agendaGremiumId: null, ...over }) as Transition;

const conflict = () => throwError(() => ({ error: { code: 'order_version_conflict' } }));
const broken = () => throwError(() => ({ status: 500 }));

interface Options {
  readonly first?: Order;
  readonly permissions?: readonly string[];
  readonly list?: OrderList | null;
}

async function setup(options: Options = {}) {
  localStorage.setItem('ap.locale', 'de');
  const permissions = options.permissions ?? ['order.manage', 'budget.view', 'budget.book'];
  const first = options.first ?? order({ positionIds: ['p-1', 'gone'] });
  const api = {
    get: jest.fn(() => of(first)),
    list: jest.fn(() => (options.list === null ? broken() : of(options.list ?? LIST))),
    bookings: jest.fn(() => of([{ id: 'b-1', description: 'Beamer bezahlt', amount: '40.00' }, { id: 'b-2', description: null, amount: '10.00' }])),
    setStatus: jest.fn((_id: string, status: Order['status']): Observable<Order> => of({ ...first, status, version: 2 })),
    setInvoice: jest.fn((_id: string, invoiceId: string | null) => of({ ...first, invoiceId, invoiceNumber: invoiceId ? 'R-1' : null, invoiceStatus: invoiceId ? ('open' as const) : null })),
    remove: jest.fn(() => of(undefined)),
    files: jest.fn(() => of([])),
  };
  const client = {
    getApplication: jest.fn(() => of(APPLICATION)),
    transitions: jest.fn(() => of([transition()])),
    fireTransition: jest.fn(() => of({})),
    comments: jest.fn(() => of([])),
    mentionable: jest.fn(() => of([])),
  };
  const budget = {
    listInvoicesPaged: jest.fn(() =>
      of({
        items: [
          { id: 'i-1', number: 'R-1', supplier: 'Technikhaus', grossAmount: '100.00', status: 'open' },
          { id: 'i-2', number: null, supplier: null, grossAmount: null, status: 'paid' },
        ],
        total: 2,
      }),
    ),
  };
  const paramMap = new BehaviorSubject(convertToParamMap({ id: first.id }));
  const view = await render(OrderDetailComponent, {
    providers: [
      provideTestStatuses(),
      provideRouter([]),
      NO_LINKED_TODOS,
      { provide: OrdersApiService, useValue: api },
      { provide: ApiClient, useValue: client },
      { provide: BudgetTreeApi, useValue: budget },
      {
        provide: AuthService,
        useValue: {
          can: (p: string) => permissions.includes(p),
          canAny: (...ps: string[]) => ps.some((p) => permissions.includes(p)),
        },
      },
      {
        provide: ActivatedRoute,
        useValue: { paramMap, snapshot: { queryParamMap: convertToParamMap({}), fragment: null }, queryParamMap: of(convertToParamMap({})), fragment: of(null) },
      },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const injector = view.fixture.debugElement.injector;
  const toast = jest.spyOn(injector.get(ToastService), 'show');
  const navigate = jest.spyOn(injector.get(Router), 'navigate').mockResolvedValue(true);
  const touched = jest.fn();
  injector.get(OrdersRefresh).changed.subscribe(touched);
  const keys = (): string[] => cmp.actions().map((a: { key: string }) => a.key);
  return { ...view, cmp, api, client, budget, paramMap, toast, navigate, touched, keys };
}

describe('OrderDetailComponent', () => {
  afterEach(() => {
    localStorage.clear();
    jest.useRealTimers();
  });

  /** §F/administration/admin/003035: the next status of the list that is not void. */
  it('names the status that follows in the list of the Bestellungen', () => {
    const list = DEFAULT_STATUS_LISTS.order;
    expect(['planned', 'ordered', 'delivered', 'cancelled', 'gone'].map((key) => nextStatus(list, key)?.key ?? null)).toEqual([
      'ordered',
      'delivered',
      null,
      null,
      null,
    ]);
  });

  /** §F/finance/orders/002936: head, fields, positions, sum and the built-in rows of "Verknüpft". */
  it('shows the Bestellung with its difference, its positions, the sum and the linked rows', async () => {
    const first = order({
      positionIds: ['p-1', 'gone'],
      kind: 'outlay',
      actualAmount: '112.50',
      invoiceId: 'i-1',
      invoiceNumber: null,
      invoiceStatus: 'paid',
      bookedAmount: '50.00',
    });
    const { cmp, api, client, fixture } = await setup({ first });
    fixture.detectChanges();
    expect(api.get).toHaveBeenCalledWith('o-1');
    expect(api.list).toHaveBeenCalledWith('a-1');
    expect(client.getApplication).toHaveBeenCalledWith('a-1', { quiet: true });
    expect(api.bookings).toHaveBeenCalledWith('o-1');
    expect(cmp.state()).toEqual({ state: 'ready', data: first });
    expect(cmp.head()).toMatchObject({
      title: 'Beamer',
      kicker: 'B-7K3QX9MD',
      status: { label: 'Geplant', kind: 'neutral' },
      back: null,
    });
    expect(cmp.head().meta.map((m: { label: string }) => m.label)).toEqual([
      'Auslage',
      'Rechnung bezahlt',
      expect.stringMatching(/^Verbucht 50,00\s€$/),
    ]);
    const facts: { label: string; value: string }[] = cmp.facts();
    const labels = facts.map((f) => f.label);
    expect(labels).not.toContain('Nummer');
    expect(labels).not.toContain('Status');
    expect(labels).not.toContain('Positionen der Kostenaufstellung');
    expect(labels.indexOf('Abweichung')).toBe(labels.indexOf('Tatsächlicher Preis') + 1);
    expect(facts.find((f) => f.label === 'Abweichung')?.value).toMatch(/^\+12,50\s€$/);
    expect(cmp.covered()).toEqual([
      { id: 'p-1', label: 'Beamer', value: expect.stringMatching(/^90,00\s€$/) },
      { id: 'gone', label: 'Entfernte Position', value: '' },
    ]);
    expect(cmp.sumLine()).toMatch(/^212,50\s€$/);
    expect(cmp.approvedLine()).toMatch(/^200,00\s€$/);
    expect(cmp.warning()).toMatch(/^Alle Bestellungen des Antrags liegen zusammen 12,50\s€ über dem genehmigten Betrag\.$/);
    expect(cmp.linked()).toEqual([
      { icon: 'file', title: 'Technik für den Sitzungssaal', sub: 'Antrag', link: ['/applications', 'a-1'] },
      { icon: 'receipt', title: 'Rechnung ohne Nummer', sub: 'Rechnung · Rechnung bezahlt', link: ['/invoices'], queryParams: { id: 'i-1' } },
      { icon: 'swap', title: 'Beamer bezahlt', sub: expect.stringMatching(/^Buchung · 40,00\s€$/), link: ['/expenses'], queryParams: { id: 'b-1' } },
      { icon: 'swap', title: 'Buchung', sub: expect.stringMatching(/^Buchung · 10,00\s€$/), link: ['/expenses'], queryParams: { id: 'b-2' } },
    ]);
    expect(screen.getByRole('heading', { name: 'Beamer', level: 1 })).toBeInTheDocument();
    expect(screen.getAllByTestId('od-position')).toHaveLength(2);
    expect(screen.getByTestId('od-sum')).toBeInTheDocument();
  });

  it('shows a Bestellung without Antrag, sum or difference with its plain parts', async () => {
    const first = order({ applicationId: undefined, applicationTitle: null, invoiceId: 'i-1', invoiceNumber: 'R-9', invoiceStatus: 'open' });
    const { cmp, api, client } = await setup({ first, permissions: [] });
    expect(api.list).not.toHaveBeenCalled();
    expect(client.getApplication).not.toHaveBeenCalled();
    expect(cmp.canManage()).toBe(false);
    expect(cmp.step()).toBeNull();
    expect(cmp.actions()).toEqual([]);
    expect(cmp.covered()).toEqual([]);
    expect(cmp.sumLine()).toBe('');
    expect(cmp.warning()).toBe('');
    expect(cmp.facts().map((f: { label: string }) => f.label)).not.toContain('Abweichung');
    expect(cmp.linked()).toEqual([
      { icon: 'receipt', title: 'R-9', sub: 'Rechnung · Rechnung offen', link: ['/invoices'], queryParams: { id: 'i-1' } },
    ]);
    cmp.onOffer('t-1');
    expect(client.fireTransition).not.toHaveBeenCalled();
  });

  /** §F/finance/orders/003014: a Bestellung without an Antrag shows the bookings that name it. */
  it('lists the bookings of a Bestellung without an Antrag', async () => {
    const { cmp, api } = await setup({ first: order({ applicationId: null, applicationTitle: null }) });
    expect(api.list).not.toHaveBeenCalled();
    expect(api.bookings).toHaveBeenCalledWith('o-1');
    expect(cmp.linked().map((row: { title: string }) => row.title)).toEqual(['Beamer bezahlt', 'Buchung']);
    expect(cmp.sumLine()).toBe('');
  });

  it('shows the sum alone without an approved amount, and an untitled Antrag', async () => {
    const { cmp, api } = await setup({
      first: order({ applicationTitle: '' }),
      list: { ...LIST, approvedAmount: null, overBy: null },
      permissions: ['order.manage'],
    });
    expect(cmp.sumLine()).toMatch(/^212,50\s€$/);
    expect(cmp.linked()[0].title).toBe('Ohne Titel');
    expect(api.bookings).not.toHaveBeenCalled();
    expect(screen.getByTestId('od-step')).toHaveTextContent('Als „Bestellt“ markieren');
  });

  it('leaves the parts of the Antrag out when their reads fail, and hides the sum of the applicant view', async () => {
    const { cmp, api, client, paramMap } = await setup({ list: null });
    expect(cmp.sumLine()).toBe('');
    expect(cmp.canManage()).toBe(true);
    api.list.mockReturnValue(of(NO_ORDER_LIST));
    client.getApplication.mockReturnValue(throwError(() => ({ status: 403 })));
    api.bookings.mockReturnValue(throwError(() => ({ status: 403 })));
    paramMap.next(convertToParamMap({ id: 'o-2' }));
    expect(cmp.sumLine()).toBe('');
    expect(cmp.canManage()).toBe(false);
    expect(cmp.linked()).toHaveLength(1);
  });

  it('offers a retry when the Bestellung does not load, and drops the answers of an older address', async () => {
    const { cmp, api, client, paramMap } = await setup();
    const slow = new Subject<Order>();
    api.get.mockReturnValueOnce(slow);
    paramMap.next(convertToParamMap({}));
    expect(cmp.state()).toEqual({ state: 'loading' });
    expect(cmp.head()).toEqual({ title: 'Bestellung', back: null });
    expect(cmp.facts()).toEqual([]);
    expect(cmp.linked()).toEqual([]);
    cmp.onAction('delete');
    cmp.setStatus('ordered');
    cmp.setInvoice(null);
    cmp.confirmDelete();
    expect(cmp.deleting()).toBe(false);
    api.get.mockReturnValueOnce(throwError(() => ({ status: 404 })));
    paramMap.next(convertToParamMap({ id: 'o-9' }));
    slow.next(order({ id: 'old' }));
    slow.error({ status: 500 });
    const failed = cmp.state();
    expect(failed).toMatchObject({ state: 'error', message: 'Die Bestellung konnte nicht geladen werden.' });
    const lists = new Subject<OrderList>();
    const apps = new Subject<Application>();
    const books = new Subject<never[]>();
    api.list.mockReturnValueOnce(lists);
    client.getApplication.mockReturnValueOnce(apps);
    api.bookings.mockReturnValueOnce(books);
    failed.retry();
    expect(cmp.state().state).toBe('ready');
    paramMap.next(convertToParamMap({ id: 'o-10' }));
    api.list.mockClear();
    lists.next({ ...LIST, total: '1.00' });
    apps.next({ ...APPLICATION, currency: 'CHF' });
    books.next([]);
    expect(cmp.sumLine()).toMatch(/^212,50/);
    expect(cmp.linked()).toHaveLength(3);
  });

  /** §F/finance/orders/002870: the next status is the main button, the rest is in the menu. */
  it('offers the next status as the main button and every other action in the menu', async () => {
    const { cmp, keys } = await setup();
    expect(cmp.step()).toEqual({ status: 'ordered', label: 'Als „Bestellt“ markieren' });
    expect(keys()).toEqual(['status:delivered', 'invoiceLink', 'invoiceNew', 'booking', 'edit', 'status:cancelled', 'delete']);
    const byKey = Object.fromEntries(cmp.actions().map((a: { key: string }) => [a.key, a]));
    expect(byKey['edit']).toMatchObject({ priority: 'head', route: { commands: ['/orders', 'o-1', 'edit'] } });
    expect(byKey['invoiceNew'].route).toEqual({ commands: ['/invoices'], query: { new: 'invoice', order: 'o-1' } });
    expect(byKey['booking'].route).toEqual({ commands: ['/expenses'], query: { new: 'booking', order: 'o-1' } });
    expect(byKey['delete']).toMatchObject({ kind: 'danger', priority: 'menu' });
    cmp.onAction('edit');
    cmp.onAction('booking');
    cmp.onAction('invoiceNew');
  });

  it('fits the menu to the status, the invoice and the rights', async () => {
    const delivered = await setup({ first: order({ status: 'delivered', invoiceId: 'i-1' }), permissions: ['order.manage'] });
    expect(delivered.cmp.step()).toBeNull();
    expect(delivered.keys()).toEqual(['status:planned', 'status:ordered', 'invoiceUnlink', 'edit', 'status:cancelled', 'delete']);
  });

  it('offers no cancel for a cancelled Bestellung', async () => {
    const { keys, cmp } = await setup({ first: order({ status: 'cancelled' }), permissions: ['order.manage', 'budget.view'] });
    expect(cmp.step()).toBeNull();
    expect(keys()).toEqual(['status:planned', 'status:ordered', 'status:delivered', 'invoiceLink', 'edit', 'delete']);
  });

  /** §F/finance/orders/002931: after "Bestellt" the detail offers the marked transitions; nothing fires by itself. */
  it('sets the next status and offers the transition of the Antrag without firing it', async () => {
    const { cmp, api, client, touched, toast } = await setup();
    cmp.setStatus('ordered');
    expect(api.setStatus).toHaveBeenCalledWith('o-1', 'ordered', 1);
    expect(cmp.order().status).toBe('ordered');
    expect(touched).toHaveBeenCalledTimes(1);
    expect(client.transitions).toHaveBeenCalledWith('a-1', { orderStatus: 'ordered' });
    expect(cmp.offered()).toHaveLength(1);
    expect(cmp.offerActions()).toEqual([
      { key: '', label: 'Nicht jetzt' },
      { key: 't-1', label: 'Als beschafft markieren', kind: 'main' },
    ]);
    expect(client.fireTransition).not.toHaveBeenCalled();
    cmp.onOffer('');
    expect(cmp.offered()).toEqual([]);
    expect(client.fireTransition).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it('fires the offered transition on a press and says how it went', async () => {
    const { cmp, client, toast, navigate } = await setup({ first: order({ status: 'ordered', version: undefined }) });
    client.transitions.mockReturnValue(of([transition(), transition({ id: 't-2', label: 'Zur Sitzung', addsToAgenda: true }), transition({ id: 't-3', label: 'Entscheiden', allowsDecision: true })]));
    cmp.onAction('status:delivered');
    expect(client.transitions).toHaveBeenCalledWith('a-1', { orderStatus: 'delivered' });
    expect(cmp.offerActions().map((a: { kind?: string }) => a.kind)).toEqual([undefined, 'main', undefined, undefined]);
    cmp.onOffer('t-1');
    expect(client.fireTransition).toHaveBeenCalledWith('a-1', { transitionId: 't-1' });
    expect(toast).toHaveBeenCalledWith('Übergang „Als beschafft markieren“ ausgeführt.', 'success');
    cmp.offered.set([transition()]);
    client.fireTransition.mockReturnValueOnce(throwError(() => ({ status: 409 })));
    cmp.onOffer('t-1');
    expect(toast).toHaveBeenCalledWith('Der Übergang konnte nicht ausgeführt werden.', 'error');
    cmp.offered.set([transition({ id: 't-2', addsToAgenda: true })]);
    cmp.onOffer('t-2');
    expect(navigate).toHaveBeenCalledWith(['/applications', 'a-1']);
    cmp.offered.set([transition({ id: 't-3', allowsDecision: true })]);
    cmp.onOffer('t-3');
    expect(navigate).toHaveBeenCalledTimes(2);
    expect(client.fireTransition).toHaveBeenCalledTimes(2);
  });

  it('asks the flow after each status, and offers nothing without an Antrag or when the flow does not answer', async () => {
    const { cmp, api, client } = await setup();
    cmp.onAction('status:cancelled');
    expect(api.setStatus).toHaveBeenCalledWith('o-1', 'cancelled', 1);
    expect(client.transitions).toHaveBeenCalledWith('a-1', { orderStatus: 'cancelled' });
    client.transitions.mockReturnValue(throwError(() => ({ status: 500 })));
    cmp.offered.set([]);
    cmp.setStatus('ordered');
    expect(cmp.offered()).toEqual([]);
    api.setStatus.mockReturnValueOnce(of(order({ applicationId: undefined, status: 'delivered' })));
    client.transitions.mockClear();
    cmp.setStatus('delivered');
    expect(client.transitions).not.toHaveBeenCalled();
  });

  /** §F/finance/orders/002881: a cancel of a Bestellung with bookings asks first. */
  it('asks before the cancel of a Bestellung with bookings', async () => {
    const { cmp, api } = await setup({ first: order({ bookedAmount: '40.00' }) });
    cmp.onAction('status:cancelled');
    expect(cmp.cancelling()?.key).toBe('cancelled');
    expect(cmp.cancelTitle()).toBe('Status „Storniert“ setzen?');
    expect(cmp.cancelLabel()).toBe('Als „Storniert“ markieren');
    expect(cmp.cancelBody()).toMatch(/^Für „Beamer“ sind 40,00\s€ verbucht\. Die Buchungen bleiben bestehen\.$/);
    expect(api.setStatus).not.toHaveBeenCalled();
    cmp.confirmCancel();
    expect(cmp.cancelling()).toBeNull();
    expect(api.setStatus).toHaveBeenCalledWith('o-1', 'cancelled', 1);
  });

  it('says why a status change failed and reads again after a change of another person', async () => {
    const { cmp, api, toast } = await setup();
    const slow = new Subject<Order>();
    api.setStatus.mockReturnValueOnce(slow);
    cmp.setStatus('ordered');
    cmp.setStatus('ordered');
    expect(api.setStatus).toHaveBeenCalledTimes(1);
    slow.error({ error: null });
    expect(cmp.busy()).toBe(false);
    expect(toast).toHaveBeenCalledWith('Die Bestellung konnte nicht gespeichert werden.', 'error');
    expect(api.get).toHaveBeenCalledTimes(1);
    api.setStatus.mockReturnValueOnce(conflict());
    cmp.setStatus('ordered');
    expect(toast).toHaveBeenCalledWith('Die Bestellung wurde inzwischen geändert. Sie ist neu geladen.', 'error');
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  /** §F/finance/orders/002873: the pick of an invoice, and the removal of the link. */
  it('links an invoice from the search and takes the link away again', async () => {
    jest.useFakeTimers();
    const { cmp, api, budget, touched } = await setup();
    cmp.onAction('invoiceLink');
    jest.runOnlyPendingTimers();
    expect(cmp.linking()).toBe(true);
    expect(budget.listInvoicesPaged).toHaveBeenLastCalledWith({ limit: 20 });
    expect(cmp.invoiceRows()).toEqual([
      { id: 'i-1', title: 'R-1', sub: expect.stringMatching(/^Technikhaus · 100,00\s€ · Rechnung offen$/) },
      { id: 'i-2', title: 'Rechnung ohne Nummer', sub: 'Rechnung bezahlt' },
    ]);
    expect(cmp.invoicePick()).toBe('i-1');
    cmp.invoicePick.set('i-2');
    cmp.invoiceSearch.set('R-');
    jest.runOnlyPendingTimers();
    expect(budget.listInvoicesPaged).toHaveBeenLastCalledWith({ q: 'R-', limit: 20 });
    expect(cmp.invoicePick()).toBe('i-2');
    cmp.setInvoice('i-2');
    expect(api.setInvoice).toHaveBeenCalledWith('o-1', 'i-2', 1);
    expect(cmp.linking()).toBe(false);
    expect(cmp.order().invoiceId).toBe('i-2');
    expect(touched).toHaveBeenCalledTimes(1);
    cmp.onAction('invoiceUnlink');
    expect(api.setInvoice).toHaveBeenLastCalledWith('o-1', null, 1);
    expect(cmp.order().invoiceId).toBeNull();
  });

  it('shows an empty invoice list after a failed or empty search and reports a failed link', async () => {
    jest.useFakeTimers();
    const { cmp, api, budget, toast } = await setup({ first: order({ invoiceId: 'i-7', version: undefined }) });
    budget.listInvoicesPaged.mockReturnValueOnce(of({ items: [], total: 0 }));
    cmp.onAction('invoiceLink');
    jest.runOnlyPendingTimers();
    expect(cmp.invoiceRows()).toEqual([]);
    expect(cmp.invoicePick()).toBeNull();
    budget.listInvoicesPaged.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.invoiceSearch.set('xy');
    jest.runOnlyPendingTimers();
    expect(cmp.invoiceRows()).toEqual([]);
    api.setInvoice.mockReturnValueOnce(throwError(() => ({ error: { code: 'invoice_not_found' } })));
    cmp.setInvoice('i-1');
    expect(api.setInvoice).toHaveBeenCalledWith('o-1', 'i-1', 1);
    expect(cmp.linking()).toBe(false);
    expect(toast).toHaveBeenCalledWith('Die Bestellung konnte nicht gespeichert werden.', 'error');
  });

  it('deletes the Bestellung after the question and goes back to the list', async () => {
    const { cmp, api, navigate, touched } = await setup();
    cmp.onAction('delete');
    expect(cmp.deleting()).toBe(true);
    cmp.confirmDelete();
    expect(api.remove).toHaveBeenCalledWith('o-1');
    expect(cmp.deleting()).toBe(false);
    expect(touched).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(['/orders'], { queryParamsHandling: 'preserve' });
  });

  it('says why a delete failed', async () => {
    const { cmp, api, toast } = await setup();
    api.remove.mockReturnValueOnce(throwError(() => ({ error: { code: 'order_has_bookings' } })));
    cmp.confirmDelete();
    expect(toast).toHaveBeenCalledWith('Die Bestellung hat Buchungen. Storniere sie, statt sie zu löschen.', 'error');
    api.remove.mockReturnValueOnce(throwError(() => ({})));
    cmp.confirmDelete();
    expect(toast).toHaveBeenCalledWith('Die Bestellung konnte nicht gelöscht werden.', 'error');
    expect(cmp.busy()).toBe(false);
  });
});
