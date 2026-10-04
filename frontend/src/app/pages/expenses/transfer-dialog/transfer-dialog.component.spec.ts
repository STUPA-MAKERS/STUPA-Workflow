import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { screen } from '@testing-library/angular';
import { USE_MOCK_API } from '@core/api/api.config';
import type { BudgetTransfer } from '../../budget/budget-tree.api';
import type { CostCentreLabel } from '../../budget/expense-display.util';
import { ExpenseDialogsState } from '../expense-dialogs.state';
import { ExpenseSubBookingsState } from '../expense-sub-bookings.state';
import { ExpenseTransfersState } from '../expense-transfers.state';
import { ExpensesListState } from '../expenses-list.state';
import { type TransferDialogMode, TransferDialogComponent } from './transfer-dialog.component';

const TRANSFER: BudgetTransfer = {
  transferId: 'tr-1',
  expenseId: 'e-1',
  incomeId: 'e-2',
  fromBudgetId: 'b-1',
  fromPathKey: 'VS-800',
  toBudgetId: 'b-2',
  toPathKey: 'VS-900',
  fiscalYearId: 'fy-1',
  amount: '50.00',
  currency: 'EUR',
  description: 'Umbuchung Fest',
  note: null,
  invoiceDate: null,
  paymentDate: null,
  actor: null,
  actorName: null,
  createdAt: '2026-05-01T10:00:00Z',
};

function setup(mode: TransferDialogMode) {
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
  const dialogs = TestBed.runInInjectionContext(
    () => new ExpenseDialogsState(list, sub, transfers),
  );
  http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
  http
    .expectOne((r) => r.url.endsWith('/invoices'))
    .flush({ items: [], total: 0, limit: 200, offset: 0 });
  const fixture = TestBed.createComponent(TransferDialogComponent);
  fixture.componentRef.setInput('dialogs', dialogs);
  fixture.componentRef.setInput('transfers', transfers);
  fixture.componentRef.setInput('mode', mode);
  fixture.componentRef.setInput(
    'costCentres',
    new Map<string, CostCentreLabel>([['b-1', { name: 'Rücklage', path: 'VS-800', color: '#b8323a' }]]),
  );
  fixture.detectChanges();
  return { fixture, http, dialogs, transfers };
}

describe('TransferDialogComponent', () => {
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('asks for from, to, fiscal year, amount and text, and books the transfer', () => {
    const { fixture, http, dialogs } = setup('create');
    dialogs.openTransfer();
    fixture.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Übertrag' })).toBeInTheDocument();
    for (const label of [/^Von Kostenstelle/, /^Zu Kostenstelle/, /^Haushaltsjahr/, /^Betrag/, /^Beschreibung/]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    dialogs.tFromId.set('b-1');
    dialogs.tToId.set('b-2');
    dialogs.tFiscalYearId.set('fy-1');
    dialogs.tAmount.set('10');
    dialogs.tDescription.set('Neu');
    fixture.detectChanges();
    screen.getByRole('button', { name: 'Übertragen' }).click();
    http.expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'POST').flush({});
    http.match(() => true).forEach((r) => r.flush({ items: [], total: 0, limit: 20, offset: 0 }));
    expect(dialogs.transferOpen()).toBe(false);
  });

  it('flags the same cost centre twice and a cost centre without a fiscal year', () => {
    const { fixture, dialogs } = setup('create');
    dialogs.openTransfer();
    dialogs.tFromId.set('b-1');
    dialogs.tToId.set('b-1');
    fixture.detectChanges();
    const alerts = screen.getAllByRole('alert').map((a) => a.textContent ?? '');
    expect(alerts.some((t) => t.includes('andere Kostenstelle'))).toBe(true);
    expect(alerts.some((t) => t.includes('kein Haushaltsjahr'))).toBe(true);
  });

  it('closes the new transfer on cancel', () => {
    const { fixture, dialogs } = setup('create');
    dialogs.openTransfer();
    fixture.detectChanges();
    screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)?.click();
    expect(dialogs.transferOpen()).toBe(false);
  });

  it('shows the fixed pair of a transfer and saves the correction', () => {
    const { fixture, http, transfers } = setup('edit');
    transfers.openEdit(TRANSFER);
    fixture.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Übertrag bearbeiten' })).toBeInTheDocument();
    expect(screen.getByText('Rücklage')).toBeInTheDocument();
    // The second cost centre is outside the loaded tree: its path names it.
    expect(screen.getByText('VS-900')).toBeInTheDocument();
    transfers.editAmount.set('75.00');
    fixture.detectChanges();
    screen.getByRole('button', { name: 'Speichern' }).click();
    const req = http.expectOne((r) => r.url.endsWith('/budget-transfers/tr-1'));
    expect(req.request.body.amount).toBe('75.00');
    req.flush(TRANSFER);
    http.match(() => true).forEach((r) => r.flush({ items: [], total: 0, limit: 20, offset: 0 }));
  });

  it('has no pair without a transfer under correction', () => {
    const { fixture } = setup('edit');
    const cmp = fixture.componentInstance as unknown as { pair(): unknown };
    expect(cmp.pair()).toBeNull();
  });

  it('closes the correction on cancel', () => {
    const { fixture, transfers } = setup('edit');
    transfers.openEdit(TRANSFER);
    fixture.detectChanges();
    screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)?.click();
    expect(transfers.editing()).toBeNull();
  });
});
