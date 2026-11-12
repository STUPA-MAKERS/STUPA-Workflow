import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL } from '@core/api/api.config';
import { BudgetPlanApi } from './budget-plan.api';

describe('BudgetPlanApi', () => {
  let api: BudgetPlanApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: API_BASE_URL, useValue: '/api' }],
    });
    api = TestBed.inject(BudgetPlanApi);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  const expectCall = (method: string, url: string, body?: unknown): void => {
    const req = http.expectOne(url);
    expect(req.request.method).toBe(method);
    if (body !== undefined) expect(req.request.body).toEqual(body);
    req.flush({});
  };
  const line = { amount: '1', note: null, transferable: false, coverable: false, blocked: '0' };

  it('calls the plan routes', () => {
    api.plan('t', 'f').subscribe();
    expectCall('GET', '/api/budgets/t/fiscal-years/f/plan');
    api.createPlan('t', 'f', 'p').subscribe();
    expectCall('POST', '/api/budgets/t/fiscal-years/f/plan', { copyFromFiscalYearId: 'p' });
    api.createNachtrag('t', 'f').subscribe();
    expectCall('POST', '/api/budgets/t/fiscal-years/f/plan/versions', {});
    api.setLine('v', 'b', line).subscribe();
    expectCall('PUT', '/api/budget-plan-versions/v/lines/b', line);
    api.deleteLine('v', 'b').subscribe();
    expectCall('DELETE', '/api/budget-plan-versions/v/lines/b');
    api.setState('v', 'resolved').subscribe();
    expectCall('POST', '/api/budget-plan-versions/v/state', { state: 'resolved' });
  });

  it('calls the routes of the Kostenstelle', () => {
    api.setSide('b', 'income').subscribe();
    expectCall('PUT', '/api/budgets/b/side', { side: 'income' });
    api.setPlanSwitch('t', true).subscribe();
    expectCall('PUT', '/api/budgets/t/plan-switch', { enabled: true });
  });
});
