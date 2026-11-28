import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { SalesApiService, type SyncResult } from '@core/api/sales.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastWith } from '../../testing/load-error';
import { SalesSyncAction, causeKey } from './sales-sync';

function setup(api: Partial<Record<keyof SalesApiService, jest.Mock>>) {
  localStorage.setItem('ap.locale', 'de');
  const toast = { success: jest.fn(), error: jest.fn() };
  TestBed.configureTestingModule({
    providers: [
      { provide: SalesApiService, useValue: api },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  return { action: TestBed.inject(SalesSyncAction), toast };
}

describe('causeKey', () => {
  it('names each known cause and reads an unknown one as unknown', () => {
    expect(causeKey('fiscal_year_closed')).toBe('sales.cause.fiscalYearClosed');
    expect(causeKey('cost_centre_not_leaf')).toBe('sales.cause.notLeaf');
    expect(causeKey('other')).toBe('sales.cause.unknown');
    expect(causeKey(null)).toBe('sales.cause.unknown');
  });
});

describe('SalesSyncAction', () => {
  it('shows the action while one integration is on, and hides it on an error', () => {
    const syncState = jest.fn().mockReturnValueOnce(of({ pretix: false, mollie: true }));
    const { action } = setup({ syncState });
    action.load();
    expect(action.available()).toBe(true);
    syncState.mockReturnValueOnce(throwError(() => new Error('x')));
    action.load();
    expect(action.available()).toBe(false);
  });

  it('reports the new bookings and each failure', () => {
    const result: SyncResult = {
      booked: 2,
      failures: [{ integration: 'mollie', source: 'payment', key: 'tr_1', cause: 'fiscal_year_closed' }],
    };
    const sync = jest.fn(() => of(result));
    const { action, toast } = setup({ sync });
    const done = jest.fn();
    action.run('bookings', done);
    expect(sync).toHaveBeenCalledWith('bookings');
    expect(done).toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith('2 neue Buchungen · Mollie tr_1: Das Haushaltsjahr ist abgeschlossen.');
    action.report({ booked: 1, failures: [{ integration: 'pretix', source: 'order', key: 'A', cause: 'x' }] });
    expect(toast.error).toHaveBeenLastCalledWith('1 neue Buchung · Pretix A: Unbekannter Fehler.');
    action.report({ booked: 0, failures: [] });
    expect(toast.success).toHaveBeenCalledWith('0 neue Buchungen');
  });

  it('ignores a second press and says when another run is busy or the run failed', () => {
    const sync = jest
      .fn()
      .mockReturnValueOnce(throwError(() => ({ error: { code: 'sync_running' } })))
      .mockReturnValueOnce(throwError(() => ({ error: null })));
    const { action, toast } = setup({ sync });
    action.running.set(true);
    action.run('events');
    expect(sync).not.toHaveBeenCalled();
    action.running.set(false);
    action.run('events');
    expect(toast.error).toHaveBeenLastCalledWith('Es läuft bereits ein Abruf.');
    action.run('events');
    expect(toast.error).toHaveBeenLastCalledWith('Der Abruf ist fehlgeschlagen.');
    expect(action.running()).toBe(false);
  });
});
