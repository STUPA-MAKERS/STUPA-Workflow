import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { BudgetDashboardComponent } from './budget-dashboard.component';
import type { BudgetApplication, BudgetTreeNode, FiscalYear } from './budget-tree.api';

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
    byFiscalYear: [{ fiscalYearId: 'fy-1', allocated: '1000', committed: '400', available: '600' }],
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

const APPS: BudgetApplication[] = [
  {
    applicationId: 'aaaaaaaa-1111-2222-3333-444444444444',
    budgetId: 'b-800',
    pathKey: 'VS-800',
    fiscalYearId: 'fy-1',
    amount: '120.00',
    currency: 'EUR',
    stage: 'approved',
    stateId: 's-1',
    createdAt: '2026-05-01T10:00:00Z',
  },
];

async function setup() {
  const view = await render(BudgetDashboardComponent, {
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
  });
  const http = TestBed.inject(HttpTestingController);
  http.expectOne((r) => r.url.endsWith('/budgets')).flush(TREE);
  http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
  http.expectOne((r) => r.url.includes('/budgets/b-vs/applications')).flush(APPS);
  view.fixture.detectChanges();
  return { ...view, http };
}

describe('BudgetDashboardComponent (#17)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the cost-centre subtree with bars and the applications panel', async () => {
    await setup();
    expect(screen.getAllByText('VS').length).toBeGreaterThan(0);
    // Budget-Name erscheint im linken Baum + als Wurzel-Zeile der Auslastungstabelle.
    expect(screen.getAllByText('VS-Mittel').length).toBeGreaterThan(0);
    // Pfad VS-800 erscheint in der Auslastungstabelle (links) und in der Anträge-Tabelle (rechts).
    expect(screen.getAllByText('VS-800').length).toBeGreaterThan(1);
  });

  it('drills into a cost centre on click and reloads its applications', async () => {
    const { fixture, http } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.drillInto(TREE[0].children[0]);
    expect(c.selectedKsId()).toBe('b-800');
    http.expectOne((r) => r.url.includes('/budgets/b-800/applications')).flush(APPS);
    // Breadcrumbs gehen jetzt VS › 800.
    expect(c.breadcrumbs().map((n: { key: string }) => n.key)).toEqual(['VS', '800']);
  });

  it('opens an application in a popover dialog', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openApp(APPS[0]);
    fixture.detectChanges();
    expect(c.dialogApp()).toEqual(APPS[0]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
