import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { CalendarApiService } from '@core/api/calendar.service';
import { type Order, type OrderList, OrdersApiService } from '@core/api/orders.service';
import { Router } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { BudgetTreeApi, type Invoice } from '../../budget/budget-tree.api';
import { toastMock } from '../../../../testing/toast';
import { OrdersSectionComponent } from './orders-section.component';
import { order } from '../../../../testing/order-fixtures';

const list = (over: Partial<OrderList> = {}): OrderList => ({
  items: [
    order({ id: 'o-1', title: 'Beamer', plannedAmount: '100.00', actualAmount: '112.50', status: 'delivered' }),
    order({ id: 'o-2', title: 'Kabel', supplier: null, kind: 'outlay', plannedAmount: '20.00', version: 3 }),
  ],
  total: '132.50',
  approvedAmount: '150.00',
  overBy: null,
  canManage: true,
  canCreate: true,
  ...over,
});

const INVOICES = [
  { id: 'i-1', number: 'R-17', supplier: 'Technikhaus', grossAmount: '112.50', status: 'open' },
  { id: 'i-2', number: null, supplier: null, grossAmount: '9.00', status: 'paid' },
] as unknown as Invoice[];

async function setup(
  answer: OrderList | null = list(),
  inputs: Record<string, unknown> = {},
  perms: readonly string[] = [],
) {
  localStorage.setItem('ap.locale', 'de');
  const router = { navigate: jest.fn(() => Promise.resolve(true)) };
  const budget = {
    listInvoicesPaged: jest.fn(() => of({ items: INVOICES, total: 2, limit: 20, offset: 0 })),
  };
  const auth = {
    can: (perm: string) => perms.includes(perm),
    canAny: (...wanted: string[]) => wanted.some((perm) => perms.includes(perm)),
  };
  const api = {
    setInvoice: jest.fn(() => of(order())),
    list: jest.fn(() => (answer ? of(answer) : throwError(() => ({ status: 500 })))),
    setStatus: jest.fn(() => of(order())),
    remove: jest.fn(() => of(undefined)),
    files: jest.fn(() => of([])),
  };
  const toast = toastMock();
  const changed = jest.fn();
  const view = await render(OrdersSectionComponent, {
    inputs: { applicationId: 'a-1', hasBudget: true, currency: 'EUR', ...inputs },
    on: { changed },
    providers: [
      { provide: OrdersApiService, useValue: api },
      { provide: ApiClient, useValue: {} },
      { provide: CalendarApiService, useValue: { people: () => of([]) } },
      { provide: ToastService, useValue: toast },
      { provide: Router, useValue: router },
      { provide: BudgetTreeApi, useValue: budget },
      { provide: AuthService, useValue: auth },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  return { ...view, cmp, api, toast, changed, router, budget };
}

describe('OrdersSectionComponent', () => {
  afterEach(() => localStorage.clear());

  /** §F/finance/orders/002869 */
  it('shows the rows with the price, the difference, the sum line and a heading without a count', async () => {
    const { api, fixture } = await setup();
    expect(api.list).toHaveBeenCalledWith('a-1');
    expect(fixture.nativeElement).not.toHaveAttribute('hidden');
    expect(screen.getByRole('heading', { name: 'Bestellungen' })).toHaveTextContent(/^\s*Bestellungen\s*$/);
    const rows = [...document.querySelectorAll('[data-testid="os-row"]')].map((r) =>
      (r.textContent ?? '').replace(/\s+/g, ' ').trim(),
    );
    expect(rows[0]).toContain('Beamer');
    expect(rows[0]).toContain('Technikhaus');
    expect(rows[0]).toContain('Geliefert');
    expect(rows[0]).toMatch(/112,50\s€/);
    expect(rows[0]).toMatch(/\+12,50\s€/);
    expect(rows[0]).not.toContain('geplant');
    expect(rows[1]).toContain('Auslage');
    expect(rows[1]).toContain('Preis geplant');
    expect(rows[1]).toMatch(/20,00\s€/);
    expect(screen.getByTestId('os-sum')).toHaveTextContent(/Summe\s*132,50\s€ von 150,00\s€ genehmigt/);
  });

  /** §F/finance/orders/002868 */
  it('warns above the approved amount and not at the approved amount', async () => {
    await setup(list({ total: '162.50', overBy: '12.50' }));
    expect(screen.getByRole('status')).toHaveTextContent(/Die Summe liegt 12,50\s€ über dem genehmigten Betrag\./);
  });

  /** §F/finance/orders/002868 */
  it('does not warn at the approved amount', async () => {
    await setup(list({ total: '150.00', overBy: null }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('shows for a type with money without a Bestellung', async () => {
    await setup(list({ items: [], total: '0.00', canCreate: false }));
    expect(screen.getByText('Noch keine Bestellungen')).toBeInTheDocument();
    expect(screen.queryByTestId('os-new')).not.toBeInTheDocument();
    expect(screen.queryByTestId('os-sum')).not.toBeInTheDocument();
  });

  it('does not show for a type without money and without a Bestellung', async () => {
    const { fixture } = await setup(list({ items: [] }), { hasBudget: false });
    expect(screen.queryByRole('heading', { name: 'Bestellungen' })).not.toBeInTheDocument();
    expect(fixture.nativeElement).toHaveAttribute('hidden');
  });

  it('stays away while the list is not there', async () => {
    await setup(null);
    expect(screen.queryByRole('heading', { name: 'Bestellungen' })).not.toBeInTheDocument();
  });

  /** §F/finance/orders/002864 */
  it('shows the applicant view without a price, a sum and a menu', async () => {
    const { cmp } = await setup(
      list({
        items: [{ id: 'o-1', number: 'B-1', title: 'Beamer', kind: 'order', status: 'ordered', orderedOn: null, deliveredOn: null }],
        total: null,
        approvedAmount: null,
        canManage: false,
        canCreate: false,
      }),
      { hasBudget: false },
    );
    expect(screen.getByText('Bestellt')).toBeInTheDocument();
    expect(cmp.rows()[0]).toMatchObject({ price: '', sub: [], menu: [] });
    expect(document.querySelector('app-row-menu')).toBeNull();
    expect(screen.queryByTestId('os-sum')).not.toBeInTheDocument();
  });

  it('gives the sum alone without an approved amount', async () => {
    await setup(list({ approvedAmount: null }));
    expect(screen.getByTestId('os-sum')).toHaveTextContent(/^\s*Summe\s*132,50\s€\s*$/);
  });

  it('opens the form for a new Bestellung and for a row, and reads again after a save', async () => {
    const { cmp, api, changed } = await setup();
    await userEvent.click(screen.getByTestId('os-new'));
    expect(cmp.dialogOpen()).toBe(true);
    expect(cmp.editing()).toBeNull();
    cmp.dialogOpen.set(false);
    await userEvent.click(screen.getByRole('button', { name: 'Kabel' }));
    expect(cmp.editing().id).toBe('o-2');
    cmp.onChanged();
    expect(api.list).toHaveBeenCalledTimes(2);
    expect(changed).toHaveBeenCalledTimes(1);
  });

  /** §F/finance/orders/002870 */
  it('sets a status from the menu with the version of the row', async () => {
    const { cmp, api, changed, toast } = await setup();
    const kabel = cmp.items()[1] as Order;
    cmp.onMenu(kabel, 'ordered');
    expect(api.setStatus).toHaveBeenCalledWith('o-2', 'ordered', 3);
    expect(changed).toHaveBeenCalledTimes(1);
    cmp.onMenu({ ...kabel, version: undefined }, 'cancelled');
    expect(api.setStatus).toHaveBeenLastCalledWith('o-2', 'cancelled', 1);
    cmp.onMenu(kabel, 'edit');
    expect(cmp.editing().id).toBe('o-2');

    api.setStatus.mockReturnValueOnce(throwError(() => ({ error: { code: 'order_version_conflict' } })));
    cmp.onMenu(kabel, 'delivered');
    expect(toast.error).toHaveBeenCalledWith('Die Bestellung wurde inzwischen geändert. Sie ist neu geladen.');
    expect(api.list).toHaveBeenCalledTimes(4);
    api.setStatus.mockReturnValueOnce(throwError(() => ({ error: null })));
    cmp.onMenu(kabel, 'delivered');
    expect(toast.error).toHaveBeenCalledWith('Die Bestellung konnte nicht gespeichert werden.');
    expect(api.list).toHaveBeenCalledTimes(4);

    const pending = new Subject<Order>();
    api.setStatus.mockReturnValueOnce(pending);
    cmp.onMenu(kabel, 'delivered');
    cmp.onMenu(kabel, 'ordered');
    expect(api.setStatus).toHaveBeenCalledTimes(5);
  });

  it('asks before the delete', async () => {
    const { cmp, api, changed, toast } = await setup();
    cmp.confirmDelete();
    expect(api.remove).not.toHaveBeenCalled();
    cmp.onMenu(cmp.items()[0], 'delete');
    expect(cmp.deleting().id).toBe('o-1');
    expect(api.remove).not.toHaveBeenCalled();
    cmp.confirmDelete();
    expect(api.remove).toHaveBeenCalledWith('o-1');
    expect(cmp.deleting()).toBeNull();
    expect(changed).toHaveBeenCalledTimes(1);

    api.remove.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.deleting.set(cmp.items()[0]);
    cmp.confirmDelete();
    expect(toast.error).toHaveBeenCalledWith('Die Bestellung konnte nicht gelöscht werden.');

    const pending = new Subject<undefined>();
    api.remove.mockReturnValueOnce(pending);
    cmp.deleting.set(cmp.items()[0]);
    cmp.confirmDelete();
    cmp.confirmDelete();
    expect(api.remove).toHaveBeenCalledTimes(3);
  });

  it('drops the answer of an Antrag that is no longer shown', async () => {
    const first = new Subject<OrderList>();
    const { cmp, api, fixture } = await setup();
    api.list.mockReturnValueOnce(first);
    fixture.componentRef.setInput('applicationId', 'a-2');
    fixture.detectChanges();
    fixture.componentRef.setInput('applicationId', 'a-3');
    fixture.detectChanges();
    first.next(list({ items: [] }));
    expect(cmp.items()).toHaveLength(2);
  });

  /** §F/finance/orders/002880 */
  it('shows the marks of the invoice and of the bookings in the row', async () => {
    const { cmp } = await setup(
      list({
        items: [
          order({ id: 'o-1', invoiceId: 'i-1', invoiceStatus: 'open', bookedAmount: '40.00' }),
          order({ id: 'o-2', invoiceId: 'i-2', invoiceStatus: 'paid' }),
        ],
      }),
    );
    expect(cmp.rows()[0].sub.slice(-2)).toEqual(['Rechnung offen', expect.stringMatching(/^Verbucht 40,00\s€$/)]);
    expect(cmp.rows()[1].sub.slice(-1)).toEqual(['Rechnung bezahlt']);
    expect(document.querySelectorAll('[data-testid="os-row"]')[0]).toHaveTextContent('Rechnung offen');
  });

  /** §F/finance/orders/002870 */
  it.each([
    [[], 1, ['ordered', 'delivered', 'edit', 'cancelled', 'delete']],
    [['budget.view'], 1, ['ordered', 'delivered', 'invoiceLink', 'edit', 'cancelled', 'delete']],
    [['budget.book'], 0, ['ordered', 'invoiceLink', 'invoiceNew', 'booking', 'edit', 'cancelled', 'delete']],
  ] as const)('offers the invoice and the booking entries by the rights %j', async (perms, row, ids) => {
    const { cmp } = await setup(list(), {}, perms);
    const menu = cmp.rows()[row].menu as { items: { id: string }[] }[];
    expect(menu.flatMap((section) => section.items.map((item) => item.id))).toEqual(ids);
  });

  /** §F/finance/orders/002876 + §F/finance/orders/002879 */
  it('opens the invoice form and the booking form with the Bestellung', async () => {
    const { cmp, router } = await setup();
    cmp.onMenu(cmp.items()[0], 'invoiceNew');
    expect(router.navigate).toHaveBeenLastCalledWith(['/invoices'], {
      queryParams: { new: 'invoice', order: 'o-1' },
    });
    cmp.onMenu(cmp.items()[0], 'booking');
    expect(router.navigate).toHaveBeenLastCalledWith(['/expenses'], {
      queryParams: { new: 'booking', order: 'o-1' },
    });
  });

  /** §F/finance/orders/002873 */
  it('picks an invoice for a Bestellung in a dialog', async () => {
    jest.useFakeTimers();
    const { cmp, api, budget, changed, toast } = await setup();
    const kabel = cmp.items()[1] as Order;
    cmp.linkInvoice('i-1');
    expect(api.setInvoice).not.toHaveBeenCalled();
    cmp.onMenu(kabel, 'invoiceLink');
    jest.advanceTimersByTime(300);
    expect(cmp.linking().id).toBe('o-2');
    expect(budget.listInvoicesPaged).toHaveBeenCalledWith({ limit: 20 });
    expect(cmp.invoiceRows()).toEqual([
      { id: 'i-1', title: 'R-17', sub: expect.stringMatching(/^Technikhaus · 112,50\s€ · Rechnung offen$/) },
      { id: 'i-2', title: 'Rechnung ohne Nummer', sub: expect.stringMatching(/^9,00\s€ · Rechnung bezahlt$/) },
    ]);
    expect(cmp.invoicePick()).toBe('i-1');
    cmp.invoiceSearch.set('R-17');
    jest.advanceTimersByTime(300);
    expect(budget.listInvoicesPaged).toHaveBeenLastCalledWith({ q: 'R-17', limit: 20 });
    budget.listInvoicesPaged.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.invoiceSearch.set('R-18');
    jest.advanceTimersByTime(300);
    expect(cmp.invoiceRows()).toEqual([]);
    jest.useRealTimers();

    cmp.linkInvoice('i-2');
    expect(api.setInvoice).toHaveBeenCalledWith('o-2', 'i-2', 3);
    expect(cmp.linking()).toBeNull();
    expect(changed).toHaveBeenCalledTimes(1);

    cmp.onMenu({ ...kabel, version: undefined, invoiceId: 'i-2' }, 'invoiceLink');
    expect(cmp.invoicePick()).toBe('i-2');
    api.setInvoice.mockReturnValueOnce(throwError(() => ({ error: { code: 'order_version_conflict' } })));
    cmp.linkInvoice('i-1');
    expect(api.setInvoice).toHaveBeenLastCalledWith('o-2', 'i-1', 1);
    expect(toast.error).toHaveBeenCalledWith('Die Bestellung wurde inzwischen geändert. Sie ist neu geladen.');
    expect(cmp.linking()).toBeNull();

    budget.listInvoicesPaged.mockReturnValueOnce(of({ items: [], total: 0, limit: 20, offset: 0 }));
    cmp.onMenu(kabel, 'invoiceLink');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(cmp.invoiceRows()).toEqual([]);
    expect(cmp.invoicePick()).toBeNull();

    const pending = new Subject<Order>();
    api.setInvoice.mockReturnValueOnce(pending);
    cmp.onMenu(kabel, 'invoiceLink');
    cmp.linkInvoice('i-1');
    cmp.linkInvoice('i-1');
    expect(api.setInvoice).toHaveBeenCalledTimes(3);
  });

  /** §F/finance/orders/002881 */
  it('asks before the cancel of a booked Bestellung and keeps the bookings', async () => {
    const booked = order({ id: 'o-9', title: 'Regal', bookedAmount: '60.00', version: 2 });
    const { cmp, api } = await setup(list({ items: [booked] }));
    expect(cmp.cancelBody()).toBe('');
    cmp.confirmCancel();
    expect(api.setStatus).not.toHaveBeenCalled();
    cmp.onMenu(booked, 'cancelled');
    expect(api.setStatus).not.toHaveBeenCalled();
    expect(cmp.cancelBody()).toMatch(/^Für „Regal“ sind 60,00\s€ verbucht\. Die Buchungen bleiben bestehen\.$/);
    cmp.confirmCancel();
    expect(api.setStatus).toHaveBeenCalledWith('o-9', 'cancelled', 2);
    expect(cmp.cancelling()).toBeNull();
  });

  /** §F/finance/orders/002878 */
  it('says that a Bestellung with a booking cannot be deleted', async () => {
    const { cmp, api, toast } = await setup();
    api.remove.mockReturnValueOnce(throwError(() => ({ error: { code: 'order_has_bookings' } })));
    cmp.deleting.set(cmp.items()[0]);
    cmp.confirmDelete();
    expect(toast.error).toHaveBeenCalledWith('Die Bestellung hat Buchungen. Storniere sie, statt sie zu löschen.');
  });
});
