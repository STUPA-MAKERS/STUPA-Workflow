import { BehaviorSubject } from 'rxjs';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import { axe } from 'jest-axe';
import { AuthService } from '@core/auth/auth.service';
import { BudgetDashboardComponent, utilisation } from './budget-dashboard.component';
import type {
  BudgetAllocationView,
  BudgetApplication,
  BudgetTreeNode,
  FiscalYear,
} from './budget-tree.api';
import { PALETTE, shadeColor } from './budget-color.util';

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

/**
 * VS (1000) → 800 (400, blue) → 810 (100, inherits blue)
 *          → 900 (300, no colour)
 * The root keeps 300 for itself.
 */
const TREE: BudgetTreeNode[] = [
  node({
    id: 'b-vs',
    key: 'VS',
    pathKey: 'VS',
    name: 'VS-Mittel',
    byFiscalYear: [
      alloc({ fiscalYearId: 'fy-1', allocated: '1000', bound: '300', expended: '100', committed: '400', income: '50', requested: '70', available: '650' }),
    ],
    children: [
      node({
        id: 'b-800',
        parentId: 'b-vs',
        key: '800',
        pathKey: 'VS-800',
        name: 'Dezentrale Einrichtungen',
        color: '#0075bf',
        byFiscalYear: [
          alloc({ fiscalYearId: 'fy-1', allocated: '400', bound: '60', expended: '40', committed: '100', requested: '20', available: '300' }),
        ],
        children: [
          node({
            id: 'b-810',
            parentId: 'b-800',
            key: '810',
            pathKey: 'VS-800-810',
            name: 'Werkstatt',
            byFiscalYear: [
              alloc({ fiscalYearId: 'fy-1', allocated: '100', bound: '10', expended: '30', committed: '40', available: '60' }),
            ],
          }),
        ],
      }),
      node({
        id: 'b-900',
        parentId: 'b-vs',
        key: '900',
        pathKey: 'VS-900',
        name: 'Rücklage',
        byFiscalYear: [
          alloc({ fiscalYearId: 'fy-1', allocated: '300', bound: '250', expended: '100', committed: '350', available: '-50' }),
        ],
      }),
    ],
  }),
];

function app(over: Partial<BudgetApplication> & { applicationId: string }): BudgetApplication {
  return {
    applicationId: over.applicationId,
    title: 'title' in over ? (over.title ?? null) : `Antrag ${over.applicationId}`,
    budgetId: 'budgetId' in over ? (over.budgetId ?? null) : 'b-800',
    pathKey: 'pathKey' in over ? (over.pathKey ?? null) : 'VS-800',
    fiscalYearId: over.fiscalYearId ?? 'fy-1',
    amount: over.amount === undefined ? '120.00' : over.amount,
    currency: over.currency ?? 'EUR',
    stateId: over.stateId ?? null,
    stateLabel: 'stateLabel' in over ? over.stateLabel : { de: 'In Prüfung', en: 'In review' },
    stateColor: over.stateColor ?? '#d9a400',
    createdAt: over.createdAt ?? '2026-05-01T10:00:00Z',
  };
}

const ALL_PERMS = ['budget.view', 'budget.structure', 'budget.book', 'budget.export'];

function authStub(perms: string[] = ALL_PERMS): AuthService {
  const can = (p: string): boolean => perms.includes(p);
  return { can, canAny: (...ps: string[]) => ps.some(can) } as unknown as AuthService;
}

/** Let `matchMedia` report a wide viewport (or not), and a phone. jsdom has none of its own. */
function setViewport(wide: boolean, phone = false): void {
  window.matchMedia = ((query: string) => ({
    matches:
      (wide && query.includes('min-width: 1200px')) || (phone && query === '(max-width: 768px)'),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

interface SetupOpts {
  tree?: BudgetTreeNode[];
  fys?: FiscalYear[];
  perms?: string[];
  queryParams?: Record<string, string>;
  apps?: BudgetApplication[];
  wide?: boolean;
  phone?: boolean;
}

function providers(opts: SetupOpts, params = new BehaviorSubject(convertToParamMap({}))) {
  return [
    provideHttpClient(),
    provideHttpClientTesting(),
    provideRouter([]),
    { provide: AuthService, useValue: authStub(opts.perms) },
    {
      provide: ActivatedRoute,
      useValue: {
        snapshot: { queryParamMap: params.value },
        // The page follows the URL after the first restore, so the stub needs the stream
        // and not only the snapshot.
        queryParamMap: params,
      },
    },
  ];
}

/** Answer every outstanding applications request of the sheet. */
function flushApps(http: HttpTestingController, apps: BudgetApplication[] = []): void {
  for (const req of http.match((r) => /\/budgets\/[^/]+\/applications$/.test(r.url))) {
    req.flush(apps);
  }
}

async function setup(opts: SetupOpts = {}) {
  setViewport(opts.wide ?? true, opts.phone);
  const tree = opts.tree ?? TREE;
  const fys = opts.fys ?? [FY];
  const params = new BehaviorSubject(convertToParamMap(opts.queryParams ?? {}));
  const view = await render(BudgetDashboardComponent, { providers: providers(opts, params) });
  const http = TestBed.inject(HttpTestingController);
  http.expectOne((r) => r.url.endsWith('/budgets')).flush(tree);
  const tops = tree.filter((n) => !n.hiddenInBudget);
  for (const top of tops) {
    http.expectOne((r) => r.url.endsWith(`/budgets/${top.id}/fiscal-years`)).flush(fys);
  }
  flushApps(http, opts.apps);
  view.fixture.detectChanges();
  return { ...view, http, params, c: view.fixture.componentInstance as unknown as Inst };
}

/** Render without answering anything, for the loading and error paths. */
async function bare(opts: SetupOpts = {}) {
  setViewport(opts.wide ?? true, opts.phone);
  const view = await render(BudgetDashboardComponent, { providers: providers(opts) });
  const http = TestBed.inject(HttpTestingController);
  return { ...view, http, c: view.fixture.componentInstance as unknown as Inst };
}

describe('BudgetDashboardComponent', () => {
  const realMatchMedia = window.matchMedia;
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    const http = TestBed.inject(HttpTestingController);
    flushApps(http);
    http.verify();
    window.matchMedia = realMatchMedia;
  });

  // ------------------------------------------------------------------ tree

  describe('tree', () => {
    it('scrolls only the tree and fades an end only where more rows are', async () => {
      const view = await setup();
      const tree = view.container.querySelector('.bd__pane .bd__tree') as HTMLElement;
      // The year, the overview and the search are outside the scrolling list.
      expect(tree.querySelector('app-search-pill, .bd-chip')).toBeNull();
      // The pane sits on the page, so the search field keeps its own surface.
      expect(view.container.querySelector('.bd__pane .bd__paneBody')).not.toHaveClass('bd__paneBody--side');
      const geometry = (scrollHeight: number, scrollTop: number) => {
        Object.defineProperty(tree, 'scrollHeight', { value: scrollHeight, configurable: true });
        Object.defineProperty(tree, 'clientHeight', { value: 300, configurable: true });
        Object.defineProperty(tree, 'scrollTop', { value: scrollTop, configurable: true });
        tree.dispatchEvent(new Event('scroll'));
      };
      const fades = () => [tree.classList.contains('is-fade-start'), tree.classList.contains('is-fade-end')];
      geometry(300, 0);
      expect(fades()).toEqual([false, false]);
      geometry(900, 0);
      expect(fades()).toEqual([false, true]);
      geometry(900, 300);
      expect(fades()).toEqual([true, true]);
      geometry(900, 600);
      expect(fades()).toEqual([true, false]);
    });

    it('scrolls the sheet inside itself on the wide layout and fades only the content', async () => {
      const view = await setup();
      const sheet = view.container.querySelector('article.bd__sheet') as HTMLElement;
      const body = sheet.querySelector(':scope > .bd__sheetBody') as HTMLElement;
      // The bar stays on top; the body holds the rest of the content, so the card keeps
      // its background unmasked.
      expect(Array.from(sheet.children).map((el) => el.tagName.toLowerCase())).toEqual(['app-sheet-bar', 'div']);
      expect(body.querySelector('.bd__figs')).toBeTruthy();
      Object.defineProperty(body, 'scrollHeight', { value: 1200, configurable: true });
      Object.defineProperty(body, 'clientHeight', { value: 800, configurable: true });
      Object.defineProperty(body, 'scrollTop', { value: 0, configurable: true });
      body.dispatchEvent(new Event('scroll'));
      expect(body).toHaveClass('is-fade-end');
      expect(body).not.toHaveClass('is-fade-start');
      expect(sheet).not.toHaveClass('is-fade-end');
    });

    it('scrolls a row into view when it gets the keyboard focus', async () => {
      const view = await setup();
      const row = view.container.querySelector('.bd__tree .tn') as HTMLElement;
      const scroll = jest.fn();
      row.scrollIntoView = scroll;
      (row.querySelector('.tn__main') as HTMLButtonElement).focus();
      expect(scroll).toHaveBeenCalledWith({ block: 'nearest' });
    });

    it('shows the root open with its children, each with its allocation', async () => {
      const view = await setup();
      const tree = within(view.container.querySelector('.bd__tree') as HTMLElement);
      expect(tree.getByText('VS-Mittel')).toBeTruthy();
      expect(tree.getByText('Dezentrale Einrichtungen')).toBeTruthy();
      expect(tree.getByText('Rücklage')).toBeTruthy();
      // 800 is closed, so its child is not in the tree yet.
      expect(tree.queryByText('Werkstatt')).toBeNull();
      expect(tree.getAllByText(/1\.000\s€/).length).toBe(1);
      const current = view.container.querySelector('.tn--on .tn__name');
      expect(current?.textContent).toContain('VS-Mittel');
    });

    it('gives a node its own or inherited colour and draws the swatch only then', async () => {
      const view = await setup({ queryParams: { ks: 'b-810' } });
      const rows = view.c.treeRows() as { node: { id: string }; color: string; swatch: boolean }[];
      const row = (id: string) => rows.find((r) => r.node.id === id);
      expect(row('b-800')?.color).toBe('#0075bf');
      // O19: the colour of the faculty above.
      expect(row('b-810')?.color).toBe('#0075bf');
      // No colour of its own or above: the palette colour of its position (gaps D6).
      expect(row('b-vs')?.color).toBe(PALETTE[0]);
      expect(row('b-900')?.color).toBe(PALETTE[1]);
      expect(rows.map((r) => [r.node.id, r.swatch])).toEqual([
        ['b-vs', false],
        ['b-800', true],
        ['b-810', true],
        ['b-900', false],
      ]);
      expect(view.container.querySelectorAll('.tn__swatch').length).toBe(2);
    });

    it('draws a cost centre in one colour in the tree, the chart and the bars', async () => {
      const { c } = await setup();
      const tree = new Map(
        (c.treeRows() as { node: { id: string }; color: string }[]).map((r) => [r.node.id, r.color]),
      );
      const pie = new Map(
        (c.distribution() as { id?: string; color: string }[])
          .filter((s) => s.id)
          .map((s) => [s.id, s.color]),
      );
      const bars = new Map(
        (c.usageRows() as { node: { id: string }; color: string }[]).map((r) => [r.node.id, r.color]),
      );
      for (const id of ['b-800', 'b-900']) {
        expect(pie.get(id)).toBe(tree.get(id));
        expect(bars.get(id)).toBe(tree.get(id));
      }
      // The node without any colour is the case that drifted apart before.
      expect(tree.get('b-900')).toBe(PALETTE[1]);
    });

    it('opens the path to a cost centre the URL names', async () => {
      const view = await setup({ queryParams: { ks: 'b-810' } });
      const tree = within(view.container.querySelector('.bd__tree') as HTMLElement);
      expect(tree.getByText('Werkstatt')).toBeTruthy();
      expect(view.container.querySelector('.tn--on .tn__name')?.textContent).toContain('Werkstatt');
    });

    it('opens and closes a node with its chevron', async () => {
      const view = await setup();
      const btn = screen.getByRole('button', { name: 'Dezentrale Einrichtungen aufklappen' });
      expect(btn.getAttribute('aria-expanded')).toBe('false');
      btn.click();
      view.fixture.detectChanges();
      expect(screen.getByText('Werkstatt')).toBeTruthy();
      screen.getByRole('button', { name: 'Dezentrale Einrichtungen zuklappen' }).click();
      view.fixture.detectChanges();
      expect(screen.queryByText('Werkstatt')).toBeNull();
    });

    it('filters the tree by name, key or path and keeps the way to every hit', async () => {
      const view = await setup();
      const c = view.fixture.componentInstance as unknown as Inst;
      c.query.set('werk');
      view.fixture.detectChanges();
      const names = (c.treeRows() as { node: { name: string } }[]).map((r) => r.node.name);
      expect(names).toEqual(['VS-Mittel', 'Dezentrale Einrichtungen', 'Werkstatt']);
      c.query.set('VS-900');
      expect((c.treeRows() as { node: { id: string } }[]).map((r) => r.node.id)).toEqual(['b-vs', 'b-900']);
      c.query.set('gibt es nicht');
      view.fixture.detectChanges();
      expect(screen.getByText('Keine Kostenstelle gefunden.')).toBeTruthy();
    });

    it('draws the utilisation bar of a node in red when it is overdrawn', async () => {
      const { c } = await setup();
      const rows = c.treeRows() as { node: { id: string }; segments: { tone: string }[]; percent: number | null }[];
      const r900 = rows.find((r) => r.node.id === 'b-900')!;
      expect(r900.segments[0].tone).toBe('error');
      // 350 committed of 300 → 117 %.
      expect(r900.percent).toBe(117);
    });

    it('selects a cost centre from the tree, opens it and loads its applications', async () => {
      const { c, http, fixture } = await setup();
      const nav = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      within(fixture.nativeElement.querySelector('.bd__tree'))
        .getByRole('button', { name: /Rücklage/ })
        .click();
      fixture.detectChanges();
      expect(c.selectedKsId()).toBe('b-900');
      expect(nav).toHaveBeenCalled();
      const req = http.expectOne((r) => r.url.endsWith('/budgets/b-900/applications'));
      expect(req.request.params.get('fiscalYear')).toBe('fy-1');
      req.flush([]);
    });

    it('does not reload the applications when the same cost centre is picked again', async () => {
      const { c, http } = await setup();
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectKs('b-vs');
      http.expectNone((r) => r.url.endsWith('/applications'));
    });
  });

  // ------------------------------------------------------------------ figures

  describe('figures', () => {
    it('shows all six figures, Beantragt and Einnahmen included (N28)', async () => {
      const view = await setup();
      const figs = within(view.container.querySelector('.bd__figs') as HTMLElement);
      for (const label of ['Zuteilung', 'Beantragt', 'Gebunden', 'Ausgegeben', 'Einnahmen', 'Verfügbar']) {
        expect(figs.getByText(label)).toBeTruthy();
      }
      expect(figs.getByText(/^1\.000,00\s€$/)).toBeTruthy();
      expect(figs.getByText(/^70,00\s€$/)).toBeTruthy();
      expect(figs.getByText(/^300,00\s€$/)).toBeTruthy();
      expect(figs.getByText(/^100,00\s€$/)).toBeTruthy();
      expect(figs.getByText(/^50,00\s€$/)).toBeTruthy();
      expect(figs.getByText(/^650,00\s€$/)).toBeTruthy();
    });

    it('shows a negative available amount in the error colour', async () => {
      const view = await setup({ queryParams: { ks: 'b-900' } });
      const neg = view.container.querySelector('.bd__fig--main .bd__figValue');
      expect(neg?.classList).toContain('bd__neg');
    });

    it('counts a missing allocation as zero', async () => {
      const { c } = await setup();
      expect(c.figuresOf(TREE[0], 'other-year').allocated).toBe(0);
    });

  });

  // ------------------------------------------------------------------ path + actions

  describe('header', () => {
    it('puts the path in the kicker of the shared sheet bar, the actions at its end', async () => {
      const view = await setup({ queryParams: { ks: 'b-810' } });
      const bar = view.container.querySelector('article.bd__sheet > app-sheet-bar') as HTMLElement;
      expect(bar).toBeTruthy();
      // The bar sits above the scrolling body, so it stays in place.
      expect(bar.nextElementSibling).toHaveClass('bd__sheetBody');
      const kicker = bar.querySelector('.sheet-bar__kicker') as HTMLElement;
      expect(kicker.querySelector('nav.bd__crumbs')).toBeTruthy();
      expect(kicker.querySelector('nav')?.getAttribute('aria-label')).toBe(
        view.container.querySelector('nav.bd__crumbs')?.getAttribute('aria-label'),
      );
      const actions = bar.querySelector(':scope > .bd__actions') as HTMLElement;
      expect(within(actions).getByRole('button', { name: /Exportieren/ })).toBeTruthy();
      expect(within(actions).getByRole('button', { name: 'Buchungen ansehen' })).toBeTruthy();
      expect(bar.firstElementChild).toBe(kicker);
      // The title is the first line of the body, below the bar.
      expect(view.container.querySelector('.bd__sheetBody')?.firstElementChild?.id).toBe('bd-title');
    });

    it('shows the path with the key and goes up on a click', async () => {
      const view = await setup({ queryParams: { ks: 'b-810' } });
      const crumbs = within(view.container.querySelector('.bd__crumbs') as HTMLElement);
      expect(crumbs.getByText('VS-800-810')).toBeTruthy();
      expect(view.container.querySelector('#bd-title')?.textContent).toContain('Werkstatt');
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      crumbs.getByRole('button', { name: 'Dezentrale Einrichtungen' }).click();
      const c = view.fixture.componentInstance as unknown as Inst;
      expect(c.selectedKsId()).toBe('b-800');
    });

    it('stops the path at a node whose parent is not in the tree', async () => {
      const tree = [
        node({
          id: 'b-vs',
          key: 'VS',
          byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '100' })],
          children: [node({ id: 'orphan', parentId: 'does-not-exist', key: 'ORPH' })],
        }),
      ];
      const { c } = await setup({ tree });
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectKs('orphan');
      expect(c.breadcrumbs().map((n: { id: string }) => n.id)).toEqual(['orphan']);
    });

    it('opens the bookings and the applications of the cost centre', async () => {
      const view = await setup({ apps: [app({ applicationId: 'a-1' })] });
      const nav = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      screen.getByRole('button', { name: 'Buchungen ansehen' }).click();
      expect(nav).toHaveBeenCalledWith(['/expenses'], { queryParams: { budget: 'b-vs' } });
      view.fixture.detectChanges();
      screen.getByRole('button', { name: 'Alle ansehen' }).click();
      expect(nav).toHaveBeenCalledWith(['/applications'], { queryParams: { budget: 'b-vs' } });
    });

    it('exports the selection and resets the flag after the download', async () => {
      (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
      (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
      jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
      jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
      const { c, http } = await setup();
      screen.getByRole('button', { name: /Exportieren/ }).click();
      expect(c.exporting()).toBe(true);
      // A second click while it runs does nothing.
      c.onExport();
      const req = http.expectOne((r) => r.url.includes('/budget/export.xlsx'));
      expect(req.request.params.get('node')).toBe('b-vs');
      expect(req.request.params.get('fiscalYear')).toBe('fy-1');
      req.flush(new Blob(['x']));
      expect(c.exporting()).toBe(false);
    });

    it('sends no params for an empty selection and resets the flag on an error', async () => {
      const { c, http } = await setup();
      c.selectedKsId.set('');
      c.selectedFyId.set('');
      c.onExport();
      const req = http.expectOne((r) => r.url.includes('/budget/export.xlsx'));
      expect(req.request.params.keys()).toEqual([]);
      req.error(new ProgressEvent('err'));
      expect(c.exporting()).toBe(false);
    });

    it('gives a gremium-scoped reader neither the export nor the bookings', async () => {
      // A reader with a scope (viewGremiumId) and no global budget permission: the server
      // sends the sub cost centres of the scope as roots.
      const scoped = [
        node({
          id: 'b-800',
          parentId: 'b-vs',
          key: '800',
          pathKey: 'VS-800',
          name: 'Dezentrale Einrichtungen',
          viewGremiumId: 'g-1',
          byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '400', committed: '100', available: '300' })],
        }),
      ];
      const view = await setup({ tree: scoped, perms: [] });
      const c = view.fixture.componentInstance as unknown as Inst;
      expect(c.tops().map((n: { id: string }) => n.id)).toEqual(['b-800']);
      expect(c.selectedKsId()).toBe('b-800');
      expect(screen.queryByRole('button', { name: /Exportieren/ })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Buchungen ansehen' })).toBeNull();
      // Its figures are still there.
      expect(within(view.container.querySelector('.bd__figs') as HTMLElement).getByText(/^400,00\s€$/)).toBeTruthy();
    });
  });

  // ------------------------------------------------------------------ distribution

  describe('distribution', () => {
    it('splits the figure over the sub cost centres and adds what the node keeps', async () => {
      const { c } = await setup();
      const slices = c.distribution() as { label: string; value: number; color: string; id?: string }[];
      expect(slices.map((s) => [s.id ?? null, s.value])).toEqual([
        ['b-800', 400],
        ['b-900', 300],
        [null, 300],
      ]);
      expect(slices[0].color).toBe('#0075bf');
      // No colour of its own or above: the palette colour of its position.
      expect(slices[1].color).toBe(PALETTE[1]);
      expect(slices[2].label).toBe('VS-Mittel (nicht verteilt)');
      expect(slices[2].color).toBe('var(--color-text-subtle)');
    });

    it('switches the figure and drops empty slices', async () => {
      const view = await setup();
      const c = view.fixture.componentInstance as unknown as Inst;
      (view.container.querySelector('.bd__secHead app-filter-select button') as HTMLElement).click();
      view.fixture.detectChanges();
      const list = screen.getByRole('listbox', { name: 'Kennzahl' });
      within(list).getByRole('option', { name: c.metricLabel('requested') }).click();
      view.fixture.detectChanges();
      expect(c.metric()).toBe('requested');
      expect(screen.queryByRole('listbox')).toBeNull();
      // 800 asked for 20, 900 for nothing, the root holds 50 more.
      expect(c.distribution().map((s: { value: number }) => s.value)).toEqual([20, 50]);
    });

    it('shades children that share an inherited colour', async () => {
      const tree = [
        node({
          id: 'b-vs',
          color: '#0075bf',
          byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '30' })],
          children: [
            node({ id: 'a', parentId: 'b-vs', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
            node({ id: 'b', parentId: 'b-vs', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '20' })] }),
          ],
        }),
      ];
      const { c } = await setup({ tree });
      expect(c.distribution().map((s: { color: string }) => s.color)).toEqual([
        '#0075bf',
        shadeColor('#0075bf', 1),
      ]);
    });

    it('leaves the chart out for a cost centre without sub cost centres', async () => {
      const view = await setup({ queryParams: { ks: 'b-900' } });
      expect(screen.queryByText('Verteilung')).toBeNull();
      expect(view.container.querySelector('.bd__cols--single')).toBeTruthy();
      const c = view.fixture.componentInstance as unknown as Inst;
      expect(c.distribution()).toEqual([]);
    });

    it('drills into a sub cost centre from the chart', async () => {
      const { c } = await setup();
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectKs('b-800');
      expect(c.selectedKsId()).toBe('b-800');
    });
  });

  // ------------------------------------------------------------------ utilisation

  describe('utilisation per budget', () => {
    it('lists the sub cost centres with requested, percent and available', async () => {
      const view = await setup();
      const c = view.fixture.componentInstance as unknown as Inst;
      const rows = c.usageRows();
      expect(rows.map((r: { node: { id: string } }) => r.node.id)).toEqual(['b-800', 'b-900']);
      // 800: committed 100 of 400 → 25 %.
      expect(rows[0].percent).toBe(25);
      expect(rows[0].segments).toEqual([
        { value: 40, tone: 'filled' },
        { value: 60, tone: 'second' },
      ]);
      expect(rows[0].total).toBe(400);
      expect(rows[0].color).toBe('#0075bf');
      // 900 is overdrawn.
      expect(rows[1].segments.map((s: { tone: string }) => s.tone)).toEqual(['error', 'error']);
      const list = within(view.container.querySelector('.bd__usage') as HTMLElement);
      // The column, and the line below the name that a phone shows instead.
      expect(list.getAllByText(/^20\s€$/)).toHaveLength(2);
      expect(list.getByText('25 %')).toBeTruthy();
      expect(list.getByText(/^-50\s€$/).classList).toContain('bd__neg');
      // No requested amount reads as a dash.
      expect(list.getAllByText('–').length).toBeGreaterThan(0);
    });

    it('shows the cost centre itself when it has no sub cost centres', async () => {
      const { c } = await setup({ queryParams: { ks: 'b-810' } });
      const rows = c.usageRows();
      expect(rows.map((r: { node: { id: string } }) => r.node.id)).toEqual(['b-810']);
      // The inherited colour of the faculty above.
      expect(rows[0].color).toBe('#0075bf');
    });

    it('names the spent and the bound amount in the bar label and the row tooltip', async () => {
      const view = await setup();
      const expected =
        /^Ausgegeben: 40,00\s€ · Gebunden: 60,00\s€ · von 400,00\s€ \(25 % ausgelastet\)$/;
      const bar = view.container.querySelector('.bd__usage app-seg-bar');
      expect(bar?.getAttribute('aria-label')).toMatch(expected);
      const row = view.container.querySelector('.bd__usage .bd__urow');
      expect(row?.getAttribute('title')).toMatch(expected);
    });

    it('keeps the requested amount on a phone, below the name of the row (N28)', async () => {
      const view = await setup({ wide: false, phone: true });
      const row = view.container.querySelector('.bd__usage .bd__urow') as HTMLElement;
      // The column and the line below the name both exist; CSS shows the line on a phone.
      expect(row.querySelector('.bd__c1')).toBeTruthy();
      const req = row.querySelector('.bd__ucell > .bd__uname + .bd__ureq') as HTMLElement;
      expect(req.textContent).toMatch(/Beantragt:\s*20\s€/);
    });

    it('shows no shared legend, because each bar has the colour of its cost centre', async () => {
      const view = await setup();
      expect(view.container.querySelector('.bd__legends, .bd__legend, .bd__swatch')).toBeNull();
    });

    it('opens no native select: the metric and the year chip open the menu of the app', async () => {
      const view = await setup();
      expect(view.container.querySelector('select')).toBeNull();
      const chip = view.container.querySelector('.bd__secHead app-filter-select button') as HTMLElement;
      expect(chip).toHaveAttribute('aria-haspopup', 'listbox');
      expect(chip).toHaveClass('chip', 'on');
    });

    it('drills into a row by its name', async () => {
      const view = await setup();
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      within(view.container.querySelector('.bd__usage') as HTMLElement)
        .getByRole('button', { name: 'Rücklage' })
        .click();
      const c = view.fixture.componentInstance as unknown as Inst;
      expect(c.selectedKsId()).toBe('b-900');
    });

    it('returns no rows without a selection', async () => {
      const { c } = await setup();
      c.selectedKsId.set('');
      expect(c.usageRows()).toEqual([]);
      expect(c.figures().allocated).toBe(0);
    });
  });

  // ------------------------------------------------------------------ applications

  describe('applications on the cost centre', () => {
    it('lists status, path key, cost centre and amount, newest first', async () => {
      const view = await setup({
        apps: [
          app({ applicationId: 'a-old', title: 'Alt', createdAt: '2026-01-01T00:00:00Z' }),
          app({
            applicationId: 'a-new',
            title: 'Neu',
            budgetId: 'b-810',
            pathKey: 'VS-800-810',
            amount: '2890.00',
            stateLabel: { de: 'Bewilligt', en: 'Approved' },
            stateColor: '#3f9a5c',
            createdAt: '2026-06-01T00:00:00Z',
          }),
        ],
      });
      const section = view.container.querySelector('[aria-labelledby="bd-apps"]') as HTMLElement;
      const titles = [...section.querySelectorAll('.li__title')].map((t) => t.textContent?.trim());
      expect(titles).toEqual(['Neu', 'Alt']);
      const first = section.querySelector('app-list-item') as HTMLElement;
      expect(first.querySelector('app-status-text')?.textContent).toContain('Bewilligt');
      expect(first.querySelector('app-status-text')?.classList).toContain('st--accent');
      // The path joins the keys with "-".
      expect(first.textContent).toContain('VS-800-810');
      expect(first.textContent).toContain('Werkstatt');
      expect(first.textContent).toMatch(/2\.890,00\s€/);
      expect(first.querySelector('a.li__title')?.getAttribute('href')).toBe('/applications/a-new');
    });

    it('shows at most five and falls back to "Ohne Titel" without a title, never to the id', async () => {
      const apps = Array.from({ length: 7 }, (_, i) =>
        app({ applicationId: `abcdefgh-${i}`, title: i === 6 ? null : `A${i}`, createdAt: `2026-0${i + 1}-01T00:00:00Z` }),
      );
      const view = await setup({ apps });
      const c = view.fixture.componentInstance as unknown as Inst;
      expect(c.appRows()).toHaveLength(5);
      expect(c.appRows()[0].title).toBe('Ohne Titel');
      expect(view.container.querySelectorAll('[aria-labelledby="bd-apps"] app-list-item')).toHaveLength(5);
    });

    it('says so when the cost centre has no applications and hides "Alle ansehen"', async () => {
      await setup();
      expect(screen.getByText('Keine Anträge auf dieser Kostenstelle.')).toBeTruthy();
      expect(screen.queryByRole('button', { name: 'Alle ansehen' })).toBeNull();
    });

    it('shows a placeholder while loading and an error when the request fails', async () => {
      const { c, http, fixture } = await setup();
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectKs('b-800');
      fixture.detectChanges();
      expect(c.apps()).toBeNull();
      expect(fixture.nativeElement.querySelector('[aria-labelledby="bd-apps"] app-skeleton')).toBeTruthy();
      http
        .expectOne((r) => r.url.endsWith('/budgets/b-800/applications'))
        .flush('x', { status: 500, statusText: 'err' });
      fixture.detectChanges();
      expect(screen.getByText('Die Anträge konnten nicht geladen werden.')).toBeTruthy();
    });

    it('drops a stale answer when the selection moves on', async () => {
      const { c, http } = await setup();
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectKs('b-800');
      c.selectKs('b-900');
      const stale = http.expectOne((r) => r.url.endsWith('/budgets/b-800/applications'));
      expect(stale.cancelled).toBe(true);
      http.expectOne((r) => r.url.endsWith('/budgets/b-900/applications')).flush([app({ applicationId: 'x' })]);
      expect(c.apps()).toHaveLength(1);
    });

    it('resolves the state label in the active locale, then de, en and the first entry', async () => {
      const { c } = await setup();
      localStorage.setItem('ap.locale', 'fr');
      expect(c['resolveLabel']({ de: 'D', en: 'E' })).toBe('D');
      expect(c['resolveLabel']({ en: 'E' })).toBe('E');
      expect(c['resolveLabel']({ it: 'I' })).toBe('I');
      expect(c['resolveLabel']({})).toBe('');
    });
  });

  // ------------------------------------------------------------------ year + roots

  describe('fiscal year and roots', () => {
    it('switches the fiscal year from the chip and reloads the applications for it', async () => {
      const view = await setup({ fys: [FY, FY2] });
      const c = view.fixture.componentInstance as unknown as Inst;
      const nav = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      (view.container.querySelector('.bd__pane app-filter-select button') as HTMLElement).click();
      view.fixture.detectChanges();
      const list = screen.getByRole('listbox', { name: 'Haushaltsjahr' });
      expect(within(list).getAllByRole('option').map((o) => o.textContent?.trim())).toEqual([
        'HHJ 2026',
        'HHJ 2027',
      ]);
      within(list).getByRole('option', { name: 'HHJ 2027' }).click();
      view.fixture.detectChanges();
      expect(c.selectedFyId()).toBe('fy-2');
      expect(nav).toHaveBeenCalled();
      const req = view.http.expectOne((r) => r.url.endsWith('/budgets/b-vs/applications'));
      expect(req.request.params.get('fiscalYear')).toBe('fy-2');
      req.flush([]);
      // The same year again changes nothing.
      c.selectYear('fy-2');
      view.http.expectNone((r) => r.url.endsWith('/applications'));
    });

    it('moves to another root with the year of the same start year', async () => {
      const tree = [
        TREE[0],
        node({
          id: 'b-qs',
          key: 'QS',
          name: 'QS-Mittel',
          byFiscalYear: [
            alloc({ fiscalYearId: 'qs-26', allocated: '500' }),
            alloc({ fiscalYearId: 'qs-27', allocated: '700' }),
          ],
        }),
        // Only a 2026 year: a 2027 selection shows nothing there and a pick falls back
        // to its first year.
        node({ id: 'b-xs', key: 'XS', name: 'XS-Mittel', byFiscalYear: [alloc({ fiscalYearId: 'xs-26', allocated: '90' })] }),
      ];
      setViewport(true);
      const view = await render(BudgetDashboardComponent, { providers: providers({}) });
      const http = TestBed.inject(HttpTestingController);
      http.expectOne((r) => r.url.endsWith('/budgets')).flush(tree);
      http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY, FY2]);
      http
        .expectOne((r) => r.url.endsWith('/budgets/b-qs/fiscal-years'))
        .flush([
          { ...FY, id: 'qs-26', budgetId: 'b-qs' },
          { ...FY2, id: 'qs-27', budgetId: 'b-qs' },
        ]);
      http.expectOne((r) => r.url.endsWith('/budgets/b-xs/fiscal-years')).flush([{ ...FY, id: 'xs-26', budgetId: 'b-xs' }]);
      flushApps(http);
      const c = view.fixture.componentInstance as unknown as Inst;
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectYear('fy-2');
      flushApps(http);
      // The other root shows its 2027 figures in the tree.
      const qsRow = c.treeRows().find((r: { node: { id: string } }) => r.node.id === 'b-qs');
      expect(qsRow.allocated).toBe(700);
      const xsRow = c.treeRows().find((r: { node: { id: string } }) => r.node.id === 'b-xs');
      expect(xsRow.allocated).toBe(0);
      c.selectKs('b-qs');
      expect(c.selectedBudgetId()).toBe('b-qs');
      expect(c.selectedFyId()).toBe('qs-27');
      flushApps(http);
      c.selectKs('b-xs');
      expect(c.selectedFyId()).toBe('xs-26');
      flushApps(http);
    });
  });

  // ------------------------------------------------------------------ narrow layout

  describe('narrow layout', () => {
    it('puts the tree in a side sheet that the path chip opens', async () => {
      const view = await setup({ wide: false, queryParams: { ks: 'b-800' } });
      const c = view.fixture.componentInstance as unknown as Inst;
      expect(view.container.querySelector('.bd__pane')).toBeNull();
      const chip = view.container.querySelector('.bd__pathChip') as HTMLButtonElement;
      expect(chip.textContent).toContain('VS-Mittel › Dezentrale Einrichtungen');
      chip.click();
      view.fixture.detectChanges();
      expect(c.navOpen()).toBe(true);
      // A pick closes the sheet again.
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectKs('b-810');
      expect(c.navOpen()).toBe(false);
      flushApps(view.http);
    });

    it('opens the tree in a side sheet from the start that scrolls only the tree', async () => {
      const view = await setup({ wide: false });
      (view.container.querySelector('.bd__pathChip') as HTMLButtonElement).click();
      view.fixture.detectChanges();
      const dialog = view.getByRole('dialog', { name: 'Kostenstellen' });
      expect(dialog).toHaveClass('ss--start');
      expect(dialog.querySelector('.ss__body')).toHaveClass('ss__body--fill');
      expect(dialog.querySelector('.ss__body > .bd__paneBody .bd__tree')).toBeTruthy();
      // The year and the overview sit on the page, so the sheet has only the search and
      // the tree.
      expect(dialog.querySelector('.bd-chip, select')).toBeNull();
      // The sheet has the background of the search field, so the field takes the next
      // surface there.
      expect(dialog.querySelector('.bd__paneBody')).toHaveClass('bd__paneBody--side');
    });

    it('opens the tree in the shared sheet from the bottom on a phone', async () => {
      const view = await setup({ wide: false, phone: true });
      (view.container.querySelector('.bd__pathChip') as HTMLButtonElement).click();
      view.fixture.detectChanges();
      const dialog = view.getByRole('dialog', { name: 'Kostenstellen' });
      expect(dialog).toHaveClass('ss--bottom');
      // The handle of the sheet.
      expect(dialog.querySelector('.ss__handle')).toBeTruthy();
      // The body passes the height down: the search stays above the tree, which scrolls
      // by itself down to the bottom padding of the sheet.
      expect(dialog.querySelector('.ss__body')).toHaveClass('ss__body--fill');
      const pane = dialog.querySelector('.ss__body > .bd__paneBody') as HTMLElement;
      expect(pane).toHaveClass('bd__paneBody--side');
      expect(pane.querySelector(':scope > app-search-pill + .bd__tree')).toBeTruthy();
      // The close button of the sheet closes it.
      (dialog.querySelector('.ss__close') as HTMLButtonElement).click();
      view.fixture.detectChanges();
      const c = view.fixture.componentInstance as unknown as Inst;
      expect(c.navOpen()).toBe(false);
      expect(view.queryByRole('dialog')).toBeNull();
    });

    it('puts the actions into a "more" menu on a phone', async () => {
      const view = await setup({ wide: false, phone: true });
      const c = view.fixture.componentInstance as unknown as Inst;
      const row = view.container.querySelector('.bd__topRow') as HTMLElement;
      expect(row.querySelector('.bd__actions')).toBeNull();
      const more = within(row).getByRole('button', { name: 'Weitere Aktionen' });
      more.click();
      view.fixture.detectChanges();
      const items = view.getAllByRole('menuitem').map((i) => i.textContent?.trim());
      expect(items).toEqual(['Exportieren', 'Buchungen ansehen']);
      const exp = jest.spyOn(c, 'onExport').mockImplementation(() => undefined);
      const book = jest.spyOn(c, 'openBookings').mockImplementation(() => undefined);
      view.getAllByRole('menuitem')[0].click();
      expect(exp).toHaveBeenCalled();
      c.onAction({ id: 'bookings', label: '' });
      expect(book).toHaveBeenCalled();
    });

    it('has no "more" menu on a phone without an action', async () => {
      const view = await setup({ wide: false, phone: true, perms: [] });
      expect(view.container.querySelector('.bd__more')).toBeNull();
    });

    it('shows an overview chip beside the path and the year chip', async () => {
      const view = await setup({ wide: false, phone: true });
      const c = view.fixture.componentInstance as unknown as Inst;
      const chips = view.container.querySelector('.bd__top .bd__chips') as HTMLElement;
      expect(chips.querySelector('.bd__pathChip')).toBeTruthy();
      expect(chips.querySelector('app-filter-select')).toBeTruthy();
      const chip = within(chips).getByRole('button', { name: 'Übersicht' });
      expect(chip).not.toHaveClass('bd-chip--on');
      chip.click();
      view.fixture.detectChanges();
      expect(c.overviewOpen()).toBe(true);
      expect(chip).toHaveClass('bd-chip--on');
    });

    it('opens the year chip as a bottom sheet on a phone', async () => {
      const view = await setup({ wide: false, phone: true, fys: [FY, FY2] });
      const c = view.fixture.componentInstance as unknown as Inst;
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      const chips = view.container.querySelector('.bd__top .bd__chips') as HTMLElement;
      within(chips).getByRole('button', { name: 'Haushaltsjahr: HHJ 2026' }).click();
      view.fixture.detectChanges();
      const sheet = screen.getByRole('dialog', { name: 'Haushaltsjahr' });
      within(sheet).getByRole('option', { name: 'HHJ 2027' }).click();
      view.fixture.detectChanges();
      expect(c.selectedFyId()).toBe('fy-2');
      expect(screen.queryByRole('dialog', { name: 'Haushaltsjahr' })).toBeNull();
      view.http.match(() => true);
    });

    it('names the sheet after the path and puts the actions beside the title', async () => {
      const view = await setup({ wide: false });
      const article = view.container.querySelector('article.bd__sheet');
      expect(article?.getAttribute('aria-label')).toBe('VS-Mittel');
      expect(view.container.querySelector('.bd__topRow .bd__actions')).toBeTruthy();
      expect(view.container.querySelector('app-sheet-bar')).toBeNull();
      expect(view.container.querySelector('.bd__crumbs')).toBeNull();
    });
  });

  // ------------------------------------------------------------------ overview

  describe('overview (sunburst)', () => {
    it('offers only metrics with data and falls back when the chosen one has none', async () => {
      const { c } = await setup();
      expect(c.overviewRoot()?.id).toBe('b-vs');
      expect(c.visibleOverviewMetrics()).toEqual(['allocated', 'available', 'expended']);
      c.overviewMetric.set('available');
      expect(c.activeOverviewMetric()).toBe('available');
      c.selectedKsId.set('');
      expect(c.visibleOverviewMetrics()).toEqual([]);
      expect(c.activeOverviewMetric()).toBe('allocated');
    });

    it('falls back to the first metric with data', async () => {
      const tree = [
        node({ id: 'top', key: 'T', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '100' })] }),
      ];
      const { c } = await setup({ tree });
      c.overviewMetric.set('expended');
      expect(c.activeOverviewMetric()).toBe('allocated');
      expect(c.metricLabel('expended')).toBe('Ausgegeben');
    });

    it('opens from the chip and closes on a pick', async () => {
      const view = await setup();
      const c = view.fixture.componentInstance as unknown as Inst;
      screen.getByRole('button', { name: /Übersicht/ }).click();
      expect(c.overviewOpen()).toBe(true);
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.onOverviewPick('b-800');
      expect(c.overviewOpen()).toBe(false);
      expect(c.selectedKsId()).toBe('b-800');
    });

    it('names the close button in the active locale', async () => {
      localStorage.setItem('ap.locale', 'en');
      const view = await setup();
      const c = view.fixture.componentInstance as unknown as Inst;
      c.overviewOpen.set(true);
      view.fixture.detectChanges();
      const dialog = screen.getByRole('dialog', { name: 'Budget overview' });
      const close = within(dialog).getByRole('button', { name: 'Close' });
      expect(close.getAttribute('title')).toBe('Close');
      expect(within(dialog).queryByRole('button', { name: 'Schließen' })).toBeNull();
    });
  });

  // ------------------------------------------------------------------ edge cases

  it('copes with an unknown cost centre, an unknown year and an empty selection', async () => {
    const { c, http } = await setup();
    const nav = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectedFyId.set('nope');
    expect(c.selectedYear()).toBeNull();
    c.selectedFyId.set('fy-1');
    // A cost centre that is not in the tree is its own root.
    c.selectKs('ghost');
    expect(c.selectedBudgetId()).toBe('ghost');
    expect(c.breadcrumbs()).toEqual([]);
    expect(c.distribution()).toEqual([]);
    expect(c.usageRows()).toEqual([]);
    flushApps(http);
    // Nothing selected: no request, no rows, and the URL loses the params.
    c['setSelection']('', '', '');
    http.expectNone((r) => r.url.endsWith('/applications'));
    expect(c.apps()).toEqual([]);
    c['syncUrl']();
    expect(nav).toHaveBeenLastCalledWith([], expect.objectContaining({
      queryParams: { budget: null, ks: null, fy: null },
    }));
  });

  it('shows an application without state, cost centre or amount', async () => {
    const view = await setup({
      apps: [app({ applicationId: 'a-1', stateLabel: null, budgetId: null, pathKey: null, amount: null })],
    });
    const c = view.fixture.componentInstance as unknown as Inst;
    expect(c.appRows()[0]).toEqual(expect.objectContaining({ statusLabel: null, costCentre: null }));
    const row = view.container.querySelector('[aria-labelledby="bd-apps"] app-list-item') as HTMLElement;
    expect(row.querySelector('app-status-text')).toBeNull();
    expect(row.textContent).toContain('–');
    // An empty label map gives no status either.
    c.apps.set([app({ applicationId: 'a-2', stateLabel: {} })]);
    expect(c.appRows()[0].statusLabel).toBeNull();
    c.apps.set(null);
    expect(c.appRows()).toEqual([]);
  });

  // ------------------------------------------------------------------ formatting

  it('formats money with and without cents', async () => {
    const { c } = await setup();
    expect(c.money(100)).toMatch(/100,00/);
    expect(c.money('250')).toContain('250');
    expect(c.money(null)).toContain('0');
    expect(c.money('')).toContain('0');
    expect(c.money(5, 'USD')).toMatch(/[$]|USD/);
    expect(c.moneyShort(1234.56)).toMatch(/^1\.235\s€$/);
    // A node without a currency still formats in euro.
    expect(c.money(1, '')).toContain('€');
    expect(c.moneyShort(1, '')).toContain('€');
  });

  // ------------------------------------------------------------------ load + states

  it('shows the loading state, then the error when the tree request fails', async () => {
    const { c, http, fixture } = await bare();
    fixture.detectChanges();
    expect(c.loading()).toBe(true);
    // The placeholder has the two columns of the wide layout, so the page does not jump.
    expect(fixture.nativeElement.querySelector('[aria-busy="true"]')).toHaveClass('bd--wide');
    expect(fixture.nativeElement.querySelectorAll('main')).toHaveLength(0);
    http.expectOne((r) => r.url.endsWith('/budgets')).flush('x', { status: 500, statusText: 'err' });
    fixture.detectChanges();
    expect(c.error()).toBe(true);
    expect(c.loading()).toBe(false);
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('never claims the budget is empty while it is still loading', async () => {
    const { c, http, fixture, container } = await bare();
    fixture.detectChanges();
    expect(c.loading()).toBe(true);
    expect(container.querySelector('.bd__empty')).toBeNull();
    expect(container.querySelector('.skel')).toBeTruthy();
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    fixture.detectChanges();
    expect(container.querySelector('.bd__empty')).toBeTruthy();
    expect(container.querySelector('.skel')).toBeNull();
    expect(screen.getByText('Noch keine Budgetdaten')).toBeTruthy();
  });

  it('has no axe violations on the wide layout', async () => {
    const wideView = await setup({ apps: [app({ applicationId: 'a-1' })] });
    expect(await axe(wideView.container)).toHaveNoViolations();
  });

  it('has no axe violations on the narrow layout', async () => {
    const narrow = await setup({ wide: false, apps: [app({ applicationId: 'a-1' })] });
    expect(await axe(narrow.container)).toHaveNoViolations();
  });

  it('nests no second main landmark inside the shell main', async () => {
    const view = await setup();
    expect(view.container.querySelectorAll('main')).toHaveLength(0);
    expect(view.container.querySelector('.bd__main')?.getAttribute('role')).toBeNull();
  });

  it('prunes hidden cost centres from the tree, the roots and the sheet', async () => {
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
      node({ id: 'b-secret', key: 'SEC', hiddenInBudget: true, byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
    ];
    const { c } = await setup({ tree });
    expect(c.tops().map((n: { id: string }) => n.id)).toEqual(['b-vs']);
    const ids = c.usageRows().map((r: { node: { id: string } }) => r.node.id);
    expect(ids).toEqual(['b-show']);
    expect(c.treeRows().map((r: { node: { id: string } }) => r.node.id)).not.toContain('b-hide');
  });

  // ------------------------------------------------------------------ URL

  describe('selection from the URL', () => {
    it('restores budget, cost centre and year from the query params', async () => {
      const { c } = await setup({ fys: [FY, FY2], queryParams: { budget: 'b-vs', ks: 'b-800', fy: 'fy-2' } });
      expect(c.selectedBudgetId()).toBe('b-vs');
      expect(c.selectedKsId()).toBe('b-800');
      expect(c.selectedFyId()).toBe('fy-2');
    });

    it('follows the URL when the palette sends it here while it is already here', async () => {
      const { c, params, http } = await setup();
      expect(c.selectedKsId()).toBe('b-vs');
      params.next(convertToParamMap({ ks: 'b-800' }));
      expect(c.selectedKsId()).toBe('b-800');
      flushApps(http);
    });

    it('derives the root from a cost centre the link names on its own', async () => {
      const tree = [
        node({ id: 'b-other', key: 'OTHER', name: 'Andere', byFiscalYear: [alloc({ fiscalYearId: 'fy-1' })] }),
        ...TREE,
      ];
      const { c } = await setup({ tree, queryParams: { ks: 'b-800' } });
      expect(c.selectedKsId()).toBe('b-800');
      expect(c.selectedBudgetId()).toBe('b-vs');
    });

    it('leaves the selection alone when the URL repeats what is already shown', async () => {
      const { c, params } = await setup();
      const before = [c.selectedBudgetId(), c.selectedKsId(), c.selectedFyId()];
      params.next(convertToParamMap({ budget: 'b-vs', ks: 'b-vs', fy: 'fy-1' }));
      expect([c.selectedBudgetId(), c.selectedKsId(), c.selectedFyId()]).toEqual(before);
    });

    it('stops at the highest cost centre it can see when the parent is out of scope', async () => {
      const tree = [
        node({
          id: 'b-sub', parentId: 'b-not-in-scope', key: 'SUB', name: 'Teilbereich',
          byFiscalYear: [alloc({ fiscalYearId: 'fy-1' })],
          children: [
            node({ id: 'b-leaf', parentId: 'b-sub', key: 'LEAF', name: 'Blatt', byFiscalYear: [alloc({ fiscalYearId: 'fy-1' })] }),
          ],
        }),
      ];
      const { c } = await setup({ tree, queryParams: { ks: 'b-leaf' } });
      expect(c.selectedKsId()).toBe('b-leaf');
      expect(c.selectedBudgetId()).toBe('b-sub');
    });

    it('ignores invalid query params and defaults to the first root and year', async () => {
      const { c } = await setup({ queryParams: { budget: 'ghost', ks: 'ghost', fy: 'ghost' } });
      expect(c.selectedBudgetId()).toBe('b-vs');
      expect(c.selectedKsId()).toBe('b-vs');
      expect(c.selectedFyId()).toBe('fy-1');
    });

    it('stays without a selection when the fiscal-years request fails', async () => {
      const { c, http, fixture } = await bare();
      http.expectOne((r) => r.url.endsWith('/budgets')).flush([node({ id: 'b-vs', key: 'VS' })]);
      http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).error(new ProgressEvent('err'));
      fixture.detectChanges();
      expect(c.selectedBudgetId()).toBe('');
      expect(c.loading()).toBe(false);
    });

    it('waits for the years of the root the URL names', async () => {
      const tree = [
        node({ id: 'b-a', key: 'A', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
        node({ id: 'b-b', key: 'B', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
      ];
      const { c, http, fixture } = await bare();
      http.expectOne((r) => r.url.endsWith('/budgets')).flush(tree);
      // Only b-b has years so far, so it becomes the default; the later answer for b-a
      // changes nothing.
      http.expectOne((r) => r.url.endsWith('/budgets/b-b/fiscal-years')).flush([{ ...FY, budgetId: 'b-b' }]);
      http.expectOne((r) => r.url.endsWith('/budgets/b-a/fiscal-years')).flush([{ ...FY, budgetId: 'b-a' }]);
      fixture.detectChanges();
      expect(c.selectedBudgetId()).toBe('b-b');
    });

    it('selects nothing until a root with a fiscal year is loaded', async () => {
      const { c, http, fixture } = await bare();
      http.expectOne((r) => r.url.endsWith('/budgets')).flush([node({ id: 'b-vs', key: 'VS' })]);
      http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
      fixture.detectChanges();
      expect(c.selectedBudgetId()).toBe('');
    });
  });

  // ------------------------------------------------------------------ empty reasons

  describe('empty states', () => {
    it('blames the missing fiscal year, not the cost centres, when only the year is gone', async () => {
      const view = await setup({ fys: [] });
      expect(view.container.querySelector('.bd__empty')).toBeTruthy();
      expect(screen.getByText('Kein Haushaltsjahr angelegt')).toBeTruthy();
      expect(screen.queryByText('Noch keine Budgetdaten')).toBeNull();
      const link = screen.getByRole('link', { name: 'Haushaltsjahr anlegen' });
      expect(link.getAttribute('href')).toBe('/admin/cost-centres');
    });

    it('keeps the "nothing is configured" wording when there is no cost centre at all', async () => {
      const view = await setup({ tree: [], fys: [] });
      expect(screen.getByText('Noch keine Budgetdaten')).toBeTruthy();
      expect(screen.queryByText('Kein Haushaltsjahr angelegt')).toBeNull();
      expect(view.container.querySelector('.bd__empty')).toBeTruthy();
    });

    it('centres the "nothing is configured" state in the free page height', async () => {
      const view = await setup({ tree: [], fys: [] });
      expect(view.container.querySelector('.bd__empty app-empty-state')).toHaveClass('es-host--fill');
    });

    it('centres the "no fiscal year" state in the free page height', async () => {
      const view = await setup({ fys: [] });
      expect(view.container.querySelector('.bd__empty app-empty-state')).toHaveClass('es-host--fill');
    });

    it('claims neither empty state while the fiscal years are still on the wire', async () => {
      const { c, http, fixture } = await bare();
      http.expectOne((r) => r.url.endsWith('/budgets')).flush(TREE);
      fixture.detectChanges();
      expect(c.emptyReason()).toBeNull();
      expect(screen.queryByText('Kein Haushaltsjahr angelegt')).toBeNull();
      http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
      fixture.detectChanges();
      expect(c.emptyReason()).toBe('noFiscalYear');
    });

    it('hides the fiscal-year link from a reader who cannot create one', async () => {
      await setup({ fys: [], perms: ['budget.view'] });
      expect(screen.getByText('Kein Haushaltsjahr angelegt')).toBeTruthy();
      expect(screen.queryByRole('link', { name: 'Haushaltsjahr anlegen' })).toBeNull();
    });
  });
});

describe('utilisation', () => {
  it('is committed over the total of allocation and income, or null without a total', () => {
    const f = { allocated: 100, requested: 0, bound: 20, expended: 30, income: 0, committed: 50, available: 50 };
    expect(utilisation(f)).toBe(50);
    expect(utilisation({ ...f, committed: 0, available: 0 })).toBeNull();
  });
});
