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
  const line = { amount: '1' };

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
    api.setState('v', 'in_force').subscribe();
    expectCall('POST', '/api/budget-plan-versions/v/state', { state: 'in_force' });
    api.planOfVersion('v').subscribe();
    expectCall('GET', '/api/budget-plan-versions/v/plan');
    api.deleteVersion('v').subscribe();
    expectCall('DELETE', '/api/budget-plan-versions/v');
  });

  it('§F/finance/budget/000875: loads a version as a file with the name of the server', () => {
    const files: { filename: string; size: number }[] = [];
    const keep = (file: { blob: Blob; filename: string }) => files.push({ filename: file.filename, size: file.blob.size });
    api.exportVersion('v', 'pdf').subscribe(keep);
    http.expectOne('/api/budget-plan-versions/v/export.pdf').flush(new Blob(['pdf']), {
      headers: { 'Content-Disposition': `attachment; filename="Plan.pdf"; filename*=UTF-8''Haushaltsplan_M%C3%BCll.pdf` },
    });
    api.exportVersion('v', 'xlsx').subscribe(keep);
    http.expectOne('/api/budget-plan-versions/v/export.xlsx').flush(new Blob(['x']), {
      headers: { 'Content-Disposition': 'attachment; filename="Plan.xlsx"' },
    });
    api.exportVersion('v', 'xlsx').subscribe(keep);
    http.expectOne('/api/budget-plan-versions/v/export.xlsx').flush(null);
    expect(files).toEqual([
      { filename: 'Haushaltsplan_Müll.pdf', size: 3 },
      { filename: 'Plan.xlsx', size: 1 },
      { filename: 'Haushaltsplan.xlsx', size: 0 },
    ]);
  });

  it('calls the routes of the steps', () => {
    api.passNextStep('v', 1).subscribe();
    expectCall('POST', '/api/budget-plan-versions/v/steps/next', { step: 1 });
    api.requestStep('v').subscribe();
    expectCall('POST', '/api/budget-plan-versions/v/steps/next/request', {});
    api.steps('t').subscribe();
    expectCall('GET', '/api/budgets/t/plan-steps');
    const steps = [{ name: 'Beschluss', gremiumId: 'g' }];
    api.setSteps('t', steps).subscribe();
    expectCall('PUT', '/api/budgets/t/plan-steps', { steps });
  });

  it('calls the routes of the Kostenstelle', () => {
    const body = { parentId: 't', key: '1', name: 'A', side: null, amount: '0' };
    api.createNode('v', body).subscribe();
    expectCall('POST', '/api/budget-plan-versions/v/cost-centres', body);
    api.setPlanSwitch('t', true).subscribe();
    expectCall('PUT', '/api/budgets/t/plan-switch', { enabled: true });
    api.setLine('v', 'b', { side: 'income' }).subscribe();
    expectCall('PUT', '/api/budget-plan-versions/v/lines/b', { side: 'income' });
  });

  it('§F/finance/budget/000855: sets the state of a version by hand', () => {
    const body = { state: 'in_progress' as const, step: 1, reason: 'Altbestand' };
    api.setStateByHand('v', body).subscribe();
    expectCall('PUT', '/api/budget-plan-versions/v/state', body);
  });
});
