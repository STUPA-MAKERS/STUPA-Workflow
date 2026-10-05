import type { Invoice, InvoiceBooking } from '../budget/budget-tree.api';

/** How much of an invoice is booked. */
export interface InvoiceBooked {
  /** The sum of the expense bookings on the invoice. */
  booked: number;
  /** The gross amount of the invoice. */
  gross: number;
  /** The rest, never below 0. */
  open: number;
}

/**
 * The bookings that count for the booked share: every booking whose parent is not on the
 * invoice too. A parent and its sub-bookings carry the same amount twice (the parent is the
 * sum of its children), so only the outer one counts.
 */
export function countedBookings(bookings: readonly InvoiceBooking[]): InvoiceBooking[] {
  const ids = new Set(bookings.map((b) => b.id));
  return bookings.filter((b) => !b.parentExpenseId || !ids.has(b.parentExpenseId));
}

/**
 * "Verbucht 900,00 € von 2.890,00 €": the sum of the expense bookings on the invoice
 * against its gross amount. Null when the server sends no bookings (a backend before A6).
 */
export function bookedOn(invoice: Invoice): InvoiceBooked | null {
  const bookings = invoice.linkedBookings;
  if (!bookings) return null;
  const booked = countedBookings(bookings)
    .filter((b) => b.kind === 'expense')
    .reduce((sum, b) => sum + Number(b.amount), 0);
  const gross = Number(invoice.grossAmount);
  return { booked, gross, open: Math.max(0, Math.round((gross - booked) * 100) / 100) };
}
