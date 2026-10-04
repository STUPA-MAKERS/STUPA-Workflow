import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { screen } from '@testing-library/angular';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Expense } from '../../budget/budget-tree.api';
import { ExpenseSubBookingsState } from '../expense-sub-bookings.state';
import { ExpensesListState } from '../expenses-list.state';
import { SubBookingDialogComponent } from './sub-booking-dialog.component';

const PARENT = { id: 'p-1', description: 'Lastenrad' } as Expense;

function setup() {
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
  http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
  const sub = TestBed.runInInjectionContext(() => new ExpenseSubBookingsState(list));
  const fixture = TestBed.createComponent(SubBookingDialogComponent);
  fixture.componentRef.setInput('sub', sub);
  fixture.detectChanges();
  return { fixture, http, sub };
}

describe('SubBookingDialogComponent', () => {
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('stays closed without a parent', () => {
    setup();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('names the parent it inherits from and adds the sub-booking', () => {
    const { fixture, http, sub } = setup();
    sub.openCreateSub(PARENT);
    fixture.detectChanges();
    expect(screen.getByText('Erbt Kostenstelle, HHJ und Art von „Lastenrad".')).toBeInTheDocument();
    for (const label of [/^Beschreibung/, /^Betrag/, 'Zahldatum', 'Empfänger/Zahler']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    sub.subDescription.set('Rahmen');
    sub.subAmount.set('720');
    fixture.detectChanges();
    screen.getByRole('button', { name: 'Unterbuchung hinzufügen' }).click();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/p-1/sub-bookings') && r.method === 'POST')
      .flush({});
    http.match(() => true).forEach((r) => r.flush([]));
    expect(sub.subParent()).toBeNull();
  });

  it('closes on cancel', () => {
    const { fixture, sub } = setup();
    sub.openCreateSub(PARENT);
    fixture.detectChanges();
    screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)?.click();
    expect(sub.subParent()).toBeNull();
  });
});
