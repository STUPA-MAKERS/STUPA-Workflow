import { HttpCacheService } from '@core/cache/http-cache.service';
import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import type { Observable } from 'rxjs';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { AuthService } from '@core/auth/auth.service';
import { AdminApiService } from '../admin/admin-api.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { BudgetDashboardComponent, utilisation } from './budget-dashboard.component';
import { BudgetTreeApi } from './budget-tree.api';
import type {
  BudgetAllocationView,
  BudgetApplication,
  BudgetTreeNode,
  Expense,
  FiscalYear,
} from './budget-tree.api';
import { NO_LINKED_TODOS } from '../../../testing/todo-fixtures';
import { By } from '@angular/platform-browser';
import { CostCentreSettingsComponent } from './cost-centre/cost-centre-settings.component';
import { TodosApiService } from '@core/api/todos.service';
import { PALETTE, shadeColor } from './budget-color.util';
import { itemApp, itemBooking } from './budget-items/budget-items.fixtures';
import { loadErrorToast } from '../../../testing/load-error';

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

const app = itemApp;
const booking = itemBooking;

const ALL_PERMS = ['budget.view', 'budget.structure', 'budget.book', 'budget.export'];

function authStub(perms: string[] = ALL_PERMS): AuthService {
  const can = (p: string): boolean => perms.includes(p);
  return { can, canAny: (...ps: string[]) => ps.some(can) } as unknown as AuthService;
}

/** Let `matchMedia` report a wide viewport (or not), and a phone. jsdom has none of its own. */
function setViewport(wide: boolean, phone = false): void {
  window.matchMedia = ((query: string) => ({
    matches:
      (wide && query.includes('min-width: 1200px')) || (phone && query === '(max-width: 767.98px)'),
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
  bookings?: Expense[];
  wide?: boolean;
  phone?: boolean;
  /** The to-do API of the section "Verknüpft" of the cost centre card. */
  todos?: object;
  /** The answer of the Gremien list of the settings of a Kostenstelle. */
  gremien?: Observable<readonly { id: string; name: string }[]>;
}

/**
 * The page follows the URL after the first restore, so the stub needs the stream and not only the
 * snapshot.
 */
function providers(opts: SetupOpts, params = new BehaviorSubject(convertToParamMap({}))) {
  return [
    provideHttpClient(),
    provideHttpClientTesting(),
    provideRouter([]),
    opts.todos ? { provide: TodosApiService, useValue: opts.todos } : NO_LINKED_TODOS,
    { provide: AuthService, useValue: authStub(opts.perms) },
    { provide: AdminApiService, useValue: { listGremienOptions: () => opts.gremien ?? of([]) } },
    {
      provide: ActivatedRoute,
      useValue: {
        snapshot: { queryParamMap: params.value },
        queryParamMap: params,
      },
    },
  ];
}

/** Answer every outstanding applications request of the sheet, and the bookings request
 *  of its preview. */
function flushApps(http: HttpTestingController, apps: BudgetApplication[] = [], bookings: Expense[] = []): void {
  for (const req of http.match((r) => /\/budgets\/[^/]+\/applications$/.test(r.url))) {
    if (!req.cancelled) req.flush(apps);
  }
  for (const req of http.match((r) => r.url.endsWith('/expenses'))) {
    if (!req.cancelled) req.flush({ items: bookings, total: bookings.length, limit: 5, offset: 0 });
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
  const tops = tree.filter((n) => n.active);
  for (const top of tops) {
    http.expectOne((r) => r.url.endsWith(`/budgets/${top.id}/fiscal-years`)).flush(fys);
  }
  flushApps(http, opts.apps, opts.bookings);
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

/** Only the date is fixed, so the default fiscal year does not move with the calendar. */
const NOT_FAKED = [
  'hrtime',
  'nextTick',
  'performance',
  'queueMicrotask',
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'requestIdleCallback',
  'cancelIdleCallback',
  'setImmediate',
  'clearImmediate',
  'setInterval',
  'clearInterval',
  'setTimeout',
  'clearTimeout',
] as const;

describe('BudgetDashboardComponent', () => {
  const realMatchMedia = window.matchMedia;
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    jest.useFakeTimers({ now: new Date('2026-11-12T10:00:00Z'), doNotFake: [...NOT_FAKED] });
  });
  afterEach(() => {
    jest.useRealTimers();
    const http = TestBed.inject(HttpTestingController);
    flushApps(http);
    http.verify();
    window.matchMedia = realMatchMedia;
  });

  describe('tree', () => {
    /**
     * The year, the overview and the search are outside the scrolling list. The pane sits on the
     * page, so the search field keeps its own surface.
     */
    it('scrolls only the tree and fades an end only where more rows are', async () => {
      const view = await setup();
      const tree = view.container.querySelector('.bd__pane .bd__tree') as HTMLElement;
      expect(tree.querySelector('app-search-pill, .chip')).toBeNull();
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

    /**
     * The bar stays on top, and the body holds the rest of the content, so the card keeps its
     * background unmasked.
     */
    it('scrolls the sheet inside itself on the wide layout and fades only the content', async () => {
      const view = await setup();
      const sheet = view.container.querySelector('article.bd__sheet') as HTMLElement;
      const body = sheet.querySelector(':scope > .bd__sheetBody') as HTMLElement;
      expect(Array.from(sheet.children).map((el) => el.tagName.toLowerCase())).toEqual(['header', 'div']);
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

    /** 800 is closed, so its child is not in the tree yet. */
    it('shows the root open with its children, each with its allocation', async () => {
      const view = await setup();
      const tree = within(view.container.querySelector('.bd__tree') as HTMLElement);
      expect(tree.getByText('VS-Mittel')).toBeTruthy();
      expect(tree.getByText('Dezentrale Einrichtungen')).toBeTruthy();
      expect(tree.getByText('Rücklage')).toBeTruthy();
      expect(tree.queryByText('Werkstatt')).toBeNull();
      expect(tree.getAllByText(/1\.000\s€/).length).toBe(1);
      const current = view.container.querySelector('.tn--on .tn__name');
      expect(current?.textContent).toContain('VS-Mittel');
    });

    /**
     * A node without a colour takes the colour of the faculty above. With no colour of its own or
     * above, it takes the palette colour of its position.
     */
    it('gives a node its own or inherited colour and draws the swatch only then', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-810' } });
      const rows = view.c.treeRows() as { node: { id: string }; color: string; swatch: boolean }[];
      const row = (id: string) => rows.find((r) => r.node.id === id);
      expect(row('b-800')?.color).toBe('#0075bf');
      expect(row('b-810')?.color).toBe('#0075bf');
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

    /** The node without any colour is the case that must match in all three places. */
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
      expect(tree.get('b-900')).toBe(PALETTE[1]);
    });

    it('opens the path to a cost centre the URL names', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-810' } });
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

    /** 350 committed of 300 is 117 %. */
    it('draws the utilisation bar of a node in red when it is overdrawn', async () => {
      const { c } = await setup();
      const rows = c.treeRows() as { node: { id: string }; segments: { tone: string }[]; percent: number | null }[];
      const r900 = rows.find((r) => r.node.id === 'b-900')!;
      expect(r900.segments[0].tone).toBe('error');
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

  describe('figures', () => {
    it('shows all six figures, Beantragt and Einnahmen included', async () => {
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
      const view = await setup({ queryParams: { costCentre: 'b-900' } });
      const neg = view.container.querySelector('.bd__fig--main .bd__figValue');
      expect(neg?.classList).toContain('bd__neg');
    });

    it('counts a missing allocation as zero', async () => {
      const { c } = await setup();
      expect(c.figuresOf(TREE[0], 'other-year').allocated).toBe(0);
    });

  });

  describe('header', () => {
    /**
     * The bar sits above the scrolling body, so it stays in place. It opens the sheet with the
     * name of the cost centre, like the title bar of every other detail. The tree on the left
     * shows the path, so the bar holds no breadcrumb.
     */
    it('puts the name in the title of the shared sheet bar, the actions at its end', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-810' } });
      const head = view.container.querySelector('article.bd__sheet > header.sheet-head') as HTMLElement;
      expect(head.nextElementSibling).toHaveClass('bd__sheetBody');
      const bar = head.querySelector(':scope > app-sheet-bar') as HTMLElement;
      expect(bar).toHaveClass('sheet-bar--title');
      const title = bar.querySelector('.sheet-bar__title > h2#bd-title') as HTMLElement;
      expect(title.textContent).toContain('Werkstatt');
      expect(view.container.querySelector('article.bd__sheet')?.getAttribute('aria-labelledby')).toBe('bd-title');
      expect(view.container.querySelectorAll('#bd-title')).toHaveLength(1);
      expect(view.container.querySelector('.sheet-bar__kicker')).toBeNull();
      const actions = bar.querySelector(':scope > .sheet-bar__actions > .bd__actions') as HTMLElement;
      // § 000670: one icon button for the export, "Buchungen ansehen" in the ⋮ menu, no text button.
      const exportButton = within(actions).getByRole('button', { name: /Exportieren/ });
      expect(exportButton.textContent?.trim()).toBe('');
      expect(within(actions).queryByRole('button', { name: 'Buchungen ansehen' })).toBeNull();
      expect(actions.querySelector('app-row-menu')).not.toBeNull();
      expect(view.fixture.componentInstance.moreSections()[0].items.map((i) => i.label)).toEqual(['Buchungen ansehen']);
      expect(view.container.querySelector('.bd__sheetBody')?.firstElementChild).toHaveClass('bd__figs');
    });

    it('says the key, the parent and the year in the status line below the title', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-810' } });
      const line = view.container.querySelector('header.sheet-head > p.sheet-line') as HTMLElement;
      const parts = Array.from(line.querySelectorAll('.bd__part')).map((el) => el.textContent?.trim());
      expect(parts).toEqual(['VS-800-810', 'Dezentrale Einrichtungen', expect.stringContaining('HHJ')]);
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

    it('opens the bookings page and the dialog with every item of the cost centre', async () => {
      const view = await setup({ apps: [app({ applicationId: 'a-1' })] });
      const nav = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      view.fixture.componentInstance.onAction(view.fixture.componentInstance.moreSections()[0].items[0]);
      expect(nav).toHaveBeenCalledWith(['/expenses'], { queryParams: { budget: 'b-vs' } });
      view.fixture.detectChanges();
      screen.getByRole('button', { name: 'Alle ansehen' }).click();
      view.fixture.detectChanges();
      expect(view.c.itemsOpen()).toBe(true);
      const req = view.http.expectOne((r) => r.url.endsWith('/expenses') && r.params.get('limit') === '50');
      expect(req.request.params.get('budget')).toBe('b-vs');
      req.flush({ items: [], total: 0, limit: 50, offset: 0 });
      view.fixture.detectChanges();
      expect(screen.getByRole('dialog', { name: 'Anträge und Buchungen' })).toBeTruthy();
    });

    /** A second click while it runs does nothing. */
    it('exports the selection and resets the flag after the download', async () => {
      (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
      (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
      jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
      jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
      const { c, http } = await setup();
      screen.getByRole('button', { name: /Exportieren/ }).click();
      expect(c.exporting()).toBe(true);
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
      const toast = jest.spyOn(TestBed.inject(ToastService), 'error');
      c.onExport();
      const req = http.expectOne((r) => r.url.includes('/budget/export.xlsx'));
      expect(req.request.params.keys()).toEqual([]);
      req.error(new ProgressEvent('err'));
      expect(c.exporting()).toBe(false);
      expect(toast).toHaveBeenCalledWith('Der Export ist fehlgeschlagen.');
    });

    /**
     * A reader with a scope (viewGremiumId) and no global budget permission gets the sub cost
     * centres of the scope as roots from the server. Its figures are still there.
     */
    it('gives a gremium-scoped reader neither the export nor the bookings', async () => {
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
      expect(document.querySelector('.bd__actions app-row-menu')).toBeNull();
      expect(within(view.container.querySelector('.bd__figs') as HTMLElement).getByText(/^400,00\s€$/)).toBeTruthy();
    });
  });

  describe('distribution', () => {
    /** With no colour of its own or above, a slice takes the palette colour of its position. */
    it('splits the figure over the sub cost centres and adds what the node keeps', async () => {
      const { c } = await setup();
      const slices = c.distribution() as { label: string; value: number; color: string; id?: string }[];
      expect(slices.map((s) => [s.id ?? null, s.value])).toEqual([
        ['b-800', 400],
        ['b-900', 300],
        [null, 300],
      ]);
      expect(slices[0].color).toBe('#0075bf');
      expect(slices[1].color).toBe(PALETTE[1]);
      expect(slices[2].label).toBe('VS-Mittel (nicht verteilt)');
      expect(slices[2].color).toBe('var(--color-text-subtle)');
    });

    /** 800 asks for 20, 900 for nothing, and the root holds 50 more. */
    it('switches the figure and drops empty slices', async () => {
      const view = await setup();
      const c = view.fixture.componentInstance as unknown as Inst;
      (view.container.querySelector('.section__head app-filter-select button') as HTMLElement).click();
      view.fixture.detectChanges();
      const list = screen.getByRole('listbox', { name: 'Kennzahl' });
      within(list).getByRole('option', { name: c.metricLabel('requested') }).click();
      view.fixture.detectChanges();
      expect(c.metric()).toBe('requested');
      expect(screen.queryByRole('listbox')).toBeNull();
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
      const view = await setup({ queryParams: { costCentre: 'b-900' } });
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

  describe('utilisation per budget', () => {
    /**
     * 800 has committed 100 of 400, which is 25 %. 900 is overdrawn. The amount shows in the column
     * and in the line below the name that a phone shows instead. No requested amount reads as a
     * dash.
     */
    it('lists the sub cost centres with requested, percent and available', async () => {
      const view = await setup();
      const c = view.fixture.componentInstance as unknown as Inst;
      const rows = c.usageRows();
      expect(rows.map((r: { node: { id: string } }) => r.node.id)).toEqual(['b-800', 'b-900']);
      expect(rows[0].percent).toBe(25);
      expect(rows[0].segments).toEqual([
        { value: 40, tone: 'filled' },
        { value: 60, tone: 'second' },
      ]);
      expect(rows[0].total).toBe(400);
      expect(rows[0].color).toBe('#0075bf');
      expect(rows[1].segments.map((s: { tone: string }) => s.tone)).toEqual(['error', 'error']);
      const list = within(view.container.querySelector('.bd__usage') as HTMLElement);
      expect(list.getAllByText(/^20\s€$/)).toHaveLength(2);
      expect(list.getByText('25 %')).toBeTruthy();
      expect(list.getByText(/^-50\s€$/).classList).toContain('bd__neg');
      expect(list.getAllByText('—').length).toBeGreaterThan(0);
    });

    /** The row takes the inherited colour of the faculty above. */
    it('shows the cost centre itself when it has no sub cost centres', async () => {
      const { c } = await setup({ queryParams: { costCentre: 'b-810' } });
      const rows = c.usageRows();
      expect(rows.map((r: { node: { id: string } }) => r.node.id)).toEqual(['b-810']);
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

    /** The column and the line below the name both exist; CSS shows the line on a phone. */
    it('keeps the requested amount on a phone, below the name of the row', async () => {
      const view = await setup({ wide: false, phone: true });
      const row = view.container.querySelector('.bd__usage .bd__urow') as HTMLElement;
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
      const chip = view.container.querySelector('.section__head app-filter-select button') as HTMLElement;
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

  describe('applications and bookings on the cost centre', () => {
    it('lists the newest applications and bookings in one list, each with its type icon', async () => {
      const view = await setup({
        apps: [
          app({ applicationId: 'a-old', title: 'Alt', createdAt: '2026-01-01T00:00:00Z' }),
          app({ applicationId: 'a-new', title: 'Neu', createdAt: '2026-06-01T00:00:00Z' }),
        ],
        bookings: [booking({ id: 'e-1', description: 'Druck', createdAt: '2026-03-01T00:00:00Z' })],
      });
      const section = view.container.querySelector('[aria-labelledby="bd-apps"]') as HTMLElement;
      expect(section.querySelector('h3')?.textContent).toContain('Anträge und Buchungen');
      const titles = [...section.querySelectorAll('.li__title')].map((t) => t.textContent?.trim());
      expect(titles).toEqual(['Neu', 'Druck', 'Alt']);
      expect(section.querySelectorAll('app-list-item app-icon[lead]')).toHaveLength(3);
    });

    it('asks for the five newest bookings of the cost centre and year', async () => {
      const { c, http } = await bare();
      http.expectOne((r) => r.url.endsWith('/budgets')).flush(TREE);
      http.expectOne((r) => r.url.endsWith('/fiscal-years')).flush([FY]);
      const req = http.expectOne((r) => r.url.endsWith('/expenses'));
      expect(req.request.params.get('budget')).toBe('b-vs');
      expect(req.request.params.get('fiscalYear')).toBe('fy-1');
      expect(req.request.params.get('limit')).toBe('5');
      expect(req.request.params.get('sort')).toBe('createdAt');
      req.flush({ items: [booking({ id: 'e-1' })], total: 1, limit: 5, offset: 0 });
      flushApps(http);
      expect(c.previewBookings()).toHaveLength(1);
    });

    it('lists only applications for a reader without a budget role', async () => {
      const view = await setup({ tree: TREE, perms: [], apps: [app({ applicationId: 'a-1' })] });
      expect(view.http.match((r) => r.url.endsWith('/expenses'))).toHaveLength(0);
      const section = view.container.querySelector('[aria-labelledby="bd-apps"]') as HTMLElement;
      expect(section.querySelector('h3')?.textContent).toContain('Anträge auf dieser Kostenstelle');
    });

    it('shows at most five items', async () => {
      const apps = Array.from({ length: 7 }, (_, i) =>
        app({ applicationId: `abcdefgh-${i}`, createdAt: `2026-0${i + 1}-01T00:00:00Z` }),
      );
      const view = await setup({ apps });
      expect(view.c.previewItems()).toHaveLength(5);
      expect(view.container.querySelectorAll('[aria-labelledby="bd-apps"] app-list-item')).toHaveLength(5);
    });

    it('says so when the cost centre has no items and hides "Alle ansehen"', async () => {
      await setup();
      expect(screen.getByText('Keine Anträge oder Buchungen auf dieser Kostenstelle.')).toBeTruthy();
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
      expect(loadErrorToast()).toBe('Die Anträge und Buchungen konnten nicht geladen werden.');
    });

    it('drops a stale answer when the selection moves on', async () => {
      const { c, http } = await setup();
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectKs('b-800');
      c.selectKs('b-900');
      const stale = http.expectOne((r) => r.url.endsWith('/budgets/b-800/applications'));
      expect(stale.cancelled).toBe(true);
      http.expectOne((r) => r.url.endsWith('/budgets/b-900/applications')).flush([app({ applicationId: 'x' })]);
      flushApps(http);
      expect(c.apps()).toHaveLength(1);
    });
  });

  describe('fiscal year and roots', () => {
    it('§F/finance/budget/000140: selects the fiscal year that holds today, else the newest open one', async () => {
      const view = await setup({ fys: [FY, FY2] });
      expect(view.container.querySelector('.bd__pane app-filter-select button')).toHaveTextContent('HHJ 2026');
      view.http.match(() => true);
      TestBed.resetTestingModule();
      const closed = await setup({ fys: [{ ...FY, closedAt: '2026-11-01T00:00:00Z' }, FY2] });
      expect(closed.container.querySelector('.bd__pane app-filter-select button')).toHaveTextContent('HHJ 2027');
      closed.http.match(() => true);
    });

    it('marks a closed fiscal year in the year chip', async () => {
      const view = await setup({ fys: [FY, { ...FY2, closedAt: '2026-03-01T00:00:00Z' }] });
      (view.container.querySelector('.bd__pane app-filter-select button') as HTMLElement).click();
      view.fixture.detectChanges();
      const list = screen.getByRole('listbox', { name: 'Haushaltsjahr' });
      expect(within(list).getAllByRole('option').map((o) => o.textContent?.trim())).toEqual([
        'HHJ 2026',
        'HHJ 2027 · abgeschlossen',
      ]);
      view.http.match(() => true);
    });

    /** The same year again changes nothing. */
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
      c.selectYear('fy-2');
      view.http.expectNone((r) => r.url.endsWith('/applications'));
    });

    /**
     * The other root has only a 2026 year, so a 2027 selection shows nothing there and a pick falls
     * back to its first year. The other root shows its 2027 figures in the tree.
     */
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

  describe('narrow layout', () => {
    /** A pick closes the sheet again. */
    it('puts the tree in a side sheet that the path chip opens', async () => {
      const view = await setup({ wide: false, queryParams: { costCentre: 'b-800' } });
      const c = view.fixture.componentInstance as unknown as Inst;
      expect(view.container.querySelector('.bd__pane')).toBeNull();
      const chip = view.container.querySelector('.bd__pathChip') as HTMLButtonElement;
      expect(chip.textContent).toContain('VS-Mittel › Dezentrale Einrichtungen');
      chip.click();
      view.fixture.detectChanges();
      expect(c.navOpen()).toBe(true);
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      c.selectKs('b-810');
      expect(c.navOpen()).toBe(false);
      flushApps(view.http);
    });

    /**
     * The year and the overview sit on the page, so the sheet has only the search and the tree. The
     * sheet has the background of the search field, so the field takes the next surface there.
     */
    it('opens the tree in a side sheet from the start that scrolls only the tree', async () => {
      const view = await setup({ wide: false });
      (view.container.querySelector('.bd__pathChip') as HTMLButtonElement).click();
      view.fixture.detectChanges();
      const dialog = view.getByRole('dialog', { name: 'Kostenstellen' });
      expect(dialog).toHaveClass('ss--start');
      expect(dialog.querySelector('.ss__body')).toHaveClass('ss__body--fill');
      expect(dialog.querySelector('.ss__body > .bd__paneBody .bd__tree')).toBeTruthy();
      expect(dialog.querySelector('.chip, select')).toBeNull();
      expect(dialog.querySelector('.bd__paneBody')).toHaveClass('bd__paneBody--side');
    });

    /**
     * The body passes the height down: the search stays above the tree, which scrolls by itself
     * down to the bottom padding of the sheet. The close button of the sheet closes it.
     */
    it('opens the tree in the shared sheet from the bottom on a phone', async () => {
      const view = await setup({ wide: false, phone: true });
      (view.container.querySelector('.bd__pathChip') as HTMLButtonElement).click();
      view.fixture.detectChanges();
      const dialog = view.getByRole('dialog', { name: 'Kostenstellen' });
      expect(dialog).toHaveClass('ss--bottom');
      expect(dialog.querySelector('.ss__handle')).toBeTruthy();
      expect(dialog.querySelector('.ss__body')).toHaveClass('ss__body--fill');
      const pane = dialog.querySelector('.ss__body > .bd__paneBody') as HTMLElement;
      expect(pane).toHaveClass('bd__paneBody--side');
      expect(pane.querySelector(':scope > app-search-pill + .bd__tree')).toBeTruthy();
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
      expect(chip).not.toHaveClass('on');
      chip.click();
      view.fixture.detectChanges();
      expect(c.overviewOpen()).toBe(true);
      expect(chip).toHaveClass('on');
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
    });
  });

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

  /**
   * A cost centre that is not in the tree is its own root. With nothing selected there is no
   * request and no rows, and the URL loses the params.
   */
  it('copes with an unknown cost centre, an unknown year and an empty selection', async () => {
    const { c, http } = await setup();
    const nav = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectedFyId.set('nope');
    expect(c.selectedYear()).toBeNull();
    c.selectedFyId.set('fy-1');
    c.selectKs('ghost');
    expect(c.selectedBudgetId()).toBe('ghost');
    expect(c.breadcrumbs()).toEqual([]);
    expect(c.distribution()).toEqual([]);
    expect(c.usageRows()).toEqual([]);
    flushApps(http);
    c['setSelection']('', '', '');
    http.expectNone((r) => r.url.endsWith('/applications'));
    expect(c.apps()).toEqual([]);
    c['syncUrl']();
    expect(nav).toHaveBeenLastCalledWith([], expect.objectContaining({
      queryParams: { budget: null, costCentre: null, fy: null },
    }));
  });

  /** A node without a currency still formats in euro. */
  it('formats money with and without cents', async () => {
    const { c } = await setup();
    expect(c.money(100)).toMatch(/100,00/);
    expect(c.money('250')).toContain('250');
    expect(c.money(null)).toContain('0');
    expect(c.money('')).toContain('0');
    expect(c.money(5, 'USD')).toMatch(/[$]|USD/);
    expect(c.moneyShort(1234.56)).toMatch(/^1\.235\s€$/);
    expect(c.money(1, '')).toContain('€');
    expect(c.moneyShort(1, '')).toContain('€');
  });

  /** The placeholder has the two columns of the wide layout, so the page does not jump. */
  it('shows the loading state, then the error when the tree request fails', async () => {
    const { c, http, fixture } = await bare();
    fixture.detectChanges();
    expect(c.loading()).toBe(true);
    expect(fixture.nativeElement.querySelector('[aria-busy="true"]')).toHaveClass('bd--wide');
    expect(fixture.nativeElement.querySelectorAll('main')).toHaveLength(0);
    http.expectOne((r) => r.url.endsWith('/budgets')).flush('x', { status: 500, statusText: 'err' });
    fixture.detectChanges();
    expect(c.error()).toBe(true);
    expect(c.loading()).toBe(false);
    expect(loadErrorToast()).not.toBeNull();
  });

  it('never claims the budget is empty while it is still loading', async () => {
    const { c, http, fixture, container } = await bare();
    fixture.detectChanges();
    expect(c.loading()).toBe(true);
    expect(container.querySelector('.bd__empty')).toBeNull();
    expect(container.querySelector('[aria-busy="true"] .skel-text')).toBeTruthy();
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    fixture.detectChanges();
    expect(container.querySelector('.bd__empty')).toBeTruthy();
    expect(container.querySelector('[aria-busy="true"]')).toBeNull();
    expect(screen.getByText('Noch keine Budgetdaten')).toBeTruthy();
  });

  /** Without a year every figure reads as zero, so the tree would show 0 € for a round trip. */
  it('keeps the skeleton until the year of the figures is in', async () => {
    const { c, http, fixture, container } = await bare();
    http.expectOne((r) => r.url.endsWith('/budgets')).flush(TREE);
    fixture.detectChanges();
    expect(c.loading()).toBe(false);
    expect(c.showSkeleton()).toBe(true);
    expect(container.querySelector('[aria-busy="true"] .skel-text')).toBeTruthy();
    expect(container.querySelector('.bd__empty')).toBeNull();
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
    flushApps(http);
    fixture.detectChanges();
    expect(c.showSkeleton()).toBe(false);
    expect(container.querySelector('[aria-busy="true"]')).toBeNull();
  });

  /**
   * The tree and the years are cached reads, which answer twice when the fresh answer differs. A
   * root that answers twice must not count as two, and an answer of an older tree round must not
   * count against the newer one. Either would claim "no fiscal year" while b-qs is still loading.
   */
  it('counts each root once per tree answer, however often its years answer', async () => {
    setViewport(true);
    const tree$ = new Subject<BudgetTreeNode[]>();
    const years = new Map<string, Subject<FiscalYear[]>[]>();
    const api = {
      tree: () => tree$,
      cachedFiscalYears: (id: string) => {
        const s = new Subject<FiscalYear[]>();
        years.set(id, [...(years.get(id) ?? []), s]);
        return s;
      },
    };
    const view = await render(BudgetDashboardComponent, {
      providers: [...providers({}), { provide: BudgetTreeApi, useValue: api }],
    });
    const c = view.fixture.componentInstance as unknown as Inst;
    const roots = [node({ id: 'b-vs', key: 'VS' }), node({ id: 'b-qs', key: 'QS' })];

    tree$.next(roots);
    const [vsOld] = years.get('b-vs')!;
    vsOld.next([]);
    vsOld.next([]);
    expect(c.emptyReason()).toBeNull();
    expect(c.showSkeleton()).toBe(true);

    tree$.next(roots);
    const [, vsNew] = years.get('b-vs')!;
    const [qsOld, qsNew] = years.get('b-qs')!;
    vsNew.next([]);
    qsOld.next([]);
    expect(c.emptyReason()).toBeNull();

    qsNew.next([]);
    expect(c.emptyReason()).toBe('noFiscalYear');
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

  it('prunes inactive cost centres from the tree, the roots and the sheet', async () => {
    const tree = [
      node({
        id: 'b-vs',
        key: 'VS',
        byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '100' })],
        children: [
          node({ id: 'b-hide', key: 'H', active: false, byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '50' })] }),
          node({ id: 'b-show', key: 'S', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '50' })] }),
        ],
      }),
      node({ id: 'b-secret', key: 'SEC', active: false, byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
    ];
    const { c } = await setup({ tree, perms: ['budget.view'] });
    expect(c.tops().map((n: { id: string }) => n.id)).toEqual(['b-vs']);
    const ids = c.usageRows().map((r: { node: { id: string } }) => r.node.id);
    expect(ids).toEqual(['b-show']);
    expect(c.treeRows().map((r: { node: { id: string } }) => r.node.id)).not.toContain('b-hide');
  });

  describe('selection from the URL', () => {
    it('restores budget, cost centre and year from the query params', async () => {
      const { c } = await setup({ fys: [FY, FY2], queryParams: { budget: 'b-vs', costCentre: 'b-800', fy: 'fy-2' } });
      expect(c.selectedBudgetId()).toBe('b-vs');
      expect(c.selectedKsId()).toBe('b-800');
      expect(c.selectedFyId()).toBe('fy-2');
    });

    it('follows the URL when the palette sends it here while it is already here', async () => {
      const { c, params, http } = await setup();
      expect(c.selectedKsId()).toBe('b-vs');
      params.next(convertToParamMap({ costCentre: 'b-800' }));
      expect(c.selectedKsId()).toBe('b-800');
      flushApps(http);
    });

    it('derives the root from a cost centre the link names on its own', async () => {
      const tree = [
        node({ id: 'b-other', key: 'OTHER', name: 'Andere', byFiscalYear: [alloc({ fiscalYearId: 'fy-1' })] }),
        ...TREE,
      ];
      const { c } = await setup({ tree, queryParams: { costCentre: 'b-800' } });
      expect(c.selectedKsId()).toBe('b-800');
      expect(c.selectedBudgetId()).toBe('b-vs');
    });

    it('leaves the selection alone when the URL repeats what is already shown', async () => {
      const { c, params } = await setup();
      const before = [c.selectedBudgetId(), c.selectedKsId(), c.selectedFyId()];
      params.next(convertToParamMap({ budget: 'b-vs', costCentre: 'b-vs', fy: 'fy-1' }));
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
      const { c } = await setup({ tree, queryParams: { costCentre: 'b-leaf' } });
      expect(c.selectedKsId()).toBe('b-leaf');
      expect(c.selectedBudgetId()).toBe('b-sub');
    });

    it('ignores invalid query params and defaults to the first root and year', async () => {
      const { c } = await setup({ queryParams: { budget: 'ghost', costCentre: 'ghost', fy: 'ghost' } });
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

    /**
     * Only b-b has years so far, so it becomes the default; the later answer for b-a changes
     * nothing.
     */
    it('without a URL the default is the first root of the tree, not the root whose years arrive first', async () => {
      const tree = [
        node({ id: 'b-a', key: 'A', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
        node({ id: 'b-b', key: 'B', byFiscalYear: [alloc({ fiscalYearId: 'fy-1', allocated: '10' })] }),
      ];
      const { c, http, fixture } = await bare();
      http.expectOne((r) => r.url.endsWith('/budgets')).flush(tree);
      http.expectOne((r) => r.url.endsWith('/budgets/b-b/fiscal-years')).flush([{ ...FY, budgetId: 'b-b' }]);
      fixture.detectChanges();
      expect(c.selectedBudgetId()).toBe('');
      http.expectOne((r) => r.url.endsWith('/budgets/b-a/fiscal-years')).flush([{ ...FY, budgetId: 'b-a' }]);
      fixture.detectChanges();
      expect(c.selectedBudgetId()).toBe('b-a');
    });

    it('selects nothing until a root with a fiscal year is loaded', async () => {
      const { c, http, fixture } = await bare();
      http.expectOne((r) => r.url.endsWith('/budgets')).flush([node({ id: 'b-vs', key: 'VS' })]);
      http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
      fixture.detectChanges();
      expect(c.selectedBudgetId()).toBe('');
    });
  });

  describe('empty states', () => {
    it('blames the missing fiscal year, not the cost centres, when only the year is gone', async () => {
      const view = await setup({ fys: [] });
      expect(view.container.querySelector('.bd__empty')).toBeTruthy();
      expect(screen.getByText('Kein Haushaltsjahr angelegt')).toBeTruthy();
      expect(screen.queryByText('Noch keine Budgetdaten')).toBeNull();
      const link = screen.getByRole('link', { name: 'Haushaltsjahr anlegen' });
      expect(link.getAttribute('href')).toBe('/admin/budgets');
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

describe('BudgetDashboardComponent Verknüpft (spec 000552)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  it('shows the cards that link the cost centre on its card, with the actions', async () => {
    const todos = {
      linked: jest.fn(() =>
        of([
          {
            id: 'k-1',
            boardId: 'b-1',
            boardName: 'StuPa',
            title: 'Inventur Bühnentechnik',
            columnName: 'Offen',
            isDone: false,
            dueDate: null,
            assignees: [],
            event: null,
            balance: null,
          },
        ]),
      ),
      boards: jest.fn(() => of([{ id: 'b-1', name: 'StuPa', kind: 'gremium', gremiumId: 'g-1', canWrite: true }])),
    };
    await setup({ queryParams: { costCentre: 'b-810' }, todos });
    expect(todos.linked).toHaveBeenCalledWith('budget', 'b-810');
    const list = document.querySelector('app-todo-linked-list[kind="budget"]') as HTMLElement;
    expect(within(list).getByRole('heading', { name: 'Verknüpft' })).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: 'Inventur Bühnentechnik' })).toHaveAttribute('href', '/todos?card=k-1');
    expect(within(list).getByRole('button', { name: 'To-Do anlegen' })).toBeInTheDocument();
  });

  describe('views', () => {
    it('§F/finance/budget/000804: shows the view switch only when a top level has the plan switch on', async () => {
      const off = await setup();
      expect(off.container.querySelector('app-segmented')).toBeNull();
      expect(off.c.planTop()).toBeNull();
      off.c.setMode('plan');
    });

    it('§F/finance/budget/000804: opens Planung with the top level and the year of this view', async () => {
      const tree = [{ ...TREE[0], planEnabled: true }, ...TREE.slice(1)];
      const view = await setup({ tree });
      expect(view.container.querySelector('app-segmented')).not.toBeNull();
      const navigate = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      view.c.setMode('run');
      view.c.setMode(null);
      expect(navigate).not.toHaveBeenCalled();
      view.c.setMode('plan');
      expect(navigate).toHaveBeenCalledWith(['/budget/plan'], { queryParams: { budget: 'b-vs', fy: 'fy-1', costCentre: null } });
      view.c.selectedBudgetId.set('other');
      view.c.setMode('plan');
      expect(navigate).toHaveBeenLastCalledWith(['/budget/plan'], { queryParams: { budget: 'b-vs', fy: null, costCentre: null } });
    });

    it('§F/finance/budget/000804: puts the view switch below the title on a phone', async () => {
      const tree = [{ ...TREE[0], planEnabled: true }, ...TREE.slice(1)];
      const view = await setup({ tree, wide: false, phone: true });
      expect(view.container.querySelector('.bd__top app-segmented')).not.toBeNull();
    });
  });

  describe('Kostenstellen and allocations by hand', () => {
    const PLAN_TREE = [{ ...TREE[0], planEnabled: true }];
    const planUrl = (r: { url: string }) => r.url.endsWith('/plan');
    const treeUrl = (r: { url: string }) => r.url.endsWith('/budgets');
    const lineOf = (budgetId: string) => ({ budgetId, amount: '1' });
    const planOf = (state: string, ids: string[]) => ({ id: 'p', budgetId: 'b-vs', fiscalYearId: 'fy-1', versions: [{ id: 'v', number: 0, state, steps: [], lines: ids.map(lineOf) }] });

    it('§F/finance/budget/000834: shows an inactive Kostenstelle with its mark to a person who can set it active again', async () => {
      const tree = [{ ...TREE[0], children: [{ ...TREE[0].children[0], active: false }, TREE[0].children[1]] }];
      const view = await setup({ tree });
      expect(view.c.treeRows().map((r: { node: { id: string } }) => r.node.id)).toContain('b-800');
      expect(within(view.container.querySelector('.bd__tree') as HTMLElement).getByText('inaktiv')).toBeInTheDocument();
    });

    it('§F/finance/budget/000831: edits by hand in a budget without a Haushaltsplan', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-800' } });
      expect(screen.getByRole('button', { name: 'Kostenstelle anlegen' })).toBeInTheDocument();
      expect(view.container.querySelector('app-cost-centre-settings')).not.toBeNull();
      expect(screen.queryByRole('combobox', { name: /Seite/ })).toBeNull();
      expect(screen.getByRole('heading', { name: 'Zuteilung' })).toBeInTheDocument();
      expect(view.container.querySelector('[name="allocation-b-800"]')).not.toBeNull();
      await userEvent.click(within(view.container.querySelector('.bd__head') as HTMLElement).getByRole('button', { name: 'Weitere Aktionen' }));
      expect((await screen.findAllByRole('menuitem')).map((i) => i.textContent?.trim())).toEqual(['Buchungen ansehen', 'Kostenstelle löschen']);
    });

    it('offers nothing to edit without budget.structure, and no settings for the budget itself', async () => {
      const reader = await setup({ perms: ['budget.view'], queryParams: { costCentre: 'b-800' } });
      expect(screen.queryByRole('button', { name: 'Kostenstelle anlegen' })).toBeNull();
      expect(reader.container.querySelector('app-cost-centre-settings')).toBeNull();
      expect(reader.container.querySelector('[name="allocation-b-800"]')).toBeNull();
      TestBed.resetTestingModule();
      const top = await setup();
      expect(top.container.querySelector('app-cost-centre-settings')).toBeNull();
      expect(top.container.querySelector('[name="allocation-b-vs"]')).not.toBeNull();
    });

    it('has no allocation field in a closed year, and no Gremien when their read fails', async () => {
      const view = await setup({ fys: [{ ...FY, closedAt: '2026-12-31T00:00:00Z' }], gremien: throwError(() => new Error('down')) });
      expect(view.c.allocatable()).toBe(false);
      expect(view.c.gremiumOptions()).toEqual([]);
    });

    it('§F/finance/budget/000822: shows in a year with a plan in force only its Kostenstellen and edits nothing by hand', async () => {
      const view = await setup({ tree: [...PLAN_TREE, node({ id: 'b-qs', byFiscalYear: [alloc({ fiscalYearId: 'fy-1' })] })], queryParams: { costCentre: 'b-900' } });
      expect(view.c.yearPlan()).toBeUndefined();
      view.http.expectOne(planUrl).flush(planOf('in_force', ['b-800']));
      view.fixture.detectChanges();
      const ids = view.c.treeRows().map((r: { node: { id: string } }) => r.node.id);
      expect(ids).toContain('b-800');
      expect(ids).toContain('b-qs');
      expect(view.c.byHand()).toBe(false);
      expect(view.c.allocatable()).toBe(false);
      expect(view.c.moreSections().flatMap((sec: { items: { id: string }[] }) => sec.items.map((i) => i.id))).not.toContain('new');
    });

    it('falls back to the budget when the plan in force has no line for the selected Kostenstelle', async () => {
      const tree = [{ ...PLAN_TREE[0], children: [node({ id: 'b-out', parentId: 'b-vs', byFiscalYear: [alloc({ fiscalYearId: 'fy-1' })] })] }];
      const view = await setup({ tree, queryParams: { costCentre: 'b-out' } });
      view.http.expectOne(planUrl).flush(planOf('in_force', []));
      expect(view.c.selectedKsId()).toBe('b-vs');
    });

    it('shows every Kostenstelle while the plan of the year is a draft', async () => {
      const view = await setup({ tree: PLAN_TREE, queryParams: { costCentre: 'b-800' } });
      view.http.expectOne(planUrl).flush(planOf('draft', []));
      expect(view.c.treeRows().map((r: { node: { id: string } }) => r.node.id)).toContain('b-900');
      expect(view.c.sided()).toBe(true);
      expect(view.c.byHand()).toBe(false);
    });

    it('edits by hand in a year without a plan, and keeps the answer of a year that is no longer shown', async () => {
      const view = await setup({ tree: PLAN_TREE, fys: [FY, FY2] });
      const first = view.http.expectOne(planUrl);
      view.c.selectYear('fy-2');
      const second = view.http.expectOne(planUrl);
      first.flush(planOf('in_force', []));
      expect(view.c.yearPlan()).toBeUndefined();
      second.flush({ code: 'plan_not_found' }, { status: 404, statusText: 'Not Found' });
      expect(view.c.yearPlan()).toBeNull();
      expect(view.c.byHand()).toBe(true);
      view.c.selectYear('fy-1');
      const third = view.http.expectOne(planUrl);
      view.c.selectYear('fy-2');
      third.flush({}, { status: 500, statusText: 'Error' });
      expect(view.c.yearPlan()).toBeUndefined();
      view.http.expectOne(planUrl).flush(planOf('draft', []));
    });

    it('§F/finance/budget/000829: the floating button creates a Kostenstelle below the shown one, and the page selects it', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-800' } });
      await userEvent.click(screen.getByRole('button', { name: 'Kostenstelle anlegen' }));
      const dialog = await screen.findByRole('dialog', { name: 'Kostenstelle anlegen' });
      expect(dialog.querySelector('[data-cc-trigger]')).toHaveTextContent('Dezentrale Einrichtungen');
      await userEvent.type(dialog.querySelector('[name="ccKey"] input') as HTMLElement, '820');
      await userEvent.type(dialog.querySelector('[name="ccName"] input') as HTMLElement, 'Labor');
      await userEvent.click(within(dialog).getByRole('button', { name: 'Anlegen' }));
      const post = view.http.expectOne((r) => r.method === 'POST' && r.url.endsWith('/budgets'));
      expect(post.request.body).toEqual({ parentId: 'b-800', key: '820', name: 'Labor', side: null, currency: 'EUR' });
      post.flush({ id: 'b-900' });
      view.http.expectOne(treeUrl).flush(TREE);
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Kostenstelle anlegen' })).toBeNull());
      expect(screen.getByRole('heading', { level: 2, name: 'Rücklage' })).toBeInTheDocument();
    });

    it('§F/finance/budget/000829: keeps the shown Kostenstelle when the new one is not in the tree, and closes the dialog from Abbrechen', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-800' } });
      await userEvent.click(screen.getByRole('button', { name: 'Kostenstelle anlegen' }));
      const dialog = await screen.findByRole('dialog', { name: 'Kostenstelle anlegen' });
      await userEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen' }));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Kostenstelle anlegen' })).toBeNull());
      view.c.onCreated({ id: 'gone', plan: null });
      view.http.expectOne(treeUrl).flush(TREE);
      view.c.onCreated({ id: null, plan: null });
      view.http.expectOne(treeUrl).flush(TREE);
      expect(view.c.selectedKsId()).toBe('b-800');
    });

    it('selects the budget when the selected Kostenstelle is gone after a refresh, and names a failed refresh', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-900' } });
      const error = jest.spyOn(TestBed.inject(ToastService), 'error');
      view.c.refreshTree();
      view.http.expectOne(treeUrl).flush([{ ...TREE[0], children: [TREE[0].children[0]] }]);
      expect(view.c.selectedKsId()).toBe('b-vs');
      view.c.refreshTree();
      view.http.expectOne(treeUrl).flush({}, { status: 500, statusText: 'Error' });
      expect(error).toHaveBeenCalledWith('Die Budget-Statistik konnte nicht geladen werden.');
    });

    it('§F/finance/budget/000850: reads the tree after a save of a section that went off the page', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-800' } });
      const settings = view.fixture.debugElement.query(By.directive(CostCentreSettingsComponent)).componentInstance as CostCentreSettingsComponent;
      settings.whenGone()?.();
      expect(view.http.match(treeUrl)).toHaveLength(1);
    });

    it('§F/finance/budget/000851: drops the answer of a tree read that went out before the read on the page', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-800' } });
      view.c.refreshTree();
      TestBed.inject(HttpCacheService).invalidate('/api/budgets');
      view.c.refreshTree();
      const reads = view.http.match(treeUrl);
      expect(reads).toHaveLength(2);
      reads[1].flush([{ ...TREE[0], name: 'Neu' }]);
      reads[0].flush([{ ...TREE[0], name: 'Alt' }]);
      expect(view.c.tree()[0].name).toBe('Neu');
    });

    it('§F/finance/budget/000832: deletes the selected Kostenstelle after the confirmation', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-810' } });
      const toast = TestBed.inject(ToastService);
      const success = jest.spyOn(toast, 'success');
      const error = jest.spyOn(toast, 'error');
      const remove = async (button: string) => {
        await userEvent.click(within(view.container.querySelector('.bd__head') as HTMLElement).getByRole('button', { name: 'Weitere Aktionen' }));
        await userEvent.click(await screen.findByRole('menuitem', { name: 'Kostenstelle löschen' }));
        const dialog = await screen.findByRole('dialog', { name: 'Kostenstelle löschen?' });
        expect(dialog).toHaveTextContent('„Werkstatt“ (VS-800-810) wird gelöscht. Das lässt sich nicht rückgängig machen.');
        await userEvent.click(within(dialog).getByRole('button', { name: button }));
      };
      const del = (r: { method: string; url: string }) => r.method === 'DELETE' && r.url.endsWith('/budgets/b-810');
      await remove('Abbrechen');
      view.http.expectNone(del);
      await remove('Löschen');
      view.http.expectOne(del).flush({ code: 'budget_has_bookings' }, { status: 409, statusText: 'Conflict' });
      expect(error).toHaveBeenCalledWith('Die Kostenstelle hat Buchungen und lässt sich nicht löschen.');
      expect(screen.getByRole('heading', { level: 2, name: 'Werkstatt' })).toBeInTheDocument();
      await remove('Löschen');
      view.http.expectOne(del).flush(null);
      expect(success).toHaveBeenCalledWith('Kostenstelle gelöscht.');
      view.http.expectOne(treeUrl).flush(TREE);
      view.fixture.detectChanges();
      expect(screen.getByRole('heading', { level: 2, name: 'Dezentrale Einrichtungen' })).toBeInTheDocument();
      view.c.deleteNode();
      view.http.expectNone((r) => r.method === 'DELETE');
    });

    it('§F/finance/budget/000833: a field without a value saves nothing', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-800' } });
      view.fixture.componentInstance.editAllocation(null);
      view.fixture.componentInstance.saveAllocation();
      view.http.expectNone((r) => r.method === 'PUT');
    });

    it('§F/finance/budget/000833: saves the allocation when the field loses the focus', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-800' } });
      const toast = TestBed.inject(ToastService);
      const success = jest.spyOn(toast, 'success');
      const put = (r: { method: string; url: string }) => r.method === 'PUT' && r.url.endsWith('/budgets/b-800/allocations/fy-1');
      const field = () => view.container.querySelector('[name="allocation-b-800"]') as HTMLInputElement;
      const retype = async (value: string) => {
        await userEvent.clear(field());
        if (value) await userEvent.type(field(), value);
        await userEvent.tab();
      };
      await waitFor(() => expect(field().value).toBe('400,00'));
      await userEvent.click(field());
      await userEvent.tab();
      await retype('400');
      view.http.expectNone(put);
      await userEvent.click(field());
      await userEvent.keyboard('{Enter}');
      view.http.expectNone(put);
      await retype('450');
      const req = view.http.expectOne(put);
      expect(req.request.body).toEqual({ allocated: '450' });
      req.flush({});
      expect(success).toHaveBeenCalledWith('Zuteilung gespeichert.');
      view.http.expectOne(treeUrl).flush(TREE);
      await userEvent.clear(field());
      await userEvent.type(field(), '460{Enter}');
      const byEnter = view.http.expectOne(put);
      expect(byEnter.request.body).toEqual({ allocated: '460' });
      byEnter.flush({});
      view.http.expectOne(treeUrl).flush(TREE);
    });

    it('§F/finance/budget/000833: an empty or refused allocation shows the saved one again and names the cause', async () => {
      const view = await setup({ queryParams: { costCentre: 'b-800' } });
      const error = jest.spyOn(TestBed.inject(ToastService), 'error');
      const put = (r: { method: string; url: string }) => r.method === 'PUT' && r.url.endsWith('/budgets/b-800/allocations/fy-1');
      const field = () => view.container.querySelector('[name="allocation-b-800"]') as HTMLInputElement;
      const retype = async (value: string) => {
        await userEvent.clear(field());
        if (value) await userEvent.type(field(), value);
        await userEvent.tab();
      };
      await retype('');
      view.http.expectNone(put);
      await waitFor(() => expect(field().value).toBe('400,00'));
      await retype('9999');
      view.http.expectOne(put).flush({ code: 'children_allocation_exceeds_parent' }, { status: 422, statusText: 'Unprocessable' });
      expect(error).toHaveBeenLastCalledWith('Die Zuteilung liegt über der Zuteilung der übergeordneten Kostenstelle. Erhöhe zuerst diese.');
      view.http.expectOne(treeUrl).flush(TREE);
      await waitFor(() => expect(field().value).toBe('400,00'));
      await retype('1');
      view.http.expectOne(put).flush({ code: 'parent_allocation_below_children' }, { status: 422, statusText: 'Unprocessable' });
      expect(error).toHaveBeenLastCalledWith('Die Zuteilung liegt unter der Summe der untergeordneten Kostenstellen.');
      view.http.expectOne(treeUrl).flush(TREE);
      await retype('2');
      view.http.expectOne(put).flush({}, { status: 500, statusText: 'Error' });
      expect(error).toHaveBeenLastCalledWith('Die Zuteilung konnte nicht gespeichert werden.');
      view.http.expectOne(treeUrl).flush(TREE);
      await retype('-5');
      view.http.expectNone(put);
      expect(error).toHaveBeenCalledTimes(4);
      await retype('99999999999');
      view.http.expectNone(put);
      expect(error).toHaveBeenCalledTimes(5);
      view.c.selectedKsId.set('gone');
      view.c.editAllocation('1');
      view.c.saveAllocation();
      view.http.expectNone(put);
    });
  });
});
