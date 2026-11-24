import { order } from '../../../testing/order-fixtures';
import {
  amountText,
  firstAddress,
  orderBody,
  orderFacts,
  orderFormValue,
  bookingPayee,
  bookingRest,
  orderMarks,
  orderPositions,
  positionPrefill,
  priceDifference,
  shownPrice,
  takenPositions,
} from './orders.util';

const t = (key: string): string => key;

const DATA = {
  title: 'Technik',
  tags: ['a', 'b'],
  costs: [
    {
      id: 'p-1',
      label: 'Beamer',
      offers: [
        { label: 'Angebot https://shop.example.org/beamer?x=1 inkl. Versand', value: 100, preferred: true },
        { label: 'teurer', value: 140, preferred: false },
      ],
    },
    { id: 'p-2', label: 'Kabel', offers: [{ label: 'Laden', value: 12.5, preferred: true }] },
    { label: 'ohne Id', offers: [] },
  ],
};

describe('orders.util', () => {
  it('finds the positions with an id in the answers of any form', () => {
    expect(orderPositions(DATA).map((p) => p.id)).toEqual(['p-1', 'p-2']);
    expect(orderPositions(null)).toEqual([]);
    expect(orderPositions({ list: [1, 2] })).toEqual([]);
  });

  it('shows the real price, else the planned one, and the difference of both', () => {
    expect(shownPrice(order())).toEqual({ amount: 100, planned: true });
    expect(shownPrice(order({ actualAmount: '112.50' }))).toEqual({ amount: 112.5, planned: false });
    expect(shownPrice({})).toEqual({ amount: null, planned: true });
    expect(priceDifference(order({ actualAmount: '112.50' }))).toBe(12.5);
    expect(priceDifference(order({ actualAmount: '90.00' }))).toBe(-10);
    expect(priceDifference(order({ actualAmount: '100.00' }))).toBeNull();
    expect(priceDifference(order())).toBeNull();
    expect(priceDifference(order({ plannedAmount: null, actualAmount: '5.00' }))).toBeNull();
  });

  /** §F/finance/orders/002861 */
  it('fills the sum of the preferred offers, and the first address with exactly one position', () => {
    const positions = orderPositions(DATA);
    expect(firstAddress('kein Link')).toBeNull();
    expect(positionPrefill([])).toEqual({ plannedAmount: null, url: '' });
    expect(positionPrefill([positions[0]])).toEqual({
      plannedAmount: 100,
      url: 'https://shop.example.org/beamer?x=1',
    });
    expect(positionPrefill([positions[1]])).toEqual({ plannedAmount: 12.5, url: '' });
    expect(positionPrefill(positions)).toEqual({ plannedAmount: 112.5, url: '' });
  });

  it('holds the positions of the other Bestellungen that are not cancelled', () => {
    const orders = [
      order({ id: 'o-1', positionIds: ['p-1'] }),
      order({ id: 'o-2', positionIds: ['p-2'], status: 'cancelled' }),
      order({ id: 'o-3', positionIds: ['p-3'] }),
      order({ id: 'o-4', positionIds: undefined }),
    ];
    expect([...takenPositions(orders, 'o-1')]).toEqual(['p-3']);
    expect([...takenPositions(orders, null)]).toEqual(['p-1', 'p-3']);
  });

  it('builds the body of the API from the form and reads a Bestellung into the form', () => {
    expect(amountText(12.5)).toBe('12.50');
    expect(amountText('')).toBeNull();
    expect(amountText(null)).toBeNull();
    const value = {
      title: ' Beamer ',
      kind: 'outlay',
      supplier: ' ',
      url: 'https://shop.example.org',
      positionIds: ['p-1'],
      plannedAmount: 100,
      actualAmount: null,
      orderedOn: '2026-11-20',
      buyerName: ' Ben ',
      note: '',
    };
    expect(orderBody(value, null)).toEqual({
      title: 'Beamer',
      kind: 'outlay',
      supplier: null,
      url: 'https://shop.example.org',
      orderNumber: null,
      positionIds: ['p-1'],
      plannedAmount: '100.00',
      actualAmount: null,
      orderedOn: '2026-11-20',
      deliveredOn: null,
      buyerId: null,
      buyerName: 'Ben',
      note: null,
    });
    expect(orderBody({ kind: 'x', buyerName: 'Ben' }, 'p-9')).toMatchObject({
      title: '',
      kind: 'order',
      positionIds: [],
      buyerId: 'p-9',
      buyerName: null,
    });
    expect(orderFormValue(null)).toMatchObject({ title: '', kind: 'order', positionIds: [], plannedAmount: null });
    expect(orderFormValue(order({ buyerName: 'Ben', positionIds: ['p-1'] }))).toMatchObject({
      title: 'Beamer',
      supplier: 'Technikhaus',
      positionIds: ['p-1'],
      plannedAmount: 100,
      buyerName: 'Ben',
    });
    expect(orderFormValue(order({ buyerId: 'p-9', buyerName: 'Ben' }))['buyerName']).toBe('');
    expect(orderFormValue({ ...order(), supplier: undefined, positionIds: undefined })).toMatchObject({
      supplier: '',
      positionIds: [],
    });
  });

  it('lists the values of a Bestellung for a reader and leaves out the empty ones', () => {
    const full = order({
      kind: 'outlay',
      status: 'delivered',
      url: 'https://shop.example.org',
      positionIds: ['p-1', 'gone'],
      actualAmount: '112.50',
      orderNumber: 'A-1',
      orderedOn: '2026-11-20',
      deliveredOn: '2026-11-22',
      buyerLabel: 'Anna B.',
      note: 'eilig',
      bookedAmount: '40.00',
    });
    const facts = orderFacts(full, orderPositions(DATA), 'de-DE', 'EUR', t);
    expect(facts.map((f) => f.label)).toEqual([
      'orders.field.number',
      'orders.field.kind',
      'orders.field.status',
      'orders.field.supplier',
      'orders.field.positions',
      'orders.field.url',
      'orders.field.planned',
      'orders.field.actual',
      'orders.field.orderNumber',
      'orders.field.orderedOn',
      'orders.field.deliveredOn',
      'orders.field.buyer',
      'orders.field.note',
      'orders.field.booked',
    ]);
    expect(facts[13].value).toBe('40,00\u00a0€');
    expect(facts[4].value).toBe('Beamer, orders.position.removed');
    expect(facts[5]).toMatchObject({ href: 'https://shop.example.org' });
    expect(facts[7].value).toBe('112,50\u00a0€');
    expect(facts[9].value).toBe('20.11.2026');
    const bare = orderFacts({ ...order(), supplier: undefined, plannedAmount: undefined, positionIds: undefined }, [], 'de-DE', null, t);
    expect(bare.map((f) => f.label)).toEqual(['orders.field.number', 'orders.field.kind', 'orders.field.status']);
  });

  /** §F/finance/orders/002880 */
  it('names the marks of the invoice and of the bookings', () => {
    const tp = (key: string, params?: Record<string, string>) => `${key}${params ? `:${params['amount']}` : ''}`;
    expect(orderMarks(order(), 'de-DE', 'EUR', tp)).toEqual([]);
    expect(orderMarks(order({ invoiceStatus: 'open' }), 'de-DE', 'EUR', tp)).toEqual(['orders.mark.invoiceOpen']);
    const marks = orderMarks(order({ invoiceStatus: 'paid', bookedAmount: '60.00' }), 'de-DE', null, tp);
    expect(marks[0]).toBe('orders.mark.invoicePaid');
    expect(marks[1]).toMatch(/^orders\.mark\.booked:60,00\s€$/);
  });

  /** §F/finance/orders/002879 */
  it('gives the rest amount and the payee of a booking for a Bestellung', () => {
    expect(bookingRest(order({ plannedAmount: '100.00', actualAmount: '112.50', bookedAmount: '40.00' }))).toBe(72.5);
    expect(bookingRest(order({ plannedAmount: '100.00', bookedAmount: undefined }))).toBe(100);
    expect(bookingRest(order({ plannedAmount: '20.00', bookedAmount: '30.00' }))).toBe(0);
    expect(bookingRest(order({ plannedAmount: null }))).toBe(0);
    expect(bookingPayee(order({ supplier: 'Technikhaus' }))).toBe('Technikhaus');
    expect(bookingPayee(order({ kind: 'outlay', buyerLabel: 'Lea Hoffmann' }))).toBe('Lea Hoffmann');
    expect(bookingPayee(order({ kind: 'outlay', buyerLabel: null }))).toBe('');
  });
});
