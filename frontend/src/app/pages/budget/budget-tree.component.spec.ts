import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { AdminApiService } from '../admin/admin-api.service';
import { BudgetTreeComponent } from './budget-tree.component';
import type { BudgetTreeNode, FiscalYear } from './budget-tree.api';

const FY: FiscalYear = {
  id: 'fy-1',
  budgetId: 'b-vs',
  label: '2026',
  startDate: '2026-01-01',
  endDate: '2026-12-31',
  active: true,
};

const TREE: BudgetTreeNode[] = [
  {
    id: 'b-vs',
    parentId: null,
    gremiumId: 'g-1',
    key: 'VS',
    pathKey: 'VS',
    name: 'VS-Mittel',
    currency: 'EUR',
    active: true,
    byFiscalYear: [{ fiscalYearId: 'fy-1', allocated: '1000', committed: '250', available: '750' }],
    children: [
      {
        id: 'b-800',
        parentId: 'b-vs',
        gremiumId: 'g-1',
        key: '800',
        pathKey: 'VS-800',
        name: 'Dezentrale Einrichtungen',
        currency: 'EUR',
        active: true,
        byFiscalYear: [{ fiscalYearId: 'fy-1', allocated: '400', committed: '100', available: '300' }],
        children: [],
      },
    ],
  },
];

async function setup() {
  const view = await render(BudgetTreeComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: AdminApiService, useValue: { listGremienOptions: () => of([{ id: 'g-1', name: 'StuPa' }]) } },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  http.expectOne((r) => r.url.endsWith('/budgets')).flush(TREE);
  http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
  view.fixture.detectChanges();
  return { ...view, http };
}

describe('BudgetTreeComponent (#9)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders the cost-centre tree with full path keys', async () => {
    await setup();
    expect(screen.getByText('VS')).toBeInTheDocument();
    expect(screen.getByText('VS-800')).toBeInTheDocument();
    expect(screen.getByText('Dezentrale Einrichtungen')).toBeInTheDocument();
  });

  it('flattens nested children into rows (pre-order)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.rows().map((r: { node: { pathKey: string } }) => r.node.pathKey)).toEqual(['VS', 'VS-800']);
    expect(c.rows()[1].depth).toBe(1);
  });

  it('sets a limit (allocation) via PUT for the selected fiscal year', async () => {
    const { fixture, http } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openLimit(TREE[0].children[0]);
    c.limitValue.set('500');
    c.saveLimit();
    const put = http.expectOne((r) => r.url.endsWith('/budgets/b-800/allocations/fy-1'));
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ allocated: '500' });
    put.flush({ budgetId: 'b-800', fiscalYearId: 'fy-1', allocated: '500' });
    // reload nach Erfolg
    http.expectOne((r) => r.url.endsWith('/budgets')).flush(TREE);
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
  });
});
