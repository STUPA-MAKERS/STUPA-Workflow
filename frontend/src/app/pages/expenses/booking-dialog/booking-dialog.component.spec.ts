import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { BudgetTreeNode, Expense, Invoice } from '../../budget/budget-tree.api';
import { ExpenseDialogsState } from '../expense-dialogs.state';
import { ExpenseSubBookingsState } from '../expense-sub-bookings.state';
import { ExpenseTransfersState } from '../expense-transfers.state';
import { ExpensesListState } from '../expenses-list.state';
import { type BookingDialogMode, BookingDialogComponent } from './booking-dialog.component';

const NODE: BudgetTreeNode = {
  id: 'top-1',
  parentId: null,
  gremiumId: null,
  key: 'VS',
  pathKey: 'VS',
  name: 'Verfasste Studierendenschaft',
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
};

const INVOICE: Invoice = {
  id: 'inv-1',
  number: 'RE-1',
  issueDate: '2026-04-01',
  dueDate: null,
  supplier: 'Acme',
  netAmount: null,
  taxAmount: null,
  grossAmount: '119.00',
  currency: 'EUR',
  note: null,
  status: 'open',
  fileName: null,
  hasFile: false,
  actor: null,
  createdAt: '2026-04-01T00:00:00Z',
};

const EXPENSE: Expense = {
  id: 'e-1',
  budgetId: 'top-1',
  pathKey: 'VS',
  fiscalYearId: 'fy-1',
  kind: 'expense',
  amount: '120.00',
  currency: 'EUR',
  description: 'Flyer',
  applicationId: null,
  applicationTitle: null,
  transferId: null,
  actor: null,
  actorName: null,
  invoiceDate: null,
  paymentDate: null,
  correspondent: null,
  note: null,
  referenceNumber: null,
  paymentMethod: null,
  category: null,
  invoiceId: null,
  invoiceNumber: null,
  parentExpenseId: null,
  childCount: 0,
  createdAt: '2026-05-30T09:00:00Z',
};

function setup(mode: BookingDialogMode) {
  localStorage.setItem('ap.locale', 'de');
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const list = TestBed.runInInjectionContext(() => new ExpensesListState());
  const sub = TestBed.runInInjectionContext(() => new ExpenseSubBookingsState(list));
  const transfers = TestBed.runInInjectionContext(() => new ExpenseTransfersState(list));
  const state = TestBed.runInInjectionContext(
    () => new ExpenseDialogsState(list, sub, transfers),
  );
  http.expectOne((r) => r.url.endsWith('/budgets')).flush([NODE]);
  http
    .expectOne((r) => r.url.endsWith('/invoices'))
    .flush({ items: [INVOICE], total: 1, limit: 200, offset: 0 });
  const fixture = TestBed.createComponent(BookingDialogComponent);
  fixture.componentRef.setInput('state', state);
  fixture.componentRef.setInput('mode', mode);
  fixture.componentRef.setInput('costCentreOptions', [{ value: 'top-1', label: 'VS' }]);
  fixture.detectChanges();
  const render = (): void => {
    fixture.detectChanges();
  };
  return { fixture, http, list, state, render };
}

describe('BookingDialogComponent (create)', () => {
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('stays closed until the state opens it', () => {
    setup('create');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows every field of a booking (N30)', () => {
    const { state, render } = setup('create');
    state.createOpen.set(true);
    render();
    const dialog = within(screen.getByRole('dialog', { name: 'Buchung hinzufügen' }));
    for (const label of [
      /^Beschreibung/,
      /^Betrag \(€\)/,
      'Mit Antrag verknüpfen (optional)',
      /^Kostenstelle/,
      /^Haushaltsjahr/,
      'Rechnung',
      'Empfänger/Zahler',
      'Rechnungsdatum',
      'Zahldatum',
      'Belegnummer',
      'Zahlungsmethode',
      'Kategorie',
      'Anmerkungen',
    ]) {
      expect(dialog.getByLabelText(label)).toBeInTheDocument();
    }
    expect(dialog.getByRole('radio', { name: 'Ausgabe' }).getAttribute('aria-checked')).toBe(
      'true',
    );
  });

  it('sends every field it holds when the booking is added', () => {
    const { state, http, render } = setup('create');
    state.openCreate();
    state.newDescription.set('Druck');
    state.newAmount.set('186.40');
    state.newBudgetId.set('top-1');
    state.newFiscalYearId.set('fy-1');
    state.newInvoiceId.set('inv-1');
    state.newCorrespondent.set('Copyshop');
    state.newInvoiceDate.set('2026-09-24');
    state.newPaymentDate.set('2026-09-29');
    state.newReferenceNumber.set('K-311');
    state.newPaymentMethod.set('ueberweisung');
    state.newCategory.set('Druck');
    state.newNote.set('Plakate');
    render();
    screen.getByRole('button', { name: 'Buchung hinzufügen' }).click();
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST');
    expect(req.request.body).toEqual({
      amount: '186.40',
      description: 'Druck',
      kind: 'expense',
      applicationId: null,
      budgetId: 'top-1',
      fiscalYearId: 'fy-1',
      invoiceId: 'inv-1',
      invoiceDate: '2026-09-24',
      paymentDate: '2026-09-29',
      correspondent: 'Copyshop',
      referenceNumber: 'K-311',
      paymentMethod: 'ueberweisung',
      category: 'Druck',
      note: 'Plakate',
    });
    req.flush(EXPENSE);
    http.match(() => true).forEach((r) => r.flush({ items: [], total: 0, limit: 20, offset: 0 }));
  });

  it('switches the kind; an income has no application to link', async () => {
    const { state, render } = setup('create');
    state.openCreate();
    render();
    await userEvent.click(screen.getByRole('radio', { name: 'Einnahme' }));
    render();
    expect(state.newKind()).toBe('income');
    expect(screen.queryByLabelText('Mit Antrag verknüpfen (optional)')).toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: 'Ausgabe' }));
    render();
    expect(state.newKind()).toBe('expense');
  });

  it('links an application; cost centre and fiscal year then come from it', async () => {
    const { state, http, render } = setup('create');
    state.openCreate();
    render();
    const search = screen.getByRole('combobox', { name: 'Mit Antrag verknüpfen (optional)' });
    await userEvent.type(search, 'f');
    http
      .expectOne((r) => r.url.endsWith('/applications') && r.method === 'GET')
      .flush({ items: [{ id: 'app-1', title: 'Fest', data: {} }], total: 1, limit: 8, offset: 0 });
    render();
    expect(search.getAttribute('aria-expanded')).toBe('true');
    await userEvent.click(screen.getByRole('option', { name: 'Fest' }));
    render();
    expect(state.newApplicationId()).toBe('app-1');
    expect(screen.getByText('Kostenstelle und Haushaltsjahr werden vom Antrag übernommen.')).toBeTruthy();
    expect(screen.queryByLabelText(/^Haushaltsjahr/)).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Verknüpfung lösen' }));
    render();
    expect(state.newApplicationId()).toBe('');
    expect(screen.getByLabelText(/^Haushaltsjahr/)).toBeInTheDocument();
  });

  it('says so when a cost centre has no fiscal year', () => {
    const { state, http, render } = setup('create');
    state.openCreate();
    state.onPickBudget('top-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([]);
    render();
    expect(screen.getByRole('alert').textContent).toContain('kein Haushaltsjahr');
  });

  it('closes on cancel', () => {
    const { state, render } = setup('create');
    state.openCreate();
    render();
    // The footer button; the other one is the close button of the dialog.
    screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)?.click();
    expect(state.createOpen()).toBe(false);
  });
});

describe('BookingDialogComponent (edit)', () => {
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('lets a standalone booking move to another cost centre and saves', async () => {
    const { state, http, render, fixture } = setup('edit');
    state.openEdit({ ...EXPENSE, category: 'Werbung' });
    render();
    // ngModel writes the value in a microtask; the kit field then renders it.
    await fixture.whenStable();
    fixture.detectChanges();
    const dialog = within(screen.getByRole('dialog', { name: 'Buchung bearbeiten' }));
    expect(dialog.getByLabelText(/^Kostenstelle/)).toBeInTheDocument();
    expect(dialog.getByLabelText('Kategorie')).toHaveValue('Werbung');
    dialog.getByRole('button', { name: 'Speichern' }).click();
    const req = http.expectOne((r) => r.url.endsWith('/budget-expenses/e-1'));
    expect(req.request.method).toBe('PATCH');
    req.flush(EXPENSE);
    // A save reloads the invoices: the booking can have marked one paid.
    http
      .expectOne((r) => r.url.endsWith('/invoices'))
      .flush({ items: [], total: 0, limit: 200, offset: 0 });
    expect(state.editing()).toBeNull();
  });

  it('shows the amount of a parent read-only, as the sum of its sub-bookings', () => {
    const { state, render } = setup('edit');
    state.openEdit({ ...EXPENSE, childCount: 2, amount: '300.00' });
    render();
    expect(screen.getByText('Betrag = Summe der Unterbuchungen')).toBeInTheDocument();
    expect(screen.getByText(/300,00/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Betrag \(€\)/)).toBeNull();
  });

  it('names where a bound booking and a sub-booking take their cost centre from', () => {
    const { state, render } = setup('edit');
    state.openEdit({ ...EXPENSE, applicationId: 'app-1' });
    render();
    expect(screen.getByText('Kostenstelle und Haushaltsjahr werden vom Antrag übernommen.')).toBeTruthy();
    expect(screen.queryByLabelText(/^Kostenstelle/)).toBeNull();
    state.openEdit({ ...EXPENSE, parentExpenseId: 'p-1' });
    render();
    expect(
      screen.getByText('Kostenstelle, Haushaltsjahr und Art kommen von der Hauptbuchung.'),
    ).toBeTruthy();
  });

  it('reads no parent amount and no own cost centre without a booking', () => {
    const { fixture, state } = setup('edit');
    const cmp = fixture.componentInstance as unknown as {
      parentAmount(): string | null;
      editOwnsCostCentre(): boolean;
    };
    expect(cmp.parentAmount()).toBeNull();
    expect(cmp.editOwnsCostCentre()).toBe(false);
    // A booking from an older list without a child count is not a parent.
    state.editing.set({ ...EXPENSE, childCount: undefined as unknown as number });
    expect(cmp.parentAmount()).toBeNull();
  });

  it('closes on cancel', () => {
    const { state, render } = setup('edit');
    state.openEdit(EXPENSE);
    render();
    // The footer button; the other one is the close button of the dialog.
    screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)?.click();
    expect(state.editing()).toBeNull();
  });
});
