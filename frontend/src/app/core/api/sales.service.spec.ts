import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { USE_MOCK_API } from './api.config';
import { SalesApiService } from './sales.service';

describe('SalesApiService', () => {
  let svc: SalesApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    svc = TestBed.inject(SalesApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  const expect1 = (method: string, url: string, body?: unknown) => {
    const req = http.expectOne((r) => r.urlWithParams === url && r.method === method);
    if (body !== undefined) expect(req.request.body).toEqual(body);
    req.flush({});
  };

  it('reads, saves and tests the pretix connection and lists its failed bookings', () => {
    svc.getPretix().subscribe();
    expect1('GET', '/api/admin/pretix');
    const body = { baseUrl: 'https://pretix.eu', organizer: 'stupa', showSales: true, bookIncome: false };
    svc.putPretix(body).subscribe();
    expect1('PUT', '/api/admin/pretix', body);
    svc.testPretix().subscribe();
    expect1('POST', '/api/admin/pretix/test', {});
    svc.pretixFailed().subscribe();
    expect1('GET', '/api/admin/pretix/failed-bookings');
  });

  it('reads, saves and tests the Mollie connection and lists its failed bookings', () => {
    svc.getMollie().subscribe();
    expect1('GET', '/api/admin/mollie');
    svc.putMollie({ feeBudgetId: null, unassignedBudgetId: 'b-1' }).subscribe();
    expect1('PUT', '/api/admin/mollie', { feeBudgetId: null, unassignedBudgetId: 'b-1' });
    svc.testMollie().subscribe();
    expect1('POST', '/api/admin/mollie/test', {});
    svc.mollieFailed().subscribe();
    expect1('GET', '/api/admin/mollie/failed-bookings');
  });

  it('links an Event, sets its income cost centre and reads its sales', () => {
    svc.pretixEvents().subscribe();
    expect1('GET', '/api/pretix/events');
    svc.link('e-1', 'party').subscribe();
    expect1('PUT', '/api/pretix/links/e-1', { slug: 'party' });
    svc.setIncomeBudget('e-1', 'b-1').subscribe();
    expect1('PUT', '/api/pretix/links/e-1/income-budget', { budgetId: 'b-1' });
    svc.unlink('e-1').subscribe();
    expect1('DELETE', '/api/pretix/links/e-1');
    svc.eventSales('e-1').subscribe();
    expect1('GET', '/api/events/e-1/sales');
    svc.refreshEvent('e-1').subscribe();
    expect1('POST', '/api/events/e-1/sales/refresh', {});
  });

  it('reads the state of the action "Daten abrufen" and runs it for a page', () => {
    svc.syncState().subscribe();
    expect1('GET', '/api/sales-sync');
    svc.sync('events').subscribe();
    expect1('POST', '/api/sales-sync?page=events', {});
  });
});
