import { provideTestStatuses } from '@core/api/statuses.service';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { CalendarApiService } from '@core/api/calendar.service';
import type { Application } from '@core/api/models';
import { type Order, type OrderList, OrdersApiService } from '@core/api/orders.service';
import { type FieldDef, ToastService } from '@stupa-makers/ui-kit';
import { NO_ORDER_LIST, order } from '../../../testing/order-fixtures';
import { NO_APPLICATION, OrderFormComponent } from './order-form.component';
import { OrdersRefresh } from './orders-refresh';

const APPLICATION = {
  id: 'a-1',
  currency: 'EUR',
  data: {
    title: 'Technik für den Saal',
    costs: [
      {
        id: 'p-1',
        label: 'Beamer',
        offers: [{ label: 'Angebot https://shop.example.org/beamer', value: 100, preferred: true }],
      },
      { id: 'p-2', label: 'Kabel', offers: [{ label: 'Laden', value: 12.5, preferred: true }] },
      { id: 'p-3', label: 'Leinwand', offers: [{ label: 'Laden', value: 50, preferred: true }] },
    ],
  },
} as unknown as Application;

const LIST: OrderList = {
  ...NO_ORDER_LIST,
  items: [order({ id: 'o-other', positionIds: ['p-3'] }), order({ id: 'o-gone', status: 'cancelled', positionIds: ['p-2'] })],
  total: '100.00',
  approvedAmount: '200.00',
  canManage: true,
  canCreate: true,
};

const refusal = (code?: string) => throwError(() => ({ error: code ? { code } : null }));

interface Options {
  readonly id?: string;
  readonly application?: string;
  readonly first?: Order;
  readonly list?: OrderList;
}

async function setup(options: Options = {}) {
  localStorage.setItem('ap.locale', 'de');
  const first = options.first ?? order({ positionIds: ['p-1', 'gone'], buyerName: 'Ben' });
  const api = {
    get: jest.fn(() => of(first)),
    list: jest.fn(() => of(options.list ?? LIST)),
    pending: jest.fn(() =>
      of({
        items: [
          { id: 'a-1', title: 'Technik', gremiumId: 'g-1', gremiumName: 'StuPa', approvedAmount: '200.00' },
          { id: 'a-2', title: '', gremiumId: null, gremiumName: null, approvedAmount: null },
        ],
        total: 2,
      }),
    ),
    create: jest.fn(() => of(order({ id: 'o-new' }))),
    update: jest.fn((_id: string, _version: number, body: Partial<Order>) => of({ ...first, ...body, version: 2 } as Order)),
  };
  const client = { getApplication: jest.fn(() => of(APPLICATION)) };
  const calendar = { people: jest.fn(() => of([{ id: 'p-9', name: 'Ada' }])) };
  const paramMap = new BehaviorSubject(convertToParamMap(options.id ? { id: options.id } : {}));
  const snapshot = {
    queryParamMap: convertToParamMap(options.application ? { application: options.application } : {}),
  };
  const view = await render(OrderFormComponent, {
    providers: [
      provideTestStatuses(),
      provideRouter([]),
      { provide: OrdersApiService, useValue: api },
      { provide: ApiClient, useValue: client },
      { provide: CalendarApiService, useValue: calendar },
      { provide: ActivatedRoute, useValue: { paramMap, snapshot } },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const injector = view.fixture.debugElement.injector;
  const toast = jest.spyOn(injector.get(ToastService), 'show');
  const navigate = jest.spyOn(injector.get(Router), 'navigate').mockResolvedValue(true);
  const touched = jest.fn();
  injector.get(OrdersRefresh).changed.subscribe(touched);
  const fields = (): readonly FieldDef[] => cmp.form().sections[0].fields;
  const field = (key: string): FieldDef & Record<string, unknown> =>
    fields().find((f) => f.key === key) as FieldDef & Record<string, unknown>;
  return { ...view, cmp, api, client, calendar, paramMap, toast, navigate, touched, fields, field };
}

const LEAVE = { queryParams: { application: null }, queryParamsHandling: 'merge' };

describe('OrderFormComponent', () => {
  afterEach(() => localStorage.clear());

  /** §F/finance/orders/002937: the empty form asks for the Antrag first. */
  it('offers the Anträge that can take a Bestellung in the empty form', async () => {
    const { cmp, api, client, field, fields } = await setup();
    expect(api.pending).toHaveBeenCalledWith({ limit: 200 }, true);
    expect(cmp.title()).toBe('Bestellung anlegen');
    expect(cmp.editing()).toBe(false);
    expect(fields()[0].key).toBe('applicationId');
    expect(field('applicationId')).toMatchObject({
      kind: 'select',
      required: true,
      search: true,
      options: [
        { value: 'none', label: 'Ohne Antrag' },
        { value: 'a-1', label: 'Technik · StuPa' },
        { value: 'a-2', label: 'Ohne Titel' },
      ],
    });
    expect(field('positionIds').visible).toBe(false);
    expect(field('buyerName').visible).toBe(true);
    cmp.save({ title: 'Beamer' });
    expect(api.create).not.toHaveBeenCalled();
    cmp.onValue({ ...cmp.value(), applicationId: 'a-1' });
    expect(client.getApplication).toHaveBeenCalledWith('a-1', { quiet: true });
    expect(api.list).toHaveBeenCalledWith('a-1');
    cmp.onValue({ ...cmp.value(), title: 'Beamer' });
    expect(client.getApplication).toHaveBeenCalledTimes(1);
    expect(field('positionIds')).toMatchObject({
      visible: true,
      options: [
        { value: 'p-1', label: 'Beamer' },
        { value: 'p-2', label: 'Kabel' },
      ],
    });
    cmp.save(cmp.value());
    expect(api.create).toHaveBeenCalledWith('a-1', expect.objectContaining({ title: 'Beamer', kind: 'order', buyerId: null }));
    expect(screen.getByRole('heading', { name: 'Bestellung anlegen' })).toBeInTheDocument();
  });

  /** §F/finance/orders/003014: "Ohne Antrag" is a choice of the person and has no positions. */
  it('saves a Bestellung without an Antrag after the choice "Ohne Antrag"', async () => {
    const { cmp, api, client, field, navigate } = await setup();
    expect(cmp.value()['applicationId'] ?? '').toBe('');
    cmp.onValue({ ...cmp.value(), applicationId: 'a-1' });
    cmp.onValue({ ...cmp.value(), positionIds: ['p-1'] });
    expect(cmp.value()).toMatchObject({ plannedAmount: 100 });
    cmp.onValue({ ...cmp.value(), applicationId: NO_APPLICATION, title: 'Altkauf' });
    expect(cmp.value()['positionIds']).toEqual([]);
    expect(field('positionIds').visible).toBe(false);
    expect(field('sum')).toBeUndefined();
    cmp.save(cmp.value());
    expect(api.create).toHaveBeenCalledWith(null, expect.objectContaining({ title: 'Altkauf', positionIds: [] }));
    expect(navigate).toHaveBeenCalledWith(['/orders', 'o-new'], LEAVE);
    cmp.onValue({ ...cmp.value(), applicationId: 'a-1' });
    expect(client.getApplication).toHaveBeenCalledTimes(2);
  });

  it('leaves the choice empty when the Anträge do not load', async () => {
    const view = await setup();
    view.api.pending.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    view.paramMap.next(convertToParamMap({}));
    expect(view.field('applicationId').options).toHaveLength(3);
  });

  /** §F/finance/orders/002937: `?application=<id>` fixes the Antrag, and the save creates for it. */
  it('saves a new Bestellung for the Antrag of the address and opens it', async () => {
    const { cmp, api, field, fields, navigate, touched } = await setup({ application: 'a-1' });
    expect(api.pending).not.toHaveBeenCalled();
    expect(fields()[0]).toMatchObject({ key: 'applicationName', kind: 'display', text: 'Technik für den Saal' });
    expect(field('applicationId')).toBeUndefined();
    cmp.setBuyer({ id: 'p-9', name: 'Ada' });
    expect(api.update).not.toHaveBeenCalled();
    expect(field('buyerName').visible).toBe(false);
    cmp.save({ ...cmp.value(), title: ' Beamer ', plannedAmount: 100, buyerName: 'Ben' });
    expect(api.create).toHaveBeenCalledWith(
      'a-1',
      expect.objectContaining({ title: 'Beamer', plannedAmount: '100.00', buyerId: 'p-9', buyerName: null }),
    );
    expect(cmp.saving()).toBe(false);
    expect(touched).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(['/orders', 'o-new'], LEAVE);
  });

  /** §F/finance/orders/002861: the picked positions fill the planned price and the link. */
  it('fills the price and the link from the picked positions and keeps what the person typed', async () => {
    const { cmp } = await setup({ application: 'a-1' });
    cmp.onValue({ ...cmp.value(), positionIds: ['p-1'] });
    expect(cmp.value()).toMatchObject({ plannedAmount: 100, url: 'https://shop.example.org/beamer' });
    cmp.onValue({ ...cmp.value(), positionIds: ['p-1', 'p-2'] });
    expect(cmp.value()).toMatchObject({ plannedAmount: 112.5, url: '' });
    cmp.onValue({ ...cmp.value(), plannedAmount: 99, url: 'https://own.example.org' });
    cmp.onValue({ ...cmp.value(), positionIds: ['p-2'] });
    expect(cmp.value()).toMatchObject({ plannedAmount: 99, url: 'https://own.example.org' });
    cmp.onValue({ ...cmp.value(), plannedAmount: '', url: '', positionIds: undefined });
    expect(cmp.value()).toMatchObject({ plannedAmount: null, url: '' });
    cmp.onValue({ ...cmp.value(), plannedAmount: undefined, positionIds: ['p-1'] });
    expect(cmp.value()).toMatchObject({ plannedAmount: 100 });
  });

  /** §F/finance/orders/002868: the sum and its warning stand in the detail, not in the form. */
  it('shows no sum of the Antrag in the form', async () => {
    const { field } = await setup({ application: 'a-1', list: { ...LIST, total: '212.50', overBy: '12.50' } });
    expect(field('sum')).toBeUndefined();
  });

  it('opens an existing Bestellung with its values, its removed position and its buyer', async () => {
    const first = order({ positionIds: ['p-1', 'gone'], buyerId: 'p-9', buyerLabel: 'Ada', version: undefined });
    const { cmp, api, field, fields, touched, navigate } = await setup({ id: 'o-1', application: 'ignored', first });
    expect(api.get).toHaveBeenCalledWith('o-1');
    expect(cmp.title()).toBe('Bestellung bearbeiten');
    expect(fields()[0].key).toBe('title');
    expect(cmp.value()).toMatchObject({ title: 'Beamer', positionIds: ['p-1', 'gone'], plannedAmount: 100 });
    expect(cmp.buyer()).toEqual({ id: 'p-9', name: 'Ada' });
    expect(field('positionIds').options).toEqual([
      { value: 'p-1', label: 'Beamer' },
      { value: 'p-2', label: 'Kabel' },
      { value: 'gone', label: 'Entfernte Position' },
    ]);
    cmp.onValue({ ...cmp.value(), applicationId: 'a-2', title: 'Beamer neu' });
    expect(api.list).toHaveBeenCalledTimes(1);
    cmp.save(cmp.value());
    expect(api.update).toHaveBeenCalledWith('o-1', 1, expect.objectContaining({ title: 'Beamer neu', buyerId: 'p-9' }));
    expect(api.create).not.toHaveBeenCalled();
    expect(touched).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(['/orders', 'o-1'], LEAVE);
    cmp.close();
    expect(navigate).toHaveBeenLastCalledWith(['/orders', 'o-1'], LEAVE);
  });

  it('opens a Bestellung without account and without Antrag', async () => {
    const { cmp, api } = await setup({ id: 'o-1', first: order({ applicationId: undefined, buyerId: 'p-9', buyerLabel: null }) });
    expect(cmp.buyer()).toEqual({ id: 'p-9', name: '' });
    expect(api.list).not.toHaveBeenCalled();
    cmp.save(cmp.value());
    expect(api.update).toHaveBeenCalledWith('o-1', 1, expect.objectContaining({ buyerId: 'p-9' }));
  });

  /** The pick of an account in the form of an existing Bestellung saves at once. */
  it('saves the account of the buyer at once in an existing Bestellung', async () => {
    const { cmp, api, touched, toast } = await setup({ id: 'o-1' });
    expect(cmp.buyer()).toBeNull();
    cmp.onPicked({ kind: 'gremium', id: 'g-1', name: 'StuPa', logoUrl: null });
    expect(api.update).not.toHaveBeenCalled();
    cmp.onPicked({ kind: 'person', id: 'p-9', name: 'Ada' });
    expect(api.update).toHaveBeenCalledWith('o-1', 1, { buyerId: 'p-9' });
    expect(cmp.buyer()).toEqual({ id: 'p-9', name: 'Ada' });
    expect(cmp.order().version).toBe(2);
    expect(touched).toHaveBeenCalledTimes(1);
    cmp.setBuyer(null);
    expect(api.update).toHaveBeenLastCalledWith('o-1', 2, { buyerId: null });
    api.update.mockReturnValueOnce(refusal('order_buyer_required'));
    cmp.setBuyer({ id: 'p-9', name: 'Ada' });
    expect(cmp.buyer()).toBeNull();
    expect(cmp.buyerError()).toBe('Eine Auslage braucht eine:n Käufer:in.');
    expect(cmp.errors()).toEqual({ buyerName: 'Eine Auslage braucht eine:n Käufer:in.' });
    api.update.mockReturnValueOnce(refusal());
    cmp.setBuyer({ id: 'p-9', name: 'Ada' });
    expect(toast).toHaveBeenCalledWith('Die Bestellung konnte nicht gespeichert werden.', 'error');
    cmp.onValue(cmp.value());
    expect(cmp.buyerError()).toBe('');
    expect(cmp.errors()).toEqual({});
  });

  it('searches the accounts through the calendar', async () => {
    const { cmp, calendar } = await setup();
    cmp.findPeople('ad').subscribe();
    expect(calendar.people).toHaveBeenCalledWith('ad');
  });

  it('shows each refusal of the server at its field or as a toast', async () => {
    const { cmp, api, toast, navigate } = await setup({ application: 'a-1' });
    const refuse = (code?: string) => {
      api.create.mockReturnValueOnce(refusal(code));
      cmp.save(cmp.value());
    };
    refuse('order_url_invalid');
    expect(cmp.errors()).toEqual({ url: 'Der Link muss mit http:// oder https:// beginnen.' });
    expect(cmp.saving()).toBe(false);
    refuse('order_title_required');
    expect(cmp.errors()).toEqual({ title: 'Die Bezeichnung fehlt.' });
    refuse('order_position_taken');
    expect(cmp.errors()).toEqual({ positionIds: 'Eine Position gehört schon zu einer anderen Bestellung.' });
    refuse('order_position_unknown');
    expect(cmp.errors()).toEqual({ positionIds: 'Eine Position gibt es im Antrag nicht mehr.' });
    refuse('order_buyer_unknown');
    expect(cmp.buyerError()).toBe('Eine Auslage braucht eine:n Käufer:in.');
    refuse('application_not_approved');
    expect(toast).toHaveBeenLastCalledWith('Der Antrag ist nicht genehmigt.', 'error');
    refuse('application_type_without_budget');
    expect(toast).toHaveBeenLastCalledWith('Diese Antragsart hat keinen Betrag.', 'error');
    refuse();
    expect(toast).toHaveBeenLastCalledWith('Die Bestellung konnte nicht gespeichert werden.', 'error');
    expect(navigate).not.toHaveBeenCalled();
    refuse('order_version_conflict');
    expect(toast).toHaveBeenLastCalledWith('Die Bestellung wurde inzwischen geändert. Sie ist neu geladen.', 'error');
    expect(navigate).toHaveBeenCalledWith(['/orders'], LEAVE);
  });

  it('sends one save at a time', async () => {
    const { cmp, api } = await setup({ application: 'a-1' });
    const slow = new Subject<Order>();
    api.create.mockReturnValueOnce(slow);
    cmp.save(cmp.value());
    cmp.save(cmp.value());
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(cmp.saving()).toBe(true);
  });

  it('goes back to the list when the Bestellung does not load, and drops the answers of an older Antrag', async () => {
    const { cmp, api, client, paramMap, toast, navigate } = await setup({ application: 'a-1' });
    const apps = new Subject<Application>();
    const lists = new Subject<OrderList>();
    client.getApplication.mockReturnValueOnce(apps);
    api.list.mockReturnValueOnce(lists);
    api.get.mockReturnValueOnce(of(order({ applicationId: 'a-5' })));
    paramMap.next(convertToParamMap({ id: 'o-1' }));
    client.getApplication.mockReturnValueOnce(throwError(() => ({ status: 403 })));
    api.list.mockReturnValueOnce(throwError(() => ({ status: 403 })));
    api.get.mockReturnValueOnce(of(order({ applicationId: 'a-6' })));
    paramMap.next(convertToParamMap({ id: 'o-2' }));
    apps.next(APPLICATION);
    lists.next(LIST);
    expect(cmp.form().sections[0].fields.find((f: FieldDef) => f.key === 'positionIds').visible).toBe(false);
    api.get.mockReturnValueOnce(throwError(() => ({ status: 404 })));
    paramMap.next(convertToParamMap({ id: 'o-3' }));
    expect(toast).toHaveBeenCalledWith('Die Bestellung konnte nicht geladen werden.', 'error');
    expect(navigate).toHaveBeenCalledWith(['/orders'], LEAVE);
  });
});
