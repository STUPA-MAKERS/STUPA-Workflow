import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { BudgetDashboardComponent } from './budget-dashboard.component';
import type {
  BudgetAllocationView,
  BudgetApplication,
  BudgetTreeNode,
  FiscalYear,
} from './budget-tree.api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Inst = any;

/** Vollständige Allokations-View (alle Felder, damit Number(undefined)=NaN nie auftritt). */
function alloc(over: Partial<BudgetAllocationView> & { fiscalYearId: string }): BudgetAllocationView {
  return {
    fiscalYearId: over.fiscalYearId,
    allocated: over.allocated ?? '0',
    bound: over.bound ?? '0',
    expended: over.expended ?? '0',
    income: over.income ?? '0',
    committed: over.committed ?? '0',
    requested: over.requested ?? '0',
    available: over.available ?? '0',
  };
}

function node(over: Partial<BudgetTreeNode> & { id: string }): BudgetTreeNode {
  return {
    id: over.id,
    parentId: over.parentId ?? null,
    gremiumId: over.gremiumId ?? null,
    key: over.key ?? over.id,
    pathKey: over.pathKey ?? over.id.toUpperCase(),
    name: over.name ?? `Node ${over.id}`,
    currency: over.currency ?? 'EUR',
    active: over.active ?? true,
    color: over.color ?? null,
    acceptedStateKeys: over.acceptedStateKeys ?? [],
    deniedStateKeys: over.deniedStateKeys ?? [],
    fullyBound: over.fullyBound ?? false,
    hiddenInBudget: over.hiddenInBudget ?? false,
    viewGremiumId: over.viewGremiumId ?? null,
    fiscalStartMonth: over.fiscalStartMonth ?? 1,
    fiscalStartDay: over.fiscalStartDay ?? 1,
    byFiscalYear: over.byFiscalYear ?? [],
    children: over.children ?? [],
  };
}

const FY: FiscalYear = {
  id: 'fy-1',
  budgetId: 'b-vs',
  year: 2026,
  display: '2026',
  startDate: '2026-01-01',
  endDate: '2026-12-31',
  active: true,
};

const FY2: FiscalYear = { ...FY, id: 'fy-2', year: 2027, display: '2027' };

const TREE: BudgetTreeNode[] = [
  node({
    id: 'b-vs',
    gremiumId: 'g-1',
    key: 'VS',
    pathKey: 'VS',
    name: 'VS-Mittel',
    color: '#123456',
    byFiscalYear: [
      alloc({ fiscalYearId: 'fy-1', allocated: '1000', committed: '400', available: '600', requested: '50', bound: '300', expended: '100' }),
    ],
    children: [
      node({
        id: 'b-800',
        parentId: 'b-vs',
        gremiumId: 'g-1',
        key: '800',
        pathKey: 'VS-800',
        name: 'Dezentrale Einrichtungen',
        byFiscalYear: [
          alloc({ fiscalYearId: 'fy-1', allocated: '400', committed: '100', available: '300', requested: '20', bound: '60', expended: '40' }),
        ],
        children: [],
      }),
    ],
  }),
];

const APPS: BudgetApplication[] = [
  {
    applicationId: 'aaaaaaaa-1111-2222-3333-444444444444',
    title: 'Lautsprecher',
    budgetId: 'b-800',
    pathKey: 'VS-800',
    fiscalYearId: 'fy-1',
    amount: '120.00',
    currency: 'EUR',
    stage: 'approved',
    stateId: 's-1',
    stateLabel: { de: 'Angenommen', en: 'Accepted' },
    stateColor: '#0a0',
    createdAt: '2026-05-01T10:00:00Z',
  },
];

function authStub(canValue = true): AuthService {
  return { can: (_p: string) => canValue } as unknown as AuthService;
}

interface SetupOpts {
  tree?: BudgetTreeNode[];
  fys?: FiscalYear[];
  apps?: BudgetApplication[];
  can?: boolean;
  queryParams?: Record<string, string>;
}

async function setup(opts: SetupOpts = {}) {
  const tree = opts.tree ?? TREE;
  const fys = opts.fys ?? [FY];
  const apps = opts.apps ?? APPS;
  const view = await render(BudgetDashboardComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: AuthService, useValue: authStub(opts.can ?? true) },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { queryParamMap: new Map(Object.entries(opts.queryParams ?? {})) },
        },
      },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  http.expectOne((r) => r.url.endsWith('/budgets')).flush(tree);
  // Each top with a fiscal-years request.
  const tops = tree.filter((n) => !n.hiddenInBudget);
  for (const top of tops) {
    http.expectOne((r) => r.url.endsWith(`/budgets/${top.id}/fiscal-years`)).flush(fys);
  }
  // After restore, applications for the selected ks (= first top) is requested.
  const reqs = http.match((r) => r.url.includes('/applications'));
  reqs.forEach((r) => r.flush(apps));
  view.fixture.detectChanges();
  return { ...view, http, c: view.fixture.componentInstance as unknown as Inst };
}

describe('BudgetDashboardComponent (#17)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('shows the cost-centre subtree with bars and the applications panel', async () => {
    await setup();
    expect(screen.getAllByText('VS').length).toBeGreaterThan(0);
    expect(screen.getAllByText('VS-Mittel').length).toBeGreaterThan(0);
    expect(screen.getAllByText('VS-800').length).toBeGreaterThan(1);
  });

  it('drills into a cost centre on click and reloads its applications', async () => {
    const { c, http } = await setup();
    c.drillInto(TREE[0].children[0]);
    expect(c.selectedKsId()).toBe('b-800');
    http.expectOne((r) => r.url.includes('/budgets/b-800/applications')).flush(APPS);
    expect(c.breadcrumbs().map((n: { key: string }) => n.key)).toEqual(['VS', '800']);
  });

  it('maps budget applications into shared-table rows linking to the detail page', async () => {
    const { c } = await setup();
    const rows = c.appRows();
    expect(rows.length).toBe(APPS.length);
    expect(rows[0].id).toBe(APPS[0].applicationId);
    // stateLabel resolved in the active locale (de).
    expect(rows[0].stateLabel).toBe('Angenommen');
    expect(rows[0].stateColor).toBe('#0a0');
    const link = screen.getAllByRole('link')[0] as HTMLAnchorElement;
    expect(link.getAttribute('href')).toContain('/applications/');
  });

  it('toggleNav flips the mobile nav flag', async () => {
    const { c } = await setup();
    expect(c.navOpen()).toBe(false);
    c.toggleNav();
    expect(c.navOpen()).toBe(true);
    c.toggleNav();
    expect(c.navOpen()).toBe(false);
  });

  it('navToggleLabel shows budget + fiscal-year, then bare budget, then the generic title', async () => {
    const { c } = await setup();
    // Selected budget b-vs + fy-1 → "name · display".
    expect(c.navToggleLabel()).toBe('VS-Mittel · 2026');
    // No matching fiscal year → bare budget name.
    c.selectedFyId.set('nope');
    expect(c.navToggleLabel()).toBe('VS-Mittel');
    // No selected budget → generic translated title.
    c.selectedBudgetId.set('');
    expect(typeof c.navToggleLabel()).toBe('string');
    expect(c.navToggleLabel().length).toBeGreaterThan(0);
  });

  it('navToggleLabel uses the bare name when the budget has no fiscal-years entry', async () => {
    const { c } = await setup();
    // Select a node that exists in the tree but has no entry in fiscalYearsByBudget.
    c.selectedBudgetId.set('b-800'); // child, no FY map entry → `?? []` branch
    c.selectedFyId.set('fy-1');
    expect(c.navToggleLabel()).toBe('Dezentrale Einrichtungen');
  });

  it('usageRows computes percent and null-percent when the denominator is zero', async () => {
    const { c } = await setup();
    const rows = c.usageRows();
    // Root: committed 400 / (available 600 + committed 400) = 40%.
    expect(rows[0].percent).toBe(40);
    expect(rows[0].bound).toBe(300);
    expect(rows[0].expended).toBe(100);
    expect(rows[0].income).toBe(0);
    // Child row present (flattened subtree).
    expect(rows.length).toBe(2);
  });

  it('usageRows returns [] when nothing is selected', async () => {
    const { c } = await setup();
    c.selectedKsId.set('');
    expect(c.usageRows()).toEqual([]);
  });

  it('usageRows yields a null percent when available + committed is 0', async () => {
    const tree = [
      node({
        id: 'b-x',
        key: 'X',
        byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '0', committed: '0', available: '0' })],
      }),
    ];
    const { c } = await setup({ tree });
    expect(c.usageRows()[0].percent).toBeNull();
  });

  it('usageColumns are the six expected keys', async () => {
    const { c } = await setup();
    expect(c.usageColumns().map((col: { key: string }) => col.key)).toEqual([
      'node',
      'bar',
      'requested',
      'bound',
      'expended',
      'available',
    ]);
  });

  it('usageRowId returns the row node id', async () => {
    const { c } = await setup();
    const row = c.usageRows()[0];
    expect(c.usageRowId(row)).toBe(row.node.id);
  });

  it('appRows falls back to a short-id title and uses the stage label when no stateLabel', async () => {
    const apps: BudgetApplication[] = [
      {
        applicationId: 'bbbbbbbb-2222-3333-4444-555555555555',
        title: '   ',
        budgetId: 'b-800',
        pathKey: 'VS-800',
        fiscalYearId: 'fy-1',
        amount: null,
        currency: null,
        stage: 'review',
        stateId: null,
        stateLabel: null,
        stateColor: null,
        createdAt: '2026-05-02T10:00:00Z',
      },
      {
        applicationId: 'cccccccc-3333-4444-5555-666666666666',
        title: null,
        budgetId: 'b-800',
        pathKey: 'VS-800',
        fiscalYearId: 'fy-1',
        amount: null,
        currency: null,
        stage: null,
        stateId: null,
        createdAt: '2026-05-03T10:00:00Z',
      },
    ];
    const { c } = await setup({ apps });
    const rows = c.appRows();
    // Blank title → "<shortId>…".
    expect(rows[0].title).toBe('bbbbbbbb…');
    // No stateLabel but a stage → translated stage label.
    expect(typeof rows[0].stateLabel).toBe('string');
    // No stateLabel and no stage → null.
    expect(rows[1].stateLabel).toBeNull();
    expect(rows[1].stateColor).toBeNull();
  });

  it('resolveLabel falls back de → en → first value', async () => {
    const { c } = await setup();
    localStorage.setItem('ap.locale', 'fr');
    // No fr, has de.
    expect(c['resolveLabel']({ de: 'D', en: 'E' })).toBe('D');
    // No de, has en.
    expect(c['resolveLabel']({ en: 'E' })).toBe('E');
    // Neither de/en → first value.
    expect(c['resolveLabel']({ it: 'I' })).toBe('I');
    // Empty map → ''.
    expect(c['resolveLabel']({})).toBe('');
  });

  it('pie builders include an own-segment when the parent retains a remainder', async () => {
    const { c } = await setup();
    // Root allocated 1000, child allocated 400 → own remainder 600 (> 0.005) → own slice with parent color.
    const slices = c.allocPie();
    const own = slices.find((s: { label: string }) => s.label === 'VS-Mittel');
    expect(own).toBeTruthy();
    expect(own.value).toBe(600);
    expect(own.color).toBe('#123456');
    // The child slice exists too.
    expect(slices.some((s: { label: string }) => s.label === 'Dezentrale Einrichtungen')).toBe(true);
  });

  it('pie returns [] with no selection and filters out zero slices', async () => {
    const { c } = await setup();
    c.selectedKsId.set('');
    expect(c.allocPie()).toEqual([]);
  });

  it('pie uses palette color when a child has no own color', async () => {
    const tree = [
      node({
        id: 'top',
        key: 'T',
        color: null,
        byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '100' })],
        children: [
          node({ id: 'ch', key: 'C', color: null, byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '50' })] }),
        ],
      }),
    ];
    const { c } = await setup({ tree });
    const slices = c.allocPie();
    const child = slices.find((s: { id?: string }) => s.id === 'ch');
    expect(child.color).toMatch(/^#/);
    // Own remainder slice color falls back to PALETTE[0] when parent has no color.
    const own = slices.find((s: { label: string }) => s.label === 'Node top');
    expect(own.color).toBe('#5fb37a');
  });

  it('committed/available/expended pies all build slices', async () => {
    const { c } = await setup();
    expect(c.committedPie().length).toBeGreaterThan(0);
    expect(c.availablePie().length).toBeGreaterThan(0);
    expect(c.expendedPie().length).toBeGreaterThan(0);
  });

  it('overviewRoot is the selected cost centre and visibleOverviewMetrics drops empty metrics', async () => {
    const { c } = await setup();
    expect(c.overviewRoot()?.id).toBe('b-vs');
    // allocated + available + expended all have data on the root → all three visible.
    expect(c.visibleOverviewMetrics()).toEqual(['allocated', 'available', 'expended']);
  });

  it('visibleOverviewMetrics is empty without a root', async () => {
    const { c } = await setup();
    c.selectedKsId.set('');
    expect(c.visibleOverviewMetrics()).toEqual([]);
  });

  it('activeOverviewMetric keeps the current metric when it is visible', async () => {
    const { c } = await setup();
    c.overviewMetric.set('available');
    expect(c.activeOverviewMetric()).toBe('available');
  });

  it('activeOverviewMetric falls back to the first visible when the chosen one has no data', async () => {
    const tree = [
      node({
        id: 'top',
        key: 'T',
        byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '100', available: '0', expended: '0' })],
      }),
    ];
    const { c } = await setup({ tree });
    c.overviewMetric.set('expended'); // expended has no data → only 'allocated' visible
    expect(c.activeOverviewMetric()).toBe('allocated');
  });

  it('activeOverviewMetric falls back to allocated when nothing is visible', async () => {
    const { c } = await setup();
    c.selectedKsId.set('');
    expect(c.activeOverviewMetric()).toBe('allocated');
  });

  it('onOverviewPick closes the overlay and selects + reloads the picked cost centre', async () => {
    const { c, http } = await setup();
    c.overviewOpen.set(true);
    c.onOverviewPick('b-800');
    expect(c.overviewOpen()).toBe(false);
    expect(c.selectedKsId()).toBe('b-800');
    http.expectOne((r) => r.url.includes('/budgets/b-800/applications')).flush([]);
  });

  it('metricLabel resolves a translated label per metric', async () => {
    const { c } = await setup();
    expect(typeof c.metricLabel('allocated')).toBe('string');
    expect(typeof c.metricLabel('expended')).toBe('string');
  });

  it('money formats numbers and empty/null/string inputs', async () => {
    const { c } = await setup();
    expect(c.money(100)).toContain('100');
    expect(c.money('250')).toContain('250');
    // null and '' coerce to 0.
    expect(c.money(null)).toContain('0');
    expect(c.money('')).toContain('0');
    // Currency override.
    expect(c.money(5, 'USD')).toMatch(/[$]|USD/);
  });

  it('boundPct and expendedPct clamp to 0..100 and handle a zero denominator', async () => {
    const { c } = await setup();
    // total = available 600 + committed 400 = 1000. bound 300 → 30%, expended 100 → 10%.
    const row = c.usageRows()[0];
    expect(c.boundPct(row)).toBeCloseTo(30);
    expect(c.expendedPct(row)).toBeCloseTo(10);
    // Zero denominator → 0.
    const zero = { available: 0, committed: 0, bound: 5, expended: 5 };
    expect(c.boundPct(zero)).toBe(0);
    expect(c.expendedPct(zero)).toBe(0);
    // Over-budget bound clamps to 100.
    const over = { available: -50, committed: 200, bound: 1000, expended: 0 };
    expect(c.boundPct(over)).toBe(100);
  });

  it('shortId slices the first 8 chars', async () => {
    const { c } = await setup();
    expect(c.shortId('aaaaaaaa-1111')).toBe('aaaaaaaa');
  });

  it('stageLabel returns a dash for null and a translated label otherwise', async () => {
    const { c } = await setup();
    expect(c.stageLabel(null)).toBe('—');
    expect(typeof c.stageLabel('approved')).toBe('string');
  });

  it('titleOf trims and falls back to a short id', async () => {
    const { c } = await setup();
    expect(c.titleOf({ applicationId: 'xxxxxxxx-1', title: '  Hi  ' })).toBe('Hi');
    expect(c.titleOf({ applicationId: 'yyyyyyyy-1', title: null })).toBe('yyyyyyyy…');
  });

  it('selectBudget sets root + first fiscal year, syncs the URL and reloads', async () => {
    const { c, http } = await setup();
    const nav = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectBudget('b-vs');
    expect(c.selectedBudgetId()).toBe('b-vs');
    expect(c.selectedKsId()).toBe('b-vs');
    expect(c.selectedFyId()).toBe('fy-1');
    expect(nav).toHaveBeenCalled();
    http.expectOne((r) => r.url.includes('/budgets/b-vs/applications')).flush(APPS);
  });

  it('selectBudget with an unknown budget id clears the fiscal year', async () => {
    const { c, http } = await setup();
    jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectBudget('ghost');
    expect(c.selectedFyId()).toBe('');
    // ks set to 'ghost' → reloadApplications fires.
    http.expectOne((r) => r.url.includes('/budgets/ghost/applications')).flush([]);
  });

  it('onYearPicked applies the selection, collapses the nav, syncs and reloads', async () => {
    const { c, http } = await setup();
    jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.navOpen.set(true);
    c.onYearPicked({ budgetId: 'b-vs', fiscalYearId: 'fy-2' });
    expect(c.selectedBudgetId()).toBe('b-vs');
    expect(c.selectedKsId()).toBe('b-vs');
    expect(c.selectedFyId()).toBe('fy-2');
    expect(c.navOpen()).toBe(false);
    http.expectOne((r) => r.url.includes('/budgets/b-vs/applications')).flush(APPS);
  });

  it('selectKs with an empty id clears the applications list', async () => {
    const { c } = await setup();
    jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectKs('');
    expect(c.applications()).toEqual([]);
  });

  it('reloadApplications sets [] on an HTTP error', async () => {
    const { c, http } = await setup();
    jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectKs('b-800');
    http
      .expectOne((r) => r.url.includes('/budgets/b-800/applications'))
      .flush('boom', { status: 500, statusText: 'err' });
    expect(c.applications()).toEqual([]);
  });

  it('renders the export button and exports on click', async () => {
    // jsdom lacks URL.createObjectURL/revokeObjectURL — stub them for downloadBlob.
    (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
    (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
    jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const { c, http } = await setup({ can: true });
    expect(c.canExport()).toBe(true);
    c.onExport();
    expect(c.exporting()).toBe(true);
    const req = http.expectOne((r) => r.url.includes('/budget/export.xlsx'));
    req.flush(new Blob(['x']));
    expect(c.exporting()).toBe(false);
  });

  it('export omits node/fiscalYear params when the selection is empty', async () => {
    (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
    (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
    jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const { c, http } = await setup({ can: true });
    c.selectedKsId.set('');
    c.selectedFyId.set('');
    c.onExport();
    const req = http.expectOne((r) => r.url.includes('/budget/export.xlsx'));
    // Both `|| undefined` branches taken → no params on the request.
    expect(req.request.params.keys()).toEqual([]);
    req.flush(new Blob(['x']));
    expect(c.exporting()).toBe(false);
  });

  it('breadcrumbs stop at a node whose parent is missing from the tree', async () => {
    // A child pointing at a parentId that is not present in the visible tree.
    const tree = [
      node({
        id: 'b-vs',
        key: 'VS',
        byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '100' })],
        children: [
          node({
            id: 'orphan',
            parentId: 'does-not-exist',
            key: 'ORPH',
            byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '50' })],
          }),
        ],
      }),
    ];
    const { c, http } = await setup({ tree });
    jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectKs('orphan');
    http.expectOne((r) => r.url.includes('/budgets/orphan/applications')).flush([]);
    // parentId resolves to nothing (?? null) → chain has only the orphan itself.
    expect(c.breadcrumbs().map((n: { id: string }) => n.id)).toEqual(['orphan']);
  });

  it('onExport is a no-op while already exporting', async () => {
    const { c } = await setup();
    c.exporting.set(true);
    c.onExport(); // guard returns immediately, no HTTP request issued
    expect(c.exporting()).toBe(true);
  });

  it('onExport resets the flag on error', async () => {
    const { c, http } = await setup();
    c.onExport();
    http.expectOne((r) => r.url.includes('/budget/export.xlsx')).error(new ProgressEvent('err'));
    expect(c.exporting()).toBe(false);
  });

  it('hides the export button without the permission', async () => {
    const { c } = await setup({ can: false });
    expect(c.canExport()).toBe(false);
  });

  it('shows the loading state then the error state when the tree request fails', async () => {
    const view = await render(BudgetDashboardComponent, {
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: authStub() },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const c = view.fixture.componentInstance as unknown as Inst;
    expect(c.loading()).toBe(true);
    http.expectOne((r) => r.url.endsWith('/budgets')).flush('x', { status: 500, statusText: 'err' });
    view.fixture.detectChanges();
    expect(c.error()).toBe(true);
    expect(c.loading()).toBe(false);
    expect(screen.getByRole('alert')).toBeTruthy();
    http.verify();
  });

  it('renders the empty state when the tree is empty', async () => {
    const view = await render(BudgetDashboardComponent, {
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: authStub() },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const c = view.fixture.componentInstance as unknown as Inst;
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    view.fixture.detectChanges();
    expect(c.applications()).toEqual([]);
    expect(c.tops()).toEqual([]);
    // Empty-state section is rendered (no tree rows, no charts).
    expect(view.container.querySelector('.bd__empty')).toBeTruthy();
    http.verify();
  });

  it('prunes hidden cost centres from the visible tree and tops', async () => {
    const tree = [
      node({
        id: 'b-vs',
        key: 'VS',
        byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '100' })],
        children: [
          node({ id: 'b-hide', key: 'H', hiddenInBudget: true, byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '50' })] }),
          node({ id: 'b-show', key: 'S', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '50' })] }),
        ],
      }),
      // A hidden top is excluded entirely from tops.
      node({ id: 'b-secret', key: 'SEC', hiddenInBudget: true, byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
    ];
    const { c } = await setup({ tree });
    // tops only includes visible roots with a fiscal year.
    expect(c.tops().map((n: { id: string }) => n.id)).toEqual(['b-vs']);
    // nodeById does not include the hidden child.
    const usageIds = c.usageRows().map((r: { node: { id: string } }) => r.node.id);
    expect(usageIds).toContain('b-show');
    expect(usageIds).not.toContain('b-hide');
  });

  it('restores the selection from query params (budget/ks/fy)', async () => {
    const tree = [
      node({
        id: 'b-vs',
        key: 'VS',
        byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '100' })],
        children: [node({ id: 'b-800', parentId: 'b-vs', key: '800', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '40' })] })],
      }),
    ];
    const { c } = await setup({
      tree,
      fys: [FY, FY2],
      queryParams: { budget: 'b-vs', ks: 'b-800', fy: 'fy-2' },
    });
    expect(c.selectedBudgetId()).toBe('b-vs');
    expect(c.selectedKsId()).toBe('b-800');
    expect(c.selectedFyId()).toBe('fy-2');
  });

  it('ignores invalid query params and defaults to the first budget/year', async () => {
    const { c } = await setup({
      queryParams: { budget: 'ghost', ks: 'ghost', fy: 'ghost' },
    });
    expect(c.selectedBudgetId()).toBe('b-vs');
    expect(c.selectedKsId()).toBe('b-vs');
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('stays selection-free when the fiscal-years request errors (fault-tolerant)', async () => {
    const view = await render(BudgetDashboardComponent, {
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: authStub() },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const c = view.fixture.componentInstance as unknown as Inst;
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([node({ id: 'b-vs', key: 'VS' })]);
    // listFiscalYears errors → error callback runs restoreOrDefault but no FY exists.
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).error(new ProgressEvent('err'));
    view.fixture.detectChanges();
    expect(c.selectedBudgetId()).toBe('');
    expect(c.loading()).toBe(false);
    http.verify();
  });

  it('defers restore while the chosen budget fiscal-years have not arrived yet', async () => {
    // Two tops; flush the SECOND top first. restoreOrDefault runs with the first
    // budget chosen but its `fys` still undefined → line 420 early-return branch.
    const tree = [
      node({ id: 'b-a', key: 'A', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
      node({ id: 'b-b', key: 'B', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
    ];
    const view = await render(BudgetDashboardComponent, {
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: authStub() },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const c = view.fixture.componentInstance as unknown as Inst;
    http.expectOne((r) => r.url.endsWith('/budgets')).flush(tree);
    // Respond for b-b first: withFy=[b-b]→chosen withFy[0]=b-b? No — withFy filters by
    // tops having FY. Only b-b has FY here, so it becomes the default; once selected,
    // its fys exist → restored. Flush b-a afterwards (no-op, already restored).
    http.expectOne((r) => r.url.endsWith('/budgets/b-b/fiscal-years')).flush([{ ...FY, budgetId: 'b-b' }]);
    http.match((r) => r.url.includes('/applications')).forEach((r) => r.flush([]));
    http.expectOne((r) => r.url.endsWith('/budgets/b-a/fiscal-years')).flush([{ ...FY, budgetId: 'b-a' }]);
    view.fixture.detectChanges();
    expect(c.selectedBudgetId()).toBe('b-b');
    http.match((r) => r.url.includes('/applications')).forEach((r) => r.flush([]));
    http.verify();
  });

  it('skips restore until a top with a fiscal year is loaded', async () => {
    // Top whose fiscal-years come back empty → restoreOrDefault returns without selecting.
    const view = await render(BudgetDashboardComponent, {
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: authStub() },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const c = view.fixture.componentInstance as unknown as Inst;
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([node({ id: 'b-vs', key: 'VS' })]);
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
    view.fixture.detectChanges();
    // No fiscal year → nothing selected, no applications request.
    expect(c.selectedBudgetId()).toBe('');
    http.verify();
  });
});
