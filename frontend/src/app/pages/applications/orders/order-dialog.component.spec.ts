import { render, screen } from '@testing-library/angular';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { CalendarApiService } from '@core/api/calendar.service';
import { type Order, OrdersApiService } from '@core/api/orders.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastMock } from '../../../../testing/toast';
import { OrderDialogComponent } from './order-dialog.component';
import { orderPositions } from './orders.util';
import { order } from '../../../../testing/order-fixtures';

const POSITIONS = orderPositions({
  costs: [
    { id: 'p-1', label: 'Beamer', offers: [{ label: 'https://shop.example.org/beamer', value: 100, preferred: true }] },
    { id: 'p-2', label: 'Kabel', offers: [{ label: 'Laden', value: 12.5, preferred: true }] },
    { id: 'p-3', label: 'Leinwand', offers: [{ label: 'Laden', value: 80, preferred: true }] },
  ],
});

async function setup(inputs: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    create: jest.fn(() => of(order({ id: 'o-new' }))),
    update: jest.fn(() => of(order())),
    files: jest.fn(() => of([])),
  };
  const people = jest.fn(() => of([{ id: 'p7', name: 'Lea Hoffmann' }]));
  const toast = toastMock();
  const saved = jest.fn();
  const stale = jest.fn();
  const view = await render(OrderDialogComponent, {
    inputs: { open: true, applicationId: 'a-1', positions: POSITIONS, ...inputs },
    on: { saved, stale },
    providers: [
      { provide: OrdersApiService, useValue: api },
      { provide: ApiClient, useValue: {} },
      { provide: CalendarApiService, useValue: { people } },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const fill = async (value: Record<string, unknown>) => {
    cmp.onValue({ ...cmp.value(), ...value });
    view.fixture.detectChanges();
    await view.fixture.whenStable();
  };
  return { ...view, cmp, api, people, toast, saved, stale, fill };
}

describe('OrderDialogComponent', () => {
  afterEach(() => localStorage.clear());

  /** §F/finance/orders/002861 */
  it('fills the planned price and the link from the picked positions and keeps typed values', async () => {
    const { cmp, fill } = await setup();
    expect(screen.getByRole('heading', { name: 'Bestellung anlegen' })).toBeInTheDocument();
    await fill({ positionIds: ['p-1'] });
    expect(cmp.value().plannedAmount).toBe(100);
    expect(cmp.value().url).toBe('https://shop.example.org/beamer');
    await fill({ positionIds: ['p-1', 'p-2'] });
    expect(cmp.value().plannedAmount).toBe(112.5);
    expect(cmp.value().url).toBe('');

    await fill({ positionIds: ['p-1'] });
    await fill({ plannedAmount: 95, url: 'https://anders.example.org' });
    await fill({ positionIds: ['p-1', 'p-2'] });
    expect(cmp.value().plannedAmount).toBe(95);
    expect(cmp.value().url).toBe('https://anders.example.org');
  });

  it('does not offer a position of another Bestellung and names a removed one', async () => {
    const mine = order({ id: 'o-1', positionIds: ['p-2', 'gone'] });
    const { cmp } = await setup({
      order: mine,
      orders: [mine, order({ id: 'o-2', positionIds: ['p-1'] })],
    });
    expect(screen.getByRole('heading', { name: 'Bestellung bearbeiten' })).toBeInTheDocument();
    const field = cmp.form().sections[0].fields.find((f: { key: string }) => f.key === 'positionIds');
    expect(field.options).toEqual([
      { value: 'p-2', label: 'Kabel' },
      { value: 'p-3', label: 'Leinwand' },
      { value: 'gone', label: 'Entfernte Position' },
    ]);
  });

  it('creates a Bestellung with the picked account as the buyer', async () => {
    const { cmp, api, saved, fill, people } = await setup();
    cmp.findPeople('le').subscribe();
    expect(people).toHaveBeenCalledWith('le');
    await fill({ title: 'Beamer', kind: 'outlay', buyerName: 'Ben' });
    cmp.onPicked({ kind: 'gremium', id: 'g-1', name: 'AStA' });
    expect(cmp.buyer()).toBeNull();
    cmp.onPicked({ kind: 'person', id: 'p7', name: 'Lea Hoffmann' });
    cmp.onAction('save');
    expect(api.create).toHaveBeenCalledWith('a-1', expect.objectContaining({ title: 'Beamer', kind: 'outlay', buyerId: 'p7', buyerName: null }));
    expect(saved).toHaveBeenCalledWith(expect.objectContaining({ id: 'o-new' }));
    expect(cmp.open()).toBe(false);
  });

  it('changes a Bestellung with its version and shows its files and its buyer', async () => {
    const current = order({ version: 4, buyerId: 'p7', buyerLabel: 'Lea Hoffmann' });
    const { cmp, api } = await setup({ order: current });
    expect(api.files).toHaveBeenCalledWith('o-1');
    expect(screen.getByText('Lea Hoffmann')).toBeInTheDocument();
    cmp.save();
    expect(api.update).toHaveBeenCalledWith('o-1', 4, expect.objectContaining({ title: 'Beamer', buyerId: 'p7' }));
  });

  it('does not save without a Bezeichnung, without an Antrag or while a save runs', async () => {
    const { cmp, api, fill, fixture } = await setup({ order: { ...order(), version: undefined, buyerId: 'p7', buyerLabel: undefined } });
    expect(cmp.buyer()).toEqual({ id: 'p7', name: '' });
    await fill({ title: '' });
    cmp.save();
    expect(api.update).not.toHaveBeenCalled();
    await fill({ title: 'Beamer' });
    const pending = new Subject<Order>();
    api.update.mockReturnValueOnce(pending);
    cmp.save();
    cmp.save();
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.update).toHaveBeenCalledWith('o-1', 1, expect.anything());
    pending.error({ error: null });
    fixture.componentRef.setInput('applicationId', null);
    cmp.save();
    expect(api.update).toHaveBeenCalledTimes(1);
  });

  it('puts a refusal of the server at its field, at the buyer or into a toast', async () => {
    const { cmp, api, toast, stale, fill } = await setup();
    await fill({ title: 'Beamer' });
    const refuse = (code: string) => {
      api.create.mockReturnValueOnce(throwError(() => ({ error: { code } })));
      cmp.save();
    };
    refuse('order_url_invalid');
    expect(cmp.errors()).toEqual({ url: 'Der Link muss mit http:// oder https:// beginnen.' });
    refuse('order_buyer_required');
    expect(cmp.buyerError()).toBe('Eine Auslage braucht eine:n Käufer:in.');
    await fill({ note: 'x' });
    expect(cmp.buyerError()).toBe('');
    refuse('application_not_approved');
    expect(toast.error).toHaveBeenCalledWith('Der Antrag ist nicht genehmigt.');
    refuse('boom');
    expect(toast.error).toHaveBeenCalledWith('Die Bestellung konnte nicht gespeichert werden.');
    expect(stale).not.toHaveBeenCalled();
    refuse('order_version_conflict');
    expect(stale).toHaveBeenCalled();
    expect(cmp.open()).toBe(false);
  });

  it('closes on "Abbrechen" and starts empty again', async () => {
    const { cmp, fill, fixture } = await setup();
    await fill({ title: 'Beamer' });
    cmp.onAction('cancel');
    expect(cmp.open()).toBe(false);
    cmp.open.set(true);
    fixture.detectChanges();
    expect(cmp.value().title).toBe('');
  });

  it('shows a person without the right the values and the files, and no form', async () => {
    const { cmp, api } = await setup({
      canManage: false,
      order: order({ url: 'https://shop.example.org', status: 'ordered' }),
    });
    expect(screen.getByRole('heading', { name: 'Beamer' })).toBeInTheDocument();
    expect(screen.getByText('Technikhaus')).toBeInTheDocument();
    expect(screen.getByText('Bestellt')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'https://shop.example.org' })).toHaveAttribute('rel', 'noopener noreferrer');
    expect(document.querySelector('app-form')).toBeNull();
    expect(cmp.actions().map((a: { key: string }) => a.key)).toEqual(['cancel']);
    expect(api.files).toHaveBeenCalledWith('o-1');
    expect(screen.queryByText('Datei hochladen')).not.toBeInTheDocument();
  });

  it('has no values to show without a Bestellung', async () => {
    const { cmp } = await setup({ canManage: false });
    expect(cmp.facts()).toEqual([]);
  });
});
