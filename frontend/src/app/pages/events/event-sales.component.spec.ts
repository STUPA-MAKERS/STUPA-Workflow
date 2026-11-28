import { render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { type EventSales, SalesApiService } from '@core/api/sales.service';
import { MOCK_EVENT_SALES } from '@core/api/mock-sales';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastWith } from '../../../testing/load-error';
import { EventSalesComponent } from './event-sales.component';

async function setup(sales: EventSales | null, refresh = jest.fn(() => of({ booked: 1, failures: [] }))) {
  localStorage.setItem('ap.locale', 'de');
  const toast = { success: jest.fn(), error: jest.fn() };
  const api = {
    eventSales: jest.fn(() => (sales ? of(sales) : throwError(() => new Error('x')))),
    refreshEvent: refresh,
  };
  const view = await render(EventSalesComponent, {
    inputs: { eventId: 'e-1' },
    providers: [
      { provide: SalesApiService, useValue: api },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast };
}

describe('EventSalesComponent', () => {
  it('shows the link, the products, the sums, the free places and the Mollie money', async () => {
    const { container } = await setup(MOCK_EVENT_SALES);
    expect(screen.getByText('Verkauf')).toBeTruthy();
    expect(screen.getByText('Semesterparty WS 26/27')).toBeTruthy();
    expect(screen.getByText('2.4 Veranstaltungen')).toBeTruthy();
    expect(screen.getByText('412 bezahlt · 9 offen · 6 storniert')).toBeTruthy();
    expect(screen.getByText('Frei: Einlass')).toBeTruthy();
    expect(screen.getByText('Mollie: Gebühren')).toBeTruthy();
    expect(screen.getByText(/Auszahlung 1234567\.2611\.01 vom/)).toBeTruthy();
    expect(container.querySelectorAll('[data-testid="es-mollie"]')).toHaveLength(6);
    expect(screen.getByText(/^Stand: /)).toBeTruthy();
  });

  it('stays hidden without a part', async () => {
    const empty = { ...MOCK_EVENT_SALES, link: null, pretix: null, mollie: null };
    const { fixture } = await setup(empty);
    expect((fixture.nativeElement as HTMLElement).hasAttribute('hidden')).toBe(true);
  });

  it('stays hidden after a failed read', async () => {
    const { fixture } = await setup(null);
    expect((fixture.nativeElement as HTMLElement).hasAttribute('hidden')).toBe(true);
  });

  it('shows a link without a cost centre, an unlimited quota, a settlement without a day and no read time', async () => {
    const sales: EventSales = {
      ...MOCK_EVENT_SALES,
      refreshable: false,
      link: { ...MOCK_EVENT_SALES.link!, name: '', incomeBudgetName: null },
      pretix: { ...MOCK_EVENT_SALES.pretix!, quotas: [{ name: 'Alle', available: null }], readAt: null },
      mollie: { ...MOCK_EVENT_SALES.mollie!, settlements: [{ reference: 'R', settledAt: null, amount: '1.00' }], readAt: null },
    };
    const { container } = await setup(sales);
    expect(screen.getByText('semesterparty-ws26')).toBeTruthy();
    expect(screen.queryByText('Einnahmen-Kostenstelle')).toBeNull();
    expect(screen.getByText('Unbegrenzt')).toBeTruthy();
    expect(screen.getByText('Auszahlung R vom –')).toBeTruthy();
    expect(screen.queryByText(/^Stand: /)).toBeNull();
    expect(container.querySelector('[data-testid="es-refresh"]')).toBeNull();
  });

  it('refreshes once, reports the result and reads the section again', async () => {
    const { api, toast, fixture } = await setup(MOCK_EVENT_SALES);
    const page = fixture.componentInstance as unknown as { refresh(): void; refreshing: { set(v: boolean): void } };
    page.refreshing.set(true);
    page.refresh();
    expect(api.refreshEvent).not.toHaveBeenCalled();
    page.refreshing.set(false);
    (screen.getByTestId('es-refresh').querySelector('button') ?? screen.getByTestId('es-refresh')).click();
    expect(api.refreshEvent).toHaveBeenCalledWith('e-1');
    expect(toast.success).toHaveBeenCalledWith('1 neue Buchung');
    expect(api.eventSales).toHaveBeenCalledTimes(2);
  });

  it.each([
    ['refresh_too_soon', 'Die Zahlen wurden eben erst gelesen. Versuche es in einer Minute erneut.'],
    ['sync_running', 'Es läuft bereits ein Abruf.'],
    [undefined, 'Der Abruf ist fehlgeschlagen.'],
  ])('says why a refresh failed (%s)', async (code, text) => {
    const refresh = jest.fn(() => throwError(() => ({ error: code ? { code } : null })));
    const { toast, fixture } = await setup(MOCK_EVENT_SALES, refresh);
    (fixture.componentInstance as unknown as { refresh(): void }).refresh();
    expect(toast.error).toHaveBeenCalledWith(text);
  });
});
