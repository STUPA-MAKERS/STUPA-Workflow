import type { Invoice, InvoiceBooking } from '../budget/budget-tree.api';
import { bookedOn, countedBookings } from './invoice-figures';

const B = (over: Partial<InvoiceBooking>): InvoiceBooking => ({
  id: 'b',
  budgetId: 'cc',
  pathKey: 'VS',
  budgetName: 'VS',
  fiscalYearId: 'fy',
  kind: 'expense',
  amount: '100.00',
  description: 'x',
  paymentDate: null,
  parentExpenseId: null,
  createdAt: '2026-01-01T00:00:00Z',
  ...over,
});

const INV = { grossAmount: '250.00' } as Invoice;

describe('invoice figures', () => {
  it('counts a parent once, not with its sub-bookings', () => {
    const rows = [B({ id: 'p' }), B({ id: 's', parentExpenseId: 'p' }), B({ id: 'o', parentExpenseId: 'elsewhere' })];
    expect(countedBookings(rows).map((b) => b.id)).toEqual(['p', 'o']);
  });

  it('sums the expense bookings against the gross amount', () => {
    const bookings = [B({ id: 'a' }), B({ id: 'i', kind: 'income', amount: '30.00' }), B({ id: 'c', amount: '50.00' })];
    expect(bookedOn({ ...INV, linkedBookings: bookings })).toEqual({ booked: 150, gross: 250, open: 100 });
    // Never a negative rest.
    expect(bookedOn({ ...INV, linkedBookings: [B({ amount: '300.00' })] })?.open).toBe(0);
    // A backend without A6 sends no bookings.
    expect(bookedOn(INV)).toBeNull();
  });
});
