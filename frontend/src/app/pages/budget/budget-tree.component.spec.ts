import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../testing/meeting-fixtures';
import { AdminApiService } from '../admin/admin-api.service';
import { BudgetTreeComponent } from './budget-tree.component';
import type { BudgetTreeNode, FiscalYear } from './budget-tree.api';

const FY: FiscalYear = {
  id: 'fy-1',
  budgetId: 'b-vs',
  year: 2026,
  display: '2026',
  startDate: '2026-01-01',
  endDate: '2026-12-31',
  active: true,
};

function fullNode(over: Partial<BudgetTreeNode>): BudgetTreeNode {
  return {
    id: 'x',
    parentId: null,
    gremiumId: 'g-1',
    key: 'K',
    pathKey: 'K',
    name: 'N',
    currency: 'EUR',
    active: true,
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [],
    ...over,
  };
}

const TREE: BudgetTreeNode[] = [
  fullNode({
    id: 'b-vs',
    key: 'VS',
    pathKey: 'VS',
    name: 'VS-Mittel',
    acceptedStateKeys: ['accepted'],
    deniedStateKeys: ['denied'],
    byFiscalYear: [
      {
        fiscalYearId: 'fy-1',
        allocated: '1000',
        bound: '200',
        expended: '50',
        income: '0',
        committed: '250',
        requested: '40',
        available: '750',
      },
    ],
    children: [
      fullNode({
        id: 'b-800',
        parentId: 'b-vs',
        key: '800',
        pathKey: 'VS-800',
        name: 'Dezentrale Einrichtungen',
        byFiscalYear: [
          {
            fiscalYearId: 'fy-1',
            allocated: '400',
            bound: '80',
            expended: '20',
            income: '0',
            committed: '100',
            requested: '10',
            available: '300',
          },
        ],
      }),
    ],
  }),
];

interface Mocks {
  gremien?: 'ok' | 'error';
  flow?: 'states' | 'null' | 'error';
  /** Front-end `budget.structure` gate. `false` hides the fiscal-year row actions. */
  can?: boolean;
}

function makeAdminMock(m: Mocks) {
  return {
    listGremienOptions: () =>
      m.gremien === 'error'
        ? throwError(() => new Error('boom'))
        : of([{ id: 'g-1', name: 'StuPa' }]),
    getGlobalFlow: () => {
      if (m.flow === 'error') return throwError(() => new Error('boom'));
      if (m.flow === 'null') return of(null);
      return of({
        states: [
          { key: 'accepted', label: { de: 'Angenommen', en: 'Accepted' } },
          { key: 'orphan', label: {} }, // No German label, so the code falls back to the key.
        ],
      });
    },
  };
}

const toastSpy = {
  success: jest.fn(),
  error: jest.fn(),
};

async function setup(m: Mocks = { gremien: 'ok', flow: 'null' }) {
  toastSpy.success.mockClear();
  toastSpy.error.mockClear();
  const view = await render(BudgetTreeComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: AdminApiService, useValue: makeAdminMock(m) },
      { provide: ToastService, useValue: toastSpy },
      { provide: AuthService, useValue: { can: () => m.can !== false } },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  // The initial reload() sends a tree GET and one fiscal-years GET per top. Here the
  // only top is b-vs.
  http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(TREE);
  http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
  view.fixture.detectChanges();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, http, c, toast: toastSpy };
}

/** Flush a reload() cycle: the tree GET and one fiscal-years GET per top. */
function flushReload(http: HttpTestingController, tree: BudgetTreeNode[] = TREE): void {
  http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(tree);
  for (const top of tree.filter((n) => n.parentId === null)) {
    http.expectOne((r) => r.url.endsWith(`/budgets/${top.id}/fiscal-years`)).flush([FY]);
  }
}

describe('BudgetTreeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders the cost-centre tree with full path keys', async () => {
    await setup();
    expect(screen.getByText('VS')).toBeInTheDocument();
    expect(screen.getByText('VS-800')).toBeInTheDocument();
    expect(screen.getByText('Dezentrale Einrichtungen')).toBeInTheDocument();
  });

  it('flattens nested children into rows (pre-order) with depth', async () => {
    const { c } = await setup();
    expect(c.rows().map((r: { node: { pathKey: string } }) => r.node.pathKey)).toEqual([
      'VS',
      'VS-800',
    ]);
    expect(c.rows()[1].depth).toBe(1);
  });

  it('rows() is empty when no top is selected', async () => {
    const { c } = await setup();
    c.selectedTopId.set('nope');
    expect(c.selectedTop()).toBeNull();
    expect(c.rows()).toEqual([]);
    expect(c.selectedTopLabel()).toBe('');
  });

  it('selectedTopLabel renders "key – name" for the selected top', async () => {
    const { c } = await setup();
    expect(c.selectedTopLabel()).toBe('VS – VS-Mittel');
  });

  it('exposes the columns and identity helpers', async () => {
    const { c } = await setup();
    expect(c.columns().map((col: { key: string }) => col.key)).toEqual([
      'node',
      'allocated',
      'bound',
      'expended',
      'income',
      'available',
      'color',
      'actions',
    ]);
    const row = { node: TREE[0], depth: 0 };
    expect(c.rowId(row)).toBe('b-vs');
    expect(c.childExpanded(row)).toBe(false);
    // The inline create row stands after the last row of the parent's subtree.
    c.addingChildOf.set('b-vs');
    expect(c.childExpanded(row)).toBe(false);
    expect(c.childExpanded({ node: TREE[0].children[0], depth: 1 })).toBe(true);
    c.addingChildOf.set('b-800');
    expect(c.childExpanded({ node: TREE[0].children[0], depth: 1 })).toBe(true);
    // The label of the inline row names the nested parent.
    expect(c.childParent()?.id).toBe('b-800');
    // A parent that is not in the visible rows places no create row.
    c.addingChildOf.set('ghost');
    expect(c.childExpanded(row)).toBe(false);
    expect(c.childParent()).toBeNull();
  });

  it('leaves out the amounts a narrow page has no room for', async () => {
    const { c } = await setup();
    const keys = (): string[] => c.columns().map((col: { key: string }) => col.key);
    c.width.set(900);
    expect(keys()).not.toContain('income');
    expect(keys()).toContain('expended');
    // Intl puts a no-break space before the currency sign.
    const plain = (t: string): string => t.replace(/\u00a0/g, ' ');
    expect(plain(c.availableTitle(TREE[0]))).toBe('Einnahmen 0 €');
    c.width.set(700);
    expect(keys()).not.toContain('expended');
    expect(plain(c.availableTitle(TREE[0]))).toBe('Ausgegeben 50 € · Einnahmen 0 €');
    c.width.set(1200);
    expect(keys()).toContain('income');
    expect(c.availableTitle(TREE[0])).toBe('');
    // Without an allocation view there is no tooltip.
    c.width.set(700);
    c.selectedFyId.set('other');
    expect(c.availableTitle(TREE[0])).toBe('');
  });

  it('folds and unfolds a subtree', async () => {
    const { c, fixture } = await setup();
    const fold = screen.getByRole('button', { name: /^Unter-Kostenstellen ein- oder ausklappen: VS-Mittel/ });
    expect(fold).toHaveAttribute('aria-expanded', 'true');
    await userEvent.click(fold);
    fixture.detectChanges();
    expect(c.rows().map((r: { node: { id: string } }) => r.node.id)).toEqual(['b-vs']);
    expect(c.isCollapsed('b-vs')).toBe(true);
    expect(fold).toHaveAttribute('aria-expanded', 'false');
    // A sub cost centre opens its folded parent, so the inline row can show.
    c.startAddChild(TREE[0]);
    expect(c.isCollapsed('b-vs')).toBe(false);
    c.toggleCollapse('b-vs');
    c.toggleCollapse('b-vs');
    expect(c.isCollapsed('b-vs')).toBe(false);
  });

  it('shows the colour of a node: own, from a parent, or none', async () => {
    const tree = [
      fullNode({
        id: 'r',
        key: 'R',
        pathKey: 'R',
        name: 'Root',
        children: [
          fullNode({
            id: 'a',
            parentId: 'r',
            key: 'A',
            pathKey: 'R-A',
            name: 'A',
            color: '#ff0000',
            children: [fullNode({ id: 'a1', parentId: 'a', key: '1', pathKey: 'R-A-1', name: 'A1' })],
          }),
        ],
      }),
    ];
    const { c, http } = await setup();
    c['reload']();
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(tree);
    http.expectOne((r) => r.url.endsWith('/budgets/r/fiscal-years')).flush([FY]);
    const [root, a] = [tree[0], tree[0].children[0]];
    const a1 = a.children[0];
    expect(c.swatch(a)).toEqual({ kind: 'own', color: '#ff0000' });
    expect(c.swatch(a1)).toEqual({ kind: 'inherited', color: '#ff0000' });
    expect(c.swatch(root)).toEqual({ kind: 'none', color: null });
    expect(c.swatchLabel(c.swatch(a))).toBe('Eigene Farbe #ff0000');
    expect(c.swatchLabel(c.swatch(a1))).toBe('Farbe vom Elternknoten (#ff0000)');
    expect(c.swatchLabel(c.swatch(root))).toBe('Keine Farbe');
  });

  it('marks an inactive cost centre and a negative balance', async () => {
    const neg = fullNode({
      id: 'n',
      key: 'N',
      pathKey: 'N',
      name: 'Negativ',
      active: false,
      byFiscalYear: [
        { fiscalYearId: 'fy-1', allocated: '10', bound: '20', expended: '0', income: '0', committed: '20', requested: '0', available: '-10' },
      ],
    });
    const { c, http, fixture } = await setup();
    c['reload']();
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush([neg]);
    http.expectOne((r) => r.url.endsWith('/budgets/n/fiscal-years')).flush([FY]);
    fixture.detectChanges();
    expect(c.isNegative(neg)).toBe(true);
    expect(c.amount(neg, 'available')).toContain('10');
    expect(screen.getByText(/N · inaktiv/)).toBeInTheDocument();
    c.selectedFyId.set('other');
    expect(c.isNegative(neg)).toBe(false);
    expect(c.amount(neg, 'allocated')).toBe('—');
  });

  it('offers the row actions in a menu on a phone', async () => {
    const { c } = await setup();
    const sections = c.rowMenu();
    expect(sections[0].items.map((i: { id: string }) => i.id)).toEqual(['edit', 'limit', 'child']);
    expect(sections[0].items[1].disabledReason).toBeNull();
    c.selectedFyId.set('');
    expect(c.rowMenu()[0].items[1].disabledReason).toBe('Noch kein Haushaltsjahr');
    c.onRowMenu(TREE[0], { id: 'edit', label: '' });
    expect(c.editNode()).toBe(TREE[0]);
    c.onRowMenu(TREE[0], { id: 'limit', label: '' });
    expect(c.limitNode()).toBe(TREE[0]);
    c.onRowMenu(TREE[0], { id: 'child', label: '' });
    expect(c.addingChildOf()).toBe('b-vs');
    c.onRowMenu(TREE[0], { id: 'delete', label: '' });
    expect(c.nodeDelete()).toBe(TREE[0]);
  });

  it('opens the toolbar dialogs from the header menu on a phone', async () => {
    const { c } = await setup();
    expect(c.headerMenu()[0].items.every((i: { disabledReason: string | null }) => i.disabledReason === null)).toBe(true);
    c.onHeaderMenu({ id: 'states', label: '' });
    expect(c.stateConfigOpen()).toBe(true);
    c.onHeaderMenu({ id: 'cutoff', label: '' });
    expect(c.stichtagOpen()).toBe(true);
    c.onHeaderMenu({ id: 'fy', label: '' });
    expect(c.fyOpen()).toBe(true);
    c.selectedTopId.set('');
    expect(c.headerMenu()[0].items[0].disabledReason).toBeTruthy();
  });

  it('names the picked budget, its cutoff and the fiscal years in the pickers', async () => {
    const { c } = await setup();
    expect(c.topOptions()).toEqual([{ value: 'b-vs', label: 'VS-Mittel (VS)' }]);
    expect(c.topChipText()).toBe('VS-Mittel VS · Stichtag 01.01.');
    expect(c.cutoffLabel()).toBe('01.01.');
    c.fiscalYears.set([FY, { ...FY, id: 'fy-0', year: 2025, display: '2025', active: false }]);
    expect(c.fyOptions()).toEqual([
      { value: 'fy-1', label: 'HHJ 2026' },
      { value: 'fy-0', label: 'HHJ 2025 · inaktiv' },
    ]);
    expect(c.selectedFyLabel()).toBe('2026');
    c.selectedFyId.set('gone');
    expect(c.selectedFyLabel()).toBe('');
    c.selectedFyId.set('fy-1');
    c.selectFy('fy-0');
    expect(c.selectedFyId()).toBe('fy-0');
    c.selectFy(null);
    expect(c.selectedFyId()).toBe('fy-0');
    c.selectedTopId.set('');
    expect(c.topChipText()).toBeNull();
    expect(c.cutoffLabel()).toBe('');
  });

  it('maps gremien into options on construction', async () => {
    const { c } = await setup({ gremien: 'ok', flow: 'null' });
    expect(c.gremiumOptions()).toEqual([{ value: 'g-1', label: 'StuPa' }]);
  });

  it('clears gremium options when the gremien request fails', async () => {
    const { c } = await setup({ gremien: 'error', flow: 'null' });
    expect(c.gremiumOptions()).toEqual([]);
  });

  it('builds state options from the global flow (de label, key fallback)', async () => {
    const { c } = await setup({ gremien: 'ok', flow: 'states' });
    expect(c.stateOptions()).toEqual([
      { value: 'accepted', label: 'Angenommen (accepted)' },
      { value: 'orphan', label: 'orphan (orphan)' },
    ]);
  });

  it('falls back to an empty state list when the flow request fails', async () => {
    const { c } = await setup({ gremien: 'ok', flow: 'error' });
    expect(c.stateOptions()).toEqual([]);
  });

  it('keeps the selection across reloads when the top still exists', async () => {
    const { c, http } = await setup();
    c.selectedTopId.set('b-vs');
    c['reload']();
    flushReload(http);
    expect(c.selectedTopId()).toBe('b-vs');
    expect(c.fiscalYears()).toEqual([FY]);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('resets fiscal years to empty when no tops exist after reload', async () => {
    const { c, http } = await setup();
    c['reload']();
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush([]);
    expect(c.selectedTopId()).toBe('');
    expect(c.fiscalYears()).toEqual([]);
    expect(c.loading()).toBe(false);
  });

  it('picks the newest active fiscal year, else the newest one', async () => {
    const { c, http } = await setup();
    expect(c.selectedFyId()).toBe('fy-1');
    const old = { ...FY, id: 'fy-old', year: 2024, display: '2024', active: true };
    const closed = { ...FY, id: 'fy-new', year: 2027, display: '2027', active: false };
    c.selectTop('b-vs');
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([old, closed]);
    expect(c.selectedFyId()).toBe('fy-old');
    c.selectTop('b-vs');
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([closed]);
    expect(c.selectedFyId()).toBe('fy-new');
    // An empty pick does nothing.
    c.selectTop('');
    http.verify();
  });

  it('clears an invalid selected fy on reload (defaults to first)', async () => {
    const { c, http } = await setup();
    c.selectedFyId.set('does-not-exist');
    c['reload']();
    flushReload(http);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('resets the selected fy to "" when the selected top has no fiscal years on reload', async () => {
    const { c, http } = await setup();
    c.selectedFyId.set('fy-1');
    c['reload']();
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(TREE);
    // The selected top gets an empty fiscal-years list, so fys[0]?.id ?? '' gives ''.
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
    expect(c.fiscalYears()).toEqual([]);
    expect(c.selectedFyId()).toBe('');
  });

  it('tolerates a per-top fiscal-years error (no throw, list left untouched)', async () => {
    const { c, http } = await setup();
    c['reload']();
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(TREE);
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years'))
      .flush(null, { status: 500, statusText: 'err' });
    expect(c.loading()).toBe(false);
  });

  it('surfaces a load error when the tree request fails', async () => {
    const { c, http } = await setup();
    c['reload']();
    http
      .expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET')
      .flush(null, { status: 500, statusText: 'err' });
    expect(c.loadError()).toBe(true);
    expect(c.loading()).toBe(false);
  });

  it('alloc returns the matching fiscal-year allocation or null', async () => {
    const { c } = await setup();
    expect(c.alloc(TREE[0])?.allocated).toBe('1000');
    c.selectedFyId.set('other');
    expect(c.alloc(TREE[0])).toBeNull();
  });

  it('money formats numbers, empty strings and null as currency, with cents only when needed', async () => {
    const { c } = await setup();
    const eur = (n: number, digits: number) =>
      new Intl.NumberFormat(TestBed.inject(I18nService).formatLocale(), {
        style: 'currency',
        currency: 'EUR',
        minimumFractionDigits: digits,
        maximumFractionDigits: 2,
      }).format(n);
    expect(c.money('1234.5', 'EUR')).toBe(eur(1234.5, 2));
    expect(c.money('', 'EUR')).toBe(eur(0, 0));
    expect(c.money(null, 'EUR')).toBe(eur(0, 0));
    expect(c.money(undefined, 'EUR')).toBe(eur(0, 0));
    expect(c.money(42, 'EUR')).toBe(eur(42, 0));
  });

  it('reports accepted/denied membership for the selected top', async () => {
    const { c } = await setup();
    expect(c.isAccepted('accepted')).toBe(true);
    expect(c.isAccepted('denied')).toBe(false);
    expect(c.isDenied('denied')).toBe(true);
    expect(c.isDenied('accepted')).toBe(false);
  });

  it('accepted/denied sets are empty when no top is selected', async () => {
    const { c } = await setup();
    c.selectedTopId.set('none');
    expect([...c.acceptedKeys()]).toEqual([]);
    expect([...c.deniedKeys()]).toEqual([]);
  });

  it('selectTop sets the budget, clears the fy and loads fiscal years', async () => {
    const { c, http } = await setup();
    c.selectTop('b-vs');
    expect(c.selectedTopId()).toBe('b-vs');
    expect(c.selectedFyId()).toBe('');
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
    expect(c.fiscalYears()).toEqual([FY]);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('loadFiscalYears keeps an already-valid selected fy', async () => {
    const { c, http } = await setup();
    c.selectedFyId.set('fy-1');
    c.selectTop('b-vs');
    // selectTop wiped the fy. loadFiscalYears keeps it only if the list still holds it.
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
    expect(c.selectedFyId()).toBe('fy-1');
  });

  it('loadFiscalYears resets the selected fy to "" for an empty list (next path)', async () => {
    const { c, http } = await setup();
    c.selectedFyId.set('fy-1');
    c.selectTop('b-vs');
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
    expect(c.fiscalYears()).toEqual([]);
    expect(c.selectedFyId()).toBe('');
  });

  it('loadFiscalYears empties the list on error', async () => {
    const { c, http } = await setup();
    c.selectTop('b-vs');
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years'))
      .flush(null, { status: 500, statusText: 'err' });
    expect(c.fiscalYears()).toEqual([]);
  });

  it('picks a colour, takes a typed hex value and clears it again', async () => {
    const { c, http } = await setup();
    c.openEditNode(fullNode({ id: 'b-x', color: '  #00AA00 ' }));
    expect(c.editColor()).toBe('#00AA00');
    c.pickColor('#ABCDEF');
    expect(c.editColor()).toBe('#abcdef');
    c.editColor.set('#12');
    expect(c.editColorInvalid()).toBe(true);
    // An invalid colour blocks the save.
    c.saveEditNode();
    http.verify();
    c.clearColor();
    expect(c.editColor()).toBe('');
    expect(c.editColorInvalid()).toBe(false);
    c.openEditNode(fullNode({ id: 'b-y', color: null }));
    expect(c.editColor()).toBe('');
  });

  it('toggleState does nothing when no top is selected', async () => {
    const { c, http } = await setup();
    c.selectedTopId.set('none');
    c.toggleState('accepted', 'x');
    http.verify(); // The component sent no PATCH.
  });

  it('toggleState removes an already-set key', async () => {
    const { c, http } = await setup();
    c.toggleState('accepted', 'accepted'); // The key is set, so the toggle removes it.
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ acceptedStateKeys: [], deniedStateKeys: ['denied'] });
    patch.flush({});
    flushReload(http);
  });

  it('toggleState adds a new accepted key and removes it from denied (mutual exclusion)', async () => {
    const { c, http } = await setup();
    c.toggleState('accepted', 'denied'); // 'denied' sits in deniedKeys and moves to accepted.
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({
      acceptedStateKeys: ['accepted', 'denied'],
      deniedStateKeys: [],
    });
    patch.flush({});
    flushReload(http);
  });

  it('toggleState adds a new denied key and removes it from accepted', async () => {
    const { c, http } = await setup();
    c.toggleState('denied', 'accepted');
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({
      acceptedStateKeys: [],
      deniedStateKeys: ['denied', 'accepted'],
    });
    patch.flush({});
    flushReload(http);
  });

  it('toggleState toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.toggleState('accepted', 'new');
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  it('openTop resets the draft and opens; closeTop closes', async () => {
    const { c } = await setup();
    c.newTop.set({ key: 'X', name: 'Y', fiscalStartMonth: 3, fiscalStartDay: 4 });
    c.openTop();
    expect(c.newTop()).toEqual({ key: '', name: '', fiscalStartMonth: 1, fiscalStartDay: 1 });
    expect(c.topOpen()).toBe(true);
    c.closeTop();
    expect(c.topOpen()).toBe(false);
  });

  it('patchTop updates a single draft field', async () => {
    const { c } = await setup();
    c.patchTop('key', 'AStA');
    c.patchTop('name', 'AStA-Mittel');
    expect(c.newTop().key).toBe('AStA');
    expect(c.newTop().name).toBe('AStA-Mittel');
  });

  it('patchTopStichtag clamps month to 1..12 and day to 1..28, defaulting non-numbers to 1', async () => {
    const { c } = await setup();
    c.patchTopStichtag('fiscalStartMonth', '99');
    expect(c.newTop().fiscalStartMonth).toBe(12);
    c.patchTopStichtag('fiscalStartMonth', '0');
    expect(c.newTop().fiscalStartMonth).toBe(1);
    // The cutoff day must exist in every month: 1..28.
    c.patchTopStichtag('fiscalStartDay', '99');
    expect(c.newTop().fiscalStartDay).toBe(28);
    c.patchTopStichtag('fiscalStartDay', 'abc');
    expect(c.newTop().fiscalStartDay).toBe(1);
    c.patchTopStichtag('fiscalStartMonth', '7.9');
    expect(c.newTop().fiscalStartMonth).toBe(7);
  });

  it('createTop does nothing when key or name is blank', async () => {
    const { c, http } = await setup();
    c.newTop.set({ key: '   ', name: 'Name', fiscalStartMonth: 1, fiscalStartDay: 1 });
    c.createTop(new Event('submit'));
    c.newTop.set({ key: 'Key', name: '  ', fiscalStartMonth: 1, fiscalStartDay: 1 });
    c.createTop(new Event('submit'));
    http.verify();
  });

  it('createTop POSTs, selects the new node, closes and reloads', async () => {
    const { c, http, toast } = await setup();
    c.openTop();
    c.patchTop('key', 'AStA');
    c.patchTop('name', 'AStA-Mittel');
    c.patchTopStichtag('fiscalStartMonth', '7');
    c.createTop(new Event('submit'));
    const post = http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'POST');
    expect(post.request.body).toEqual({
      key: 'AStA',
      name: 'AStA-Mittel',
      fiscalStartMonth: 7,
      fiscalStartDay: 1,
    });
    post.flush({ id: 'b-asta' });
    expect(c.selectedTopId()).toBe('b-asta');
    expect(c.topOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    // TREE holds no b-asta, so the reload sets keep=false and falls back to b-vs.
    flushReload(http);
    expect(c.selectedTopId()).toBe('b-vs');
  });

  it('createTop toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.openTop();
    c.patchTop('key', 'AStA');
    c.patchTop('name', 'AStA-Mittel');
    c.createTop(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/budgets') && r.method === 'POST')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  it('saveStichtag does nothing without a selected top', async () => {
    const { c, http } = await setup();
    c.selectedTopId.set('none');
    c.saveStichtag('fiscalStartMonth', '5');
    http.verify();
  });

  it('saveStichtag PATCHes the clamped value, toasts, reloads + reloads fiscal years', async () => {
    const { c, http, toast } = await setup();
    c.saveStichtag('fiscalStartMonth', '13');
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ fiscalStartMonth: 12 });
    patch.flush({});
    expect(toast.success).toHaveBeenCalled();
    // The reload() runs, then loadFiscalYears(top.id). That gives 1 tree GET and 2
    // fiscal-years GETs.
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush(TREE);
    http.match((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).forEach((req) => req.flush([FY]));
  });

  it('saveStichtag defaults a non-numeric day to 1 and toasts on error', async () => {
    const { c, http, toast } = await setup();
    c.saveStichtag('fiscalStartDay', 'abc');
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ fiscalStartDay: 1 });
    patch.flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  it('opens and closes the stichtag and state-config dialogs', async () => {
    const { c } = await setup();
    c.openStichtag();
    expect(c.stichtagOpen()).toBe(true);
    c.closeStichtag();
    expect(c.stichtagOpen()).toBe(false);
    c.openStateConfig();
    expect(c.stateConfigOpen()).toBe(true);
    c.closeStateConfig();
    expect(c.stateConfigOpen()).toBe(false);
  });

  it('startAddChild opens the parent and resets the draft; cancelAddChild closes', async () => {
    const { c } = await setup();
    c.childDraft.set({ key: 'X', name: 'Y' });
    c.startAddChild(TREE[0]);
    expect(c.addingChildOf()).toBe('b-vs');
    expect(c.childDraft()).toEqual({ key: '', name: '' });
    c.cancelAddChild();
    expect(c.addingChildOf()).toBeNull();
  });

  it('patchChild updates a single child-draft field', async () => {
    const { c } = await setup();
    c.patchChild('key', '40');
    c.patchChild('name', 'Sport');
    expect(c.childDraft()).toEqual({ key: '40', name: 'Sport' });
  });

  it('addChild does nothing when key or name is blank', async () => {
    const { c, http } = await setup();
    c.childDraft.set({ key: '  ', name: 'Name' });
    c.addChild(TREE[0]);
    c.childDraft.set({ key: 'Key', name: '  ' });
    c.addChild(TREE[0]);
    http.verify();
  });

  it('addChild POSTs under the parent (inheriting currency), toasts, closes and reloads', async () => {
    const { c, http, toast } = await setup();
    c.startAddChild(TREE[0]);
    c.patchChild('key', '40');
    c.patchChild('name', 'Sport');
    c.addChild(TREE[0]);
    const post = http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'POST');
    expect(post.request.body).toEqual({
      parentId: 'b-vs',
      key: '40',
      name: 'Sport',
      currency: 'EUR',
    });
    post.flush({ id: 'b-40' });
    expect(c.addingChildOf()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
    flushReload(http);
  });

  it('addChild toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.startAddChild(TREE[0]);
    c.patchChild('key', '40');
    c.patchChild('name', 'Sport');
    c.addChild(TREE[0]);
    http
      .expectOne((r) => r.url.endsWith('/budgets') && r.method === 'POST')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  it('deletes a cost centre only after the confirmation, then reloads', async () => {
    const { c, http, toast, fixture } = await setup();
    c.deleteNode(); // nothing to confirm yet
    http.verify();
    await userEvent.click(screen.getByRole('button', { name: 'Löschen: Dezentrale Einrichtungen' }));
    fixture.detectChanges();
    expect(c.nodeDelete()).toBe(TREE[0].children[0]);
    expect(screen.getByText('„Dezentrale Einrichtungen“ (VS-800) löschen?')).toBeInTheDocument();
    c.deleteNode();
    http.expectOne((r) => r.url.endsWith('/budgets/b-800') && r.method === 'DELETE').flush(null);
    expect(toast.success).toHaveBeenCalled();
    expect(c.nodeDelete()).toBeNull();
    flushReload(http);
  });

  it('a deleted top budget clears the selection', async () => {
    const { c, http } = await setup();
    c.askDeleteNode(TREE[0]);
    c.deleteNode();
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'DELETE').flush(null);
    expect(c.selectedTopId()).toBe('');
    http.expectOne((r) => r.url.endsWith('/budgets') && r.method === 'GET').flush([]);
    expect(c.fiscalYears()).toEqual([]);
  });

  it('a 409 keeps the dialog open and names the reason', async () => {
    const { c, http, toast, fixture } = await setup();
    c.askDeleteNode(TREE[0]);
    c.deleteNode();
    http.expectOne((r) => r.method === 'DELETE').flush(null, { status: 409, statusText: 'conflict' });
    fixture.detectChanges();
    expect(c.nodeDeleteBlocked()).toBe(true);
    expect(c.nodeDelete()).toBe(TREE[0]);
    expect(screen.getByRole('alert')).toHaveTextContent('Unter-Kostenstellen oder Zuteilungen');
    expect(toast.error).not.toHaveBeenCalled();
    c.closeDeleteNode();
    expect(c.nodeDelete()).toBeNull();
    expect(c.nodeDeleteBlocked()).toBe(false);
  });

  it('toasts any other delete failure', async () => {
    const { c, http, toast } = await setup();
    c.askDeleteNode(TREE[0].children[0]);
    c.deleteNode();
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-800') && r.method === 'DELETE')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  it('openEditNode prefills key/name/hidden/viewGremium from the node', async () => {
    const { c } = await setup();
    const node = fullNode({
      id: 'b-x',
      key: 'K',
      name: 'Name',
      hiddenInBudget: true,
      viewGremiumId: 'g-9',
    });
    c.openEditNode(node);
    expect(c.editNode()).toBe(node);
    expect(c.editKey()).toBe('K');
    expect(c.editName()).toBe('Name');
    expect(c.editHidden()).toBe(true);
    expect(c.editViewGremium()).toBe('g-9');
    expect(c.editActive()).toBe(true);
  });

  it('shows every setting of a node in the edit dialog', async () => {
    const { c, fixture } = await setup();
    c.openEditNode(TREE[0].children[0]);
    fixture.detectChanges();
    expect(screen.getByRole('dialog')).toHaveTextContent('VS-800');
    expect(screen.getByLabelText('Schlüssel')).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Aktiv' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Im Budget-Tab ausblenden/ })).toBeInTheDocument();
    expect(screen.getByLabelText('Sichtbar für Gremium')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Farbe #5fb37a' })).toBeInTheDocument();
    expect(screen.getByLabelText('Eigene Farbe wählen')).toBeInTheDocument();
  });

  it('openEditNode defaults the view gremium to "" when null', async () => {
    const { c } = await setup();
    c.openEditNode(fullNode({ id: 'b-x', viewGremiumId: null }));
    expect(c.editViewGremium()).toBe('');
  });

  it('closeEditNode clears the edit node', async () => {
    const { c } = await setup();
    c.openEditNode(TREE[0]);
    c.closeEditNode();
    expect(c.editNode()).toBeNull();
  });

  it('saveEditNode does nothing when no node is open', async () => {
    const { c, http } = await setup();
    c.closeEditNode();
    c.saveEditNode();
    http.verify();
  });

  it('saveEditNode does nothing when key or name trims to empty', async () => {
    const { c, http } = await setup();
    c.openEditNode(TREE[0]);
    c.editKey.set('  ');
    c.editName.set('Name');
    c.saveEditNode();
    c.editKey.set('Key');
    c.editName.set('  ');
    c.saveEditNode();
    http.verify();
  });

  it('saveEditNode PATCHes key/name/hidden/viewGremium (null when blank), toasts and reloads', async () => {
    const { c, http, toast } = await setup();
    c.openEditNode(TREE[0]);
    c.editKey.set(' VS ');
    c.editName.set(' VS-Mittel ');
    c.editHidden.set(true);
    c.editViewGremium.set('');
    c.editActive.set(false);
    c.pickColor('#ff0000');
    c.saveEditNode();
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({
      key: 'VS',
      name: 'VS-Mittel',
      color: '#ff0000',
      active: false,
      hiddenInBudget: true,
      viewGremiumId: null,
    });
    patch.flush({});
    expect(c.editNode()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
    flushReload(http);
  });

  it('saveEditNode keeps a non-empty view gremium and toasts a key error on failure', async () => {
    const { c, http, toast } = await setup();
    c.openEditNode(TREE[0]);
    c.editViewGremium.set('g-1');
    c.saveEditNode();
    const patch = http.expectOne((r) => r.url.endsWith('/budgets/b-vs') && r.method === 'PATCH');
    expect(patch.request.body.viewGremiumId).toBe('g-1');
    patch.flush(null, { status: 409, statusText: 'conflict' });
    expect(toast.error).toHaveBeenCalled();
  });

  it('openLimit prefills the value from the current allocation', async () => {
    const { c } = await setup();
    c.openLimit(TREE[0]);
    expect(c.limitNode()).toBe(TREE[0]);
    expect(c.limitValue()).toBe('1000');
  });

  it('openLimit defaults the value to "" when there is no matching allocation', async () => {
    const { c } = await setup();
    c.selectedFyId.set('other-fy');
    c.openLimit(TREE[0]);
    expect(c.limitValue()).toBe('');
  });

  it('closeLimit clears the limit node', async () => {
    const { c } = await setup();
    c.openLimit(TREE[0]);
    c.closeLimit();
    expect(c.limitNode()).toBeNull();
  });

  it('saveLimit does nothing without a node or fiscal year', async () => {
    const { c, http } = await setup();
    c.saveLimit(); // No node.
    c.openLimit(TREE[0]);
    c.selectedFyId.set('');
    c.saveLimit(); // No fiscal year.
    http.verify();
  });

  it('saveLimit does nothing when the value trims to empty', async () => {
    const { c, http } = await setup();
    c.openLimit(TREE[0]);
    c.limitValue.set('   ');
    c.saveLimit();
    http.verify();
  });

  it('saveLimit PUTs the allocation, toasts, closes and reloads', async () => {
    const { c, http, toast } = await setup();
    c.openLimit(TREE[0].children[0]);
    c.limitValue.set('500');
    c.saveLimit();
    const put = http.expectOne((r) => r.url.endsWith('/budgets/b-800/allocations/fy-1'));
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ allocated: '500' });
    put.flush({});
    expect(c.limitNode()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
    flushReload(http);
  });

  it('saveLimit toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.openLimit(TREE[0].children[0]);
    c.limitValue.set('500');
    c.saveLimit();
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-800/allocations/fy-1'))
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  it('patchFyYear truncates the year and defaults non-numbers to the current year', async () => {
    const { c } = await setup();
    c.patchFyYear('2027.9');
    expect(c.newFy().year).toBe(2027);
    c.patchFyYear('abc');
    expect(c.newFy().year).toBe(new Date().getFullYear());
  });

  it('openFy resets the draft and opens; closeFy closes', async () => {
    const { c } = await setup();
    c.newFy.set({ year: 1999 });
    c.openFy();
    expect(c.newFy().year).toBe(new Date().getFullYear());
    expect(c.fyOpen()).toBe(true);
    c.closeFy();
    expect(c.fyOpen()).toBe(false);
  });

  it('createFiscalYear does nothing without a selected top', async () => {
    const { c, http } = await setup();
    c.selectedTopId.set('');
    c.createFiscalYear(new Event('submit'));
    http.verify();
  });

  it('createFiscalYear does nothing when the year is falsy', async () => {
    const { c, http } = await setup();
    c.newFy.set({ year: 0 });
    c.createFiscalYear(new Event('submit'));
    http.verify();
  });

  it('createFiscalYear POSTs, toasts, closes and reloads the fiscal years', async () => {
    const { c, http, toast } = await setup();
    c.openFy();
    c.patchFyYear('2027');
    c.createFiscalYear(new Event('submit'));
    const post = http.expectOne(
      (r) => r.url.endsWith('/budgets/b-vs/fiscal-years') && r.method === 'POST',
    );
    expect(post.request.body).toEqual({ year: 2027 });
    post.flush({ ...FY, id: 'fy-2', year: 2027 });
    expect(c.fyOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([FY]);
  });

  it('createFiscalYear toasts an error on failure', async () => {
    const { c, http, toast } = await setup();
    c.openFy();
    c.patchFyYear('2027');
    c.createFiscalYear(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years') && r.method === 'POST')
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalled();
  });

  // --- edit a fiscal year ---------------------------------------------------

  it('openFyEdit closes the manage dialog and seeds the form', async () => {
    const { c } = await setup();
    c.openFy();
    c.openFyEdit(FY);
    expect(c.fyOpen()).toBe(false);
    expect(c.fyEdit()).toEqual(FY);
    expect(c.fyEditYear()).toBe(2026);
    expect(c.fyEditActive()).toBe(true);
    // Closing the edit hands control back to the manage dialog.
    c.closeFyEdit();
    expect(c.fyEdit()).toBeNull();
    expect(c.fyOpen()).toBe(true);
  });

  it('patchFyEditYear truncates and defaults a non-number to the current year', async () => {
    const { c } = await setup();
    c.patchFyEditYear('2027.9');
    expect(c.fyEditYear()).toBe(2027);
    c.patchFyEditYear('abc');
    expect(c.fyEditYear()).toBe(new Date().getFullYear());
  });

  it('saveFyEdit PATCHes the year and the active flag, then reloads', async () => {
    const { c, http, toast } = await setup();
    c.openFyEdit(FY);
    c.patchFyEditYear('2027');
    c.fyEditActive.set(false);
    c.saveFyEdit();
    const patch = http.expectOne(
      (r) => r.url.endsWith('/budgets/b-vs/fiscal-years/fy-1') && r.method === 'PATCH',
    );
    expect(patch.request.body).toEqual({ year: 2027, active: false });
    patch.flush({ ...FY, year: 2027, active: false });
    expect(toast.success).toHaveBeenCalledWith('Haushaltsjahr gespeichert.');
    expect(c.fyEdit()).toBeNull();
    expect(c.fyOpen()).toBe(true);
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years'))
      .flush([{ ...FY, year: 2027, display: '2027' }]);
    // The fiscal-year segments follow the correction.
    expect(c.fyOptions()[0].label).toBe('HHJ 2027');
  });

  it('saveFyEdit names the duplicate year on 422', async () => {
    const { c, http, toast } = await setup();
    c.openFyEdit(FY);
    c.saveFyEdit();
    http
      .expectOne((r) => r.method === 'PATCH')
      .flush(null, { status: 422, statusText: 'unprocessable' });
    expect(toast.error).toHaveBeenCalledWith('Dieses Jahr gibt es in diesem Budget bereits.');
  });

  it('saveFyEdit falls back to the generic error on any other status', async () => {
    const { c, http, toast } = await setup();
    c.openFyEdit(FY);
    c.saveFyEdit();
    http.expectOne((r) => r.method === 'PATCH').flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalledWith(
      'Haushaltsjahr konnte nicht angelegt werden (bereits vorhanden?).',
    );
  });

  it('saveFyEdit is a no-op without a year under edit or without a top', async () => {
    const { c, http } = await setup();
    c.saveFyEdit(); // nothing under edit
    c.openFyEdit(FY);
    c.selectedTopId.set('');
    c.saveFyEdit(); // no top budget
    http.verify();
  });

  // --- delete a fiscal year -------------------------------------------------

  it('askFyDelete closes the manage dialog and clears an earlier block reason', async () => {
    const { c } = await setup();
    c.openFy();
    c.fyDeleteBlocked.set('stale');
    c.askFyDelete(FY);
    expect(c.fyOpen()).toBe(false);
    expect(c.fyDelete()).toEqual(FY);
    expect(c.fyDeleteBlocked()).toBeNull();
    c.closeFyDelete();
    expect(c.fyDelete()).toBeNull();
    expect(c.fyOpen()).toBe(true);
  });

  it('doFyDelete DELETEs, toasts and reloads the fiscal years', async () => {
    const { c, http, toast } = await setup();
    c.askFyDelete(FY);
    c.doFyDelete();
    http
      .expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years/fy-1') && r.method === 'DELETE')
      .flush(null, { status: 204, statusText: 'no content' });
    expect(toast.success).toHaveBeenCalledWith('Haushaltsjahr gelöscht.');
    expect(c.fyDelete()).toBeNull();
    http.expectOne((r) => r.url.endsWith('/budgets/b-vs/fiscal-years')).flush([]);
    expect(c.fiscalYears()).toEqual([]);
  });

  it.each([
    ['fiscal year still has bookings; remove them first', 'budget.tree.fyBlocked.bookings'],
    ['fiscal year still has allocations; remove them first', 'budget.tree.fyBlocked.allocations'],
    ['fiscal year still has applications; remove them first', 'budget.tree.fyBlocked.applications'],
    ['fiscal year is busy', 'budget.tree.fyBlocked.generic'],
  ])('409 "%s" explains the blocker in the dialog', async (detail, key) => {
    const { c, http, toast, fixture } = await setup();
    const expected = TestBed.inject(I18nService).translate(
      key as Parameters<I18nService['translate']>[0],
    );
    c.askFyDelete(FY);
    c.doFyDelete();
    http
      .expectOne((r) => r.method === 'DELETE')
      .flush({ detail }, { status: 409, statusText: 'conflict' });
    // The dialog stays open and shows the reason. A toast repeats it.
    expect(c.fyDelete()).not.toBeNull();
    expect(c.fyDeleteBlocked()).toBe(expected);
    expect(toast.error).toHaveBeenCalledWith(expected);
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent(expected);
  });

  it('a 409 without a problem body still reads as the generic blocker', async () => {
    const { c, http } = await setup();
    c.askFyDelete(FY);
    c.doFyDelete();
    http.expectOne((r) => r.method === 'DELETE').flush(null, { status: 409, statusText: 'c' });
    expect(c.fyDeleteBlocked()).toBe(
      TestBed.inject(I18nService).translate('budget.tree.fyBlocked.generic'),
    );
  });

  it('any other delete failure toasts the generic message', async () => {
    const { c, http, toast } = await setup();
    c.askFyDelete(FY);
    c.doFyDelete();
    http.expectOne((r) => r.method === 'DELETE').flush(null, { status: 500, statusText: 'err' });
    expect(toast.error).toHaveBeenCalledWith('Haushaltsjahr konnte nicht gelöscht werden.');
    expect(c.fyDeleteBlocked()).toBeNull();
  });

  it('doFyDelete is a no-op without a confirmed year or without a top', async () => {
    const { c, http } = await setup();
    c.doFyDelete(); // nothing confirmed
    c.askFyDelete(FY);
    c.selectedTopId.set('');
    c.doFyDelete(); // no top budget
    http.verify();
  });

  // --- permission gating ----------------------------------------------------

  it('hides the fiscal-year row actions without budget.structure', async () => {
    const { c } = await setup({ gremien: 'ok', flow: 'null', can: false });
    expect(c.canStructure()).toBe(false);
    expect(c.fyColumns().map((col: { key: string }) => col.key)).toEqual(['display', 'active']);
  });

  it('shows the fiscal-year row actions with budget.structure', async () => {
    const { c } = await setup();
    expect(c.canStructure()).toBe(true);
    expect(c.fyColumns().map((col: { key: string }) => col.key)).toEqual([
      'display',
      'active',
      'actions',
    ]);
    expect(c.fyRowId(FY)).toBe('fy-1');
  });

  it('offers an edit and a delete button per fiscal year in the manage dialog', async () => {
    const { c, fixture } = await setup();
    c.openFy();
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Haushaltsjahr bearbeiten: 2026' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Haushaltsjahr löschen: 2026' })).toBeInTheDocument();
  });

  it('nests no second main landmark inside the shell main', async () => {
    // `<main>` in a routed page template lands inside the `<main id="main">` of the
    // shell. HTML forbids that, and it gives a screen reader two "main" landmarks.
    const view = await setup();
    expect(view.container.querySelectorAll('main')).toHaveLength(0);
    const region = view.container.querySelector('.bt');
    expect(region).toBeTruthy();
    expect(region!.getAttribute('role')).toBeNull();
  });

  describe('on a phone', () => {
    let restore: () => void;
    beforeEach(() => (restore = matchMediaQueries(MEDIA.phone)));
    afterEach(() => restore());

    it('keeps one primary action in the header and puts the row actions in a menu', async () => {
      const { fixture } = await setup();
      expect(screen.queryByRole('toolbar')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^Budget$/ })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Weitere Aktionen' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Aktionen: VS-Mittel' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Kostenstelle bearbeiten: VS-Mittel' })).not.toBeInTheDocument();
      // The cards have room for all five amounts, whatever the width.
      const c = fixture.componentInstance as unknown as { width: { set(v: number): void }; columns(): { key: string }[] };
      c.width.set(300);
      expect(c.columns().map((col) => col.key)).toContain('income');
    });
  });

  it('measures its width with a ResizeObserver and stops on destroy', async () => {
    // The data tables observe their own boxes too, so the stub keeps each callback by element.
    const watchers = new Map<Element, ResizeObserverCallback>();
    const disconnect = jest.fn();
    const original = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      constructor(private readonly cb: ResizeObserverCallback) {}
      observe(el: Element): void {
        watchers.set(el, this.cb);
      }
      unobserve(): void {}
      disconnect = disconnect;
    };
    try {
      const { c, fixture } = await setup();
      const host = fixture.nativeElement as Element;
      expect(watchers.has(host)).toBe(true);
      watchers.get(host)!([{ contentRect: { width: 720 } } as ResizeObserverEntry], {} as ResizeObserver);
      expect(c.width()).toBe(720);
      expect(c.hidden().has('expended')).toBe(true);
      fixture.destroy();
      expect(disconnect).toHaveBeenCalled();
    } finally {
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = original;
    }
  });
});
