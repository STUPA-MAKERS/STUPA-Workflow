import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Invoice, InvoiceBooking } from '../../budget/budget-tree.api';
import type { CostCentreLabel } from '../../budget/expense-display.util';
import { InvoiceDetailComponent } from './invoice-detail.component';

const BOOKING: InvoiceBooking = {
  id: 'b-1',
  budgetId: 'cc',
  pathKey: 'VS-200-220',
  budgetName: 'Maschinenbau',
  fiscalYearId: 'fy',
  kind: 'expense',
  amount: '900.00',
  description: 'Lastenrad Anzahlung',
  paymentDate: '2026-09-25',
  parentExpenseId: null,
  createdAt: '2026-09-25T00:00:00Z',
};

/** An ISO date `days` from today. */
function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const INVOICE: Invoice = {
  id: 'inv',
  number: 'RE-2026-118',
  issueDate: '2026-09-24',
  dueDate: inDays(9),
  supplier: 'Radhaus Müller GmbH',
  netAmount: '2428.57',
  taxAmount: '461.43',
  grossAmount: '2890.00',
  currency: 'EUR',
  note: 'Anzahlung geleistet',
  status: 'open',
  fileName: 'RE-2026-118.pdf',
  hasFile: true,
  actor: null,
  createdAt: '2026-09-24T09:00:00Z',
  linkedBookings: [BOOKING, { ...BOOKING, id: 'b-2', parentExpenseId: 'b-1', kind: 'income', budgetId: 'x', budgetName: '', paymentDate: null }],
};

async function setup(inputs: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const handlers = {
    edit: jest.fn(),
    remove: jest.fn(),
    markPaid: jest.fn(),
    createBooking: jest.fn(),
    openFile: jest.fn(),
  };
  const view = await render(InvoiceDetailComponent, {
    inputs: {
      invoice: INVOICE,
      costCentres: new Map<string, CostCentreLabel>([['cc', { name: 'Maschinenbau', path: 'VS-200-220', color: '#f28c28' }]]),
      canManage: true,
      split: true,
      ...inputs,
    },
    on: handlers,
    providers: [provideRouter([])],
  });
  return { view, ...handlers, user: userEvent.setup() };
}

const text = () => (document.body.textContent ?? '').replace(/\s+/g, ' ');

describe('InvoiceDetailComponent', () => {
  it('shows the head, the receipt, the amounts with the VAT rate, the data and the bookings', async () => {
    await setup();
    expect(screen.getByText('Rechnung · RE-2026-118')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Radhaus Müller GmbH' })).toBeInTheDocument();
    expect(screen.getByText('in 9 Tagen')).toBeInTheDocument();
    expect(screen.getByText('USt. 19 %')).toBeInTheDocument();
    expect(text()).toContain('2.890,00 €');
    expect(screen.getByText('Anzahlung geleistet')).toBeInTheDocument();
    expect(screen.getByText('RE-2026-118.pdf')).toBeInTheDocument();
    // A booking opens on the bookings page; a sub-booking opens its parent.
    const links = screen.getAllByRole('link');
    expect(links[0].getAttribute('href')).toBe('/expenses?id=b-1');
    expect(links[1].getAttribute('href')).toBe('/expenses?id=b-1');
    expect(text()).toContain('900,00 € von 2.890,00 €');
    expect(text()).toContain('Noch nicht verbucht: 1.990,00 €');
  });

  it('says how the due date stands', async () => {
    const { view } = await setup({ invoice: { ...INVOICE, dueDate: inDays(1) } });
    expect(screen.getByText('morgen fällig')).toBeInTheDocument();
    view.fixture.componentRef.setInput('invoice', { ...INVOICE, dueDate: inDays(0) });
    view.fixture.detectChanges();
    expect(screen.getByText('heute fällig').classList.contains('fd__neg')).toBe(true);
    view.fixture.componentRef.setInput('invoice', { ...INVOICE, dueDate: inDays(-1) });
    view.fixture.detectChanges();
    expect(screen.getByText('seit 1 Tag überfällig')).toBeInTheDocument();
    view.fixture.componentRef.setInput('invoice', { ...INVOICE, dueDate: inDays(-3) });
    view.fixture.detectChanges();
    expect(screen.getByText('seit 3 Tagen überfällig')).toBeInTheDocument();
    // A paid invoice is not due.
    view.fixture.componentRef.setInput('invoice', { ...INVOICE, status: 'paid' });
    view.fixture.detectChanges();
    expect(screen.queryByText(/fällig$|Tagen$/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Als bezahlt markieren' })).toBeNull();
  });

  it('leaves out what the invoice does not state', async () => {
    await setup({
      invoice: {
        ...INVOICE,
        number: null,
        supplier: null,
        dueDate: null,
        issueDate: null,
        netAmount: null,
        taxAmount: null,
        note: null,
        hasFile: false,
        linkedBookings: [],
      },
      canManage: false,
    });
    expect(screen.getByText('Rechnung')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Rechnung ohne Lieferant' })).toBeInTheDocument();
    expect(screen.getByText('USt.')).toBeInTheDocument();
    expect(screen.getByText('Kein Beleg-PDF hinterlegt.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Buchung anlegen' })).toBeNull();
    expect(screen.queryByText(/Noch nicht verbucht/)).toBeNull();
    expect(screen.getByText('Noch keine Buchung.')).toBeInTheDocument();
  });

  it('hides the bookings for a backend that sends none', async () => {
    await setup({ invoice: { ...INVOICE, linkedBookings: undefined } });
    expect(screen.queryByRole('heading', { name: /Buchungen/ })).toBeNull();
  });

  it('runs the actions of the head and of its menu', async () => {
    const { edit, remove, markPaid, createBooking, openFile, user } = await setup();
    await user.click(screen.getByRole('button', { name: 'Als bezahlt markieren' }));
    expect(markPaid).toHaveBeenCalled();
    await user.click(screen.getAllByRole('button', { name: 'Buchung anlegen' })[1]);
    expect(createBooking).toHaveBeenCalled();
    await user.click(screen.getAllByRole('button', { name: 'Beleg öffnen' })[0]);
    expect(openFile).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: /RE-2026-118\.pdf/ }));
    expect(openFile).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: 'Rechnung bearbeiten' }));
    expect(edit).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
    await user.click(screen.getByRole('menuitem', { name: 'Löschen' }));
    expect(remove).toHaveBeenCalled();
  });

  it('puts the receipt into the menu and shows a labelled edit on a phone', async () => {
    const { view, edit, openFile, user } = await setup({ phone: true });
    await user.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    expect(edit).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
    await user.click(screen.getByRole('menuitem', { name: 'Beleg öffnen' }));
    expect(openFile).toHaveBeenCalled();
    view.fixture.componentInstance.onMenu({ id: 'other', label: '' });
    view.fixture.componentRef.setInput('canManage', false);
    view.fixture.componentRef.setInput('invoice', { ...INVOICE, hasFile: false });
    view.fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).toBeNull();
  });
});
