import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { BudgetDashboardComponent } from './budget-dashboard.component';
import type {
  BudgetAllocationView,
  BudgetTreeNode,
  FiscalYear,
} from './budget-tree.api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Inst = any;

/** Full allocation view. All fields are set, so Number(undefined) never gives NaN. */
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


function authStub(canValue = true): AuthService {
  return { can: (_p: string) => canValue } as unknown as AuthService;
}

interface SetupOpts {
  tree?: BudgetTreeNode[];
  fys?: FiscalYear[];
  can?: boolean;
  queryParams?: Record<string, string>;
}

async function setup(opts: SetupOpts = {}) {
  const tree = opts.tree ?? TREE;
  const fys = opts.fys ?? [FY];
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
  const tops = tree.filter((n) => !n.hiddenInBudget);
  for (const top of tops) {
    http.expectOne((r) => r.url.endsWith(`/budgets/${top.id}/fiscal-years`)).flush(fys);
  }
  // The page does not list applications: that job belongs to /applications, which the
  // cross-link opens. No request goes out for them.
  view.fixture.detectChanges();
  return { ...view, http, c: view.fixture.componentInstance as unknown as Inst };
}

describe('BudgetDashboardComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('shows the cost-centre subtree with bars', async () => {
    await setup();
    expect(screen.getAllByText('VS').length).toBeGreaterThan(0);
    expect(screen.getAllByText('VS-Mittel').length).toBeGreaterThan(0);
    // Once, in the usage tree. A second occurrence would mean something below repeats
    // the cost-centre path per row.
    expect(screen.getAllByText('VS-800').length).toBe(1);
  });

  it('drills into a cost centre on click', async () => {
    const { c } = await setup();
    c.drillInto(TREE[0].children[0]);
    expect(c.selectedKsId()).toBe('b-800');
    expect(c.breadcrumbs().map((n: { key: string }) => n.key)).toEqual(['VS', '800']);
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
    // The child row is there too, because the subtree is flattened.
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
    // Root allocated 1000, child allocated 400 → own remainder 600 (> 0.005), so the
    // own slice appears in the parent color.
    const slices = c.allocPie();
    const own = slices.find((s: { label: string }) => s.label === 'VS-Mittel');
    expect(own).toBeTruthy();
    expect(own.value).toBe(600);
    expect(own.color).toBe('#123456');
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
    // The own remainder slice falls back to PALETTE[0] when the parent has no color.
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
    // The root has data for allocated, available and expended, so all three show.
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
    const { c } = await setup();
    c.overviewOpen.set(true);
    c.onOverviewPick('b-800');
    expect(c.overviewOpen()).toBe(false);
    expect(c.selectedKsId()).toBe('b-800');
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
    expect(c.money(5, 'USD')).toMatch(/[$]|USD/);
  });

  it('boundPct and expendedPct clamp to 0..100 and handle a zero denominator', async () => {
    const { c } = await setup();
    // The total is 1000 (available 600 + committed 400). Bound 300 gives 30% and
    // expended 100 gives 10%.
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
    const { c } = await setup();
    const nav = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectBudget('b-vs');
    expect(c.selectedBudgetId()).toBe('b-vs');
    expect(c.selectedKsId()).toBe('b-vs');
    expect(c.selectedFyId()).toBe('fy-1');
    expect(nav).toHaveBeenCalled();
  });

  it('selectBudget with an unknown budget id clears the fiscal year', async () => {
    const { c } = await setup();
    jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectBudget('ghost');
    expect(c.selectedFyId()).toBe('');
    // ks set to 'ghost' → reloadApplications fires.
  });

  it('onYearPicked applies the selection, collapses the nav, syncs and reloads', async () => {
    const { c } = await setup();
    jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.navOpen.set(true);
    c.onYearPicked({ budgetId: 'b-vs', fiscalYearId: 'fy-2' });
    expect(c.selectedBudgetId()).toBe('b-vs');
    expect(c.selectedKsId()).toBe('b-vs');
    expect(c.selectedFyId()).toBe('fy-2');
    expect(c.navOpen()).toBe(false);
  });



  it('renders the export button and exports on click', async () => {
    // jsdom has no URL.createObjectURL and no URL.revokeObjectURL. Stub both for
    // downloadBlob.
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
    // Both `|| undefined` branches run, so the request carries no params.
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
    const { c } = await setup({ tree });
    jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectKs('orphan');
    // parentId resolves to nothing (?? null), so the chain holds only the orphan.
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
    expect(c.tops()).toEqual([]);
    expect(view.container.querySelector('.bd__empty')).toBeTruthy();
    http.verify();
  });

  it('never claims the budget is empty while it is still loading', async () => {
    // "There are no cost centres" and "they have not arrived yet" are different claims.
    // The page used to render the empty panel on every load, because the template asked
    // whether the tree was empty and never whether it was still loading.
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
    view.fixture.detectChanges();

    expect(c.loading()).toBe(true);
    expect(view.container.querySelector('.bd__empty')).toBeNull();
    expect(view.container.querySelector('.skel')).toBeTruthy();
    expect(view.container.querySelector('[aria-busy="true"]')).toBeTruthy();

    // Only once the answer really is "none" does the empty state appear.
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    view.fixture.detectChanges();
    expect(view.container.querySelector('.bd__empty')).toBeTruthy();
    expect(view.container.querySelector('.skel')).toBeNull();
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
    // listFiscalYears fails, so the error callback runs restoreOrDefault. No fiscal
    // year exists at that point.
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).error(new ProgressEvent('err'));
    view.fixture.detectChanges();
    expect(c.selectedBudgetId()).toBe('');
    expect(c.loading()).toBe(false);
    http.verify();
  });

  it('defers restore while the chosen budget fiscal-years have not arrived yet', async () => {
    // Two tops. Flush the SECOND top first. restoreOrDefault then runs with the
    // first budget chosen but its `fys` still undefined, which takes the
    // early-return branch.
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
    // Respond for b-b first. withFy keeps only the tops that have a fiscal year.
    // Only b-b has one here, so it becomes the default. Its fys then exist and the
    // restore runs. The later flush for b-a does nothing.
    http.expectOne((r) => r.url.endsWith('/budgets/b-b/fiscal-years')).flush([{ ...FY, budgetId: 'b-b' }]);
    http.expectOne((r) => r.url.endsWith('/budgets/b-a/fiscal-years')).flush([{ ...FY, budgetId: 'b-a' }]);
    view.fixture.detectChanges();
    expect(c.selectedBudgetId()).toBe('b-b');
    http.verify();
  });

  it('skips restore until a top with a fiscal year is loaded', async () => {
    // The fiscal years of the top come back empty, so restoreOrDefault returns
    // without a selection.
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
    // Without a fiscal year nothing is selected.
    expect(c.selectedBudgetId()).toBe('');
    http.verify();
  });
});
