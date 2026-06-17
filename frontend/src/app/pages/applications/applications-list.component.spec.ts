import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApplicationsListComponent } from './applications-list.component';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import type { BudgetTreeNode } from '../budget/budget-tree.api';
import type {
  ApplicationListItemWire,
  ApplicationTypeListItemWire,
  Page,
  StateOutWire,
} from '@core/api/models';

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

const OPEN_STATE: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};

const TYPES: Page<ApplicationTypeListItemWire> = {
  items: [{ id: 't1', name: 'Finanzantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' }],
  total: 1,
  limit: 20,
  offset: 0,
};

function listPage(items: ApplicationListItemWire[], total = items.length): Page<ApplicationListItemWire> {
  return { items, total, limit: 20, offset: 0 };
}

const ITEM: ApplicationListItemWire = {
  id: 'app-1',
  typeId: 't1',
  title: 'Mein Antrag',
  state: OPEN_STATE,
  gremiumId: null,
  budgetPotId: null,
  amount: '250.00',
  currency: 'EUR',
  createdAt: '2026-05-30T09:00:00Z',
  updatedAt: '2026-05-30T09:00:00Z',
};

const ITEM2: ApplicationListItemWire = { ...ITEM, id: 'app-2', title: 'Zweiter Antrag' };

async function setup(opts: { perms?: string[]; flushBudgets?: boolean } = {}) {
  const view = await render(ApplicationsListComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(opts.perms ?? []) },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const router = view.fixture.debugElement.injector.get(Router);
  const cmp = view.fixture.componentInstance;
  // Der Kostenstellen-Baum (linker Filter) wird im Konstruktor eager geladen.
  if (opts.flushBudgets !== false) flushBudgets(http);
  return { ...view, http, router, cmp };
}

function flushTypes(http: HttpTestingController) {
  http.expectOne('/api/application-types').flush(TYPES);
}

/** Kostenstellen-Baum (linker Filter-Picker) — eager im Konstruktor geladen. */
function flushBudgets(http: HttpTestingController) {
  for (const req of http.match((r) => r.url === '/api/budgets')) req.flush([]);
}

describe('ApplicationsListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders a row per application with type name, state badge and amount', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    expect(screen.getByRole('heading', { name: 'Anträge', level: 1 })).toBeInTheDocument();
    // state appears both as the row badge and as a real status filter option (#review2 §2)
    const badge = screen.getAllByText('Eingereicht').find((el) => el.tagName !== 'OPTION');
    expect(badge).toBeTruthy();
    expect(screen.getByText(/250/)).toBeInTheDocument();
    // type name shows as a plain cell (and in the filter <option>)
    expect(screen.getAllByText('Finanzantrag').length).toBeGreaterThan(0);
    // the row link now carries the application title and points at the detail route
    const link = screen.getByRole('link', { name: /Mein Antrag/ });
    expect(link).toHaveAttribute('href', '/applications/app-1');
    http.verify();
  });

  it('offers the real loaded states as status filter options with the state UUID as value (#review2 §2)', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Filter' }));
    flushBudgets(http);

    // The status filter is a dropdown (not free text); option label = state name,
    // option value = the backend state UUID (sent filter value unchanged).
    const option = screen.getByRole('option', { name: 'Eingereicht' }) as HTMLOptionElement;
    expect(option.value).toBe('s1');
    http.verify();
  });

  it('shows the empty state when no applications match', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([], 0));
    detectChanges();
    expect(screen.getByText('Keine Anträge gefunden.')).toBeInTheDocument();
    http.verify();
  });

  it('renders an error message when the list request fails', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http
      .expectOne((r) => r.url === '/api/applications')
      .flush(null, { status: 500, statusText: 'Server Error' });
    detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Anträge konnten nicht geladen werden.');
    http.verify();
  });

  it('sends the current filter values as query params on submit', async () => {
    const { http, detectChanges, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Filter' }));
    flushBudgets(http);
    await userEvent.type(screen.getByLabelText('Suche'), 'Beamer');
    await userEvent.click(screen.getByRole('button', { name: 'Filtern' }));

    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: expect.objectContaining({ q: 'Beamer', offset: null }),
        queryParamsHandling: 'merge',
      }),
    );
    http.verify();
  });

  it('requests the first page and shows the count + "load more" when more exist', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    // 50 total, only 1 loaded so far → infinite-scroll fallback button visible.
    const req = http.expectOne((r) => r.url === '/api/applications');
    expect(req.request.params.get('limit')).toBe('20');
    expect(req.request.params.get('offset')).toBe('0');
    req.flush(listPage([ITEM], 50));
    detectChanges();

    expect(screen.getByText('1 von 50')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mehr laden' })).toBeEnabled();
    http.verify();
  });

  it('appends the next page on "load more" (infinite scroll)', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM], 50));
    detectChanges();

    await userEvent.click(screen.getByRole('button', { name: 'Mehr laden' }));
    // Nächster Offset = bisher geladene Trefferzahl (hier 1), Filter bleiben erhalten.
    const more = http.expectOne((r) => r.url === '/api/applications');
    expect(more.request.params.get('offset')).toBe('1');
    more.flush(listPage([ITEM2], 50));
    detectChanges();

    expect(screen.getByRole('link', { name: /Mein Antrag/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Zweiter Antrag/ })).toBeInTheDocument();
    expect(screen.getByText('2 von 50')).toBeInTheDocument();
    http.verify();
  });

  it('clears every filter param on reset', async () => {
    const { http, detectChanges, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Filter' }));
    flushBudgets(http);
    await userEvent.click(screen.getByRole('button', { name: 'Zurücksetzen' }));
    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: {
          q: null, type: null, state: null, gremium: null, topf: null, budget: null,
          amountMin: null, amountMax: null, createdFrom: null, createdTo: null, offset: null,
        },
      }),
    );
    http.verify();
  });

  it('sorts by amount when the Amount header is clicked', async () => {
    const { http, detectChanges, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: /Betrag/ }));
    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: expect.objectContaining({ sort: 'amount', order: 'desc', offset: null }),
      }),
    );
    http.verify();
  });

  it('sends amount range and date filters on submit', async () => {
    const { http, detectChanges, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Filter' }));
    flushBudgets(http);
    await userEvent.type(screen.getByLabelText('Min'), '100');
    await userEvent.type(screen.getByLabelText('Max'), '500');
    await userEvent.click(screen.getByRole('button', { name: 'Filtern' }));
    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: expect.objectContaining({ amountMin: 100, amountMax: 500, offset: null }),
      }),
    );
    http.verify();
  });

  it('renders a dash for a missing amount', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http
      .expectOne((r) => r.url === '/api/applications')
      .flush(listPage([{ ...ITEM, amount: null }]));
    detectChanges();
    // amount cell falls back to the "not provided" dash
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    http.verify();
  });

  it('maps every nullable list field to its fallback in the table rows', async () => {
    const { http, cmp } = await setup();
    flushTypes(http);
    // an item missing title/state/amount/currency/createdAt entirely
    http.expectOne((r) => r.url === '/api/applications').flush(
      listPage([
        {
          ...ITEM,
          title: undefined as never,
          state: undefined as never,
          amount: undefined as never,
          currency: undefined as never,
          createdAt: undefined as never,
        },
      ]),
    );
    const [row] = cmp.tableRows();
    // titleOf falls back to the i18n "Ohne Titel"
    expect(row.title).toBe('Ohne Titel');
    expect(row.stateLabel).toBeNull();
    expect(row.stateColor).toBeNull();
    expect(row.amount).toBeNull();
    expect(row.currency).toBeNull();
    expect(row.createdAt).toBeNull();
    http.verify();
  });

  it('treats a whitespace-only / null filter value as inactive in the indicator count', async () => {
    const { http, cmp } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    // one real value, one whitespace-only and one null → only the real value counts
    cmp.q.set('beamer');
    cmp.typeId.set('   ');
    cmp.state.set(null as never);
    expect(cmp.activeFilterCount()).toBe(1);
    http.verify();
  });

  it('accumulates filter status options across pages (collectStates), tolerating stateless items', async () => {
    const { http, cmp } = await setup();
    flushTypes(http);
    const stateB: StateOutWire = { ...OPEN_STATE, id: 's2', label: { de: 'Genehmigt', en: 'Approved' } };
    // first page: one with state s1, one without any state at all (state branch skipped)
    http.expectOne((r) => r.url === '/api/applications').flush(
      listPage([ITEM, { ...ITEM2, state: undefined as never }], 50),
    );
    expect(cmp.stateOptions().map((o) => o.value)).toEqual(['s1']);

    cmp.loadMore();
    const more = http.expectOne((r) => r.url === '/api/applications');
    // re-seeing s1 must NOT duplicate; the new s2 is appended (changed=true branch)
    more.flush(listPage([{ ...ITEM, id: 'app-3', state: stateB }], 50));
    expect(cmp.stateOptions().map((o) => o.value)).toEqual(['s1', 's2']);
    http.verify();
  });

  describe('export', () => {
    function stubBlobDownload() {
      (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
      (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
      const createObj = jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
      const revoke = jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
      const click = jest
        .spyOn(HTMLAnchorElement.prototype, 'click')
        .mockImplementation(() => undefined);
      return () => {
        createObj.mockRestore();
        revoke.mockRestore();
        click.mockRestore();
      };
    }

    it('hides the export button without the application.export permission', async () => {
      const { http, detectChanges, cmp } = await setup({ perms: [] });
      flushTypes(http);
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
      detectChanges();
      expect(cmp.canExport()).toBe(false);
      expect(screen.queryByRole('button', { name: /Export/i })).not.toBeInTheDocument();
      http.verify();
    });

    it('shows the export button and downloads the xlsx with the URL filters, clearing the flag', async () => {
      const restore = stubBlobDownload();
      const { http, detectChanges, cmp, router } = await setup({ perms: ['application.export'] });
      flushTypes(http);
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
      detectChanges();
      expect(cmp.canExport()).toBe(true);

      // The export reads the live query params snapshot — populate them first.
      await router.navigate([], {
        queryParams: {
          q: 'beamer',
          type: 't1',
          state: 's1',
          gremium: 'g1',
          topf: 'topf1',
          budget: 'b1',
          createdFrom: '2026-01-01',
          createdTo: '2026-12-31',
          amountMin: '100',
          amountMax: '500',
          sort: 'amount',
          order: 'asc',
        },
      });
      // The queryParam change reloads the list — flush that reload request.
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));

      cmp.onExport();
      expect(cmp.exporting()).toBe(true);
      const req = http.expectOne((r) => r.url === '/api/applications/export.xlsx');
      const p = req.request.params;
      expect(p.get('q')).toBe('beamer');
      expect(p.get('type')).toBe('t1');
      expect(p.get('state')).toBe('s1');
      expect(p.get('gremium')).toBe('g1');
      expect(p.get('topf')).toBe('topf1');
      expect(p.get('budget')).toBe('b1');
      expect(p.get('createdFrom')).toBe('2026-01-01');
      expect(p.get('createdTo')).toBe('2026-12-31');
      expect(p.get('amountMin')).toBe('100');
      expect(p.get('amountMax')).toBe('500');
      expect(p.get('sort')).toBe('amount');
      expect(p.get('order')).toBe('asc');
      req.flush(new Blob(['x']));
      expect(cmp.exporting()).toBe(false);
      restore();
      http.verify();
    });

    it('ignores invalid sort/order in the export query', async () => {
      const restore = stubBlobDownload();
      const { http, detectChanges, cmp, router } = await setup({ perms: ['application.export'] });
      flushTypes(http);
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
      detectChanges();

      await router.navigate([], { queryParams: { sort: 'bogus', order: 'sideways' } });
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));

      cmp.onExport();
      const req = http.expectOne((r) => r.url === '/api/applications/export.xlsx');
      // neither the invalid sort nor order made it into the query
      expect(req.request.params.get('sort')).toBeNull();
      expect(req.request.params.get('order')).toBeNull();
      req.flush(new Blob(['x']));
      restore();
      http.verify();
    });

    it('is a no-op while an export is already running', async () => {
      const { http, detectChanges, cmp } = await setup({ perms: ['application.export'] });
      flushTypes(http);
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
      detectChanges();
      cmp.exporting.set(true);
      cmp.onExport();
      http.expectNone((r) => r.url === '/api/applications/export.xlsx');
      http.verify();
    });

    it('clears the exporting flag when the export request fails', async () => {
      const { http, detectChanges, cmp } = await setup({ perms: ['application.export'] });
      flushTypes(http);
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
      detectChanges();
      cmp.onExport();
      expect(cmp.exporting()).toBe(true);
      http
        .expectOne((r) => r.url === '/api/applications/export.xlsx')
        .flush(null, { status: 500, statusText: 'fail' });
      expect(cmp.exporting()).toBe(false);
      http.verify();
    });
  });

  it('falls back to empty lists when the types and budget-tree requests fail', async () => {
    const { http, cmp } = await setup({ flushBudgets: false });
    // application-types error → types stays []
    http.expectOne('/api/application-types').flush(null, { status: 500, statusText: 'x' });
    // budget tree error → budgetTree stays []
    for (const req of http.match((r) => r.url === '/api/budgets')) {
      req.flush(null, { status: 500, statusText: 'x' });
    }
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    expect(cmp.types()).toEqual([]);
    expect(cmp.budgetTree()).toEqual([]);
    // typeName falls back to the raw id when the type is unknown
    expect(cmp.typeName('t1' as never)).toBe('t1');
    http.verify();
  });

  it('prunes cost centres hidden in the budget tab (and their subtree)', async () => {
    const { http, cmp } = await setup({ flushBudgets: false });
    flushTypes(http);
    const child = (id: string, hidden = false): BudgetTreeNode =>
      ({ id, name: id, key: id, pathKey: id, children: [], hiddenInBudget: hidden } as unknown as BudgetTreeNode);
    const tree: BudgetTreeNode[] = [
      { ...child('visible'), children: [child('visibleChild'), child('hiddenChild', true)] } as BudgetTreeNode,
      child('hiddenTop', true),
    ];
    for (const req of http.match((r) => r.url === '/api/budgets')) req.flush(tree);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));

    const pruned = cmp.budgetTree();
    // hidden top-level node removed; visible kept with hidden child removed
    expect(pruned.map((n) => n.id)).toEqual(['visible']);
    expect(pruned[0].children.map((n) => n.id)).toEqual(['visibleChild']);
    http.verify();
  });

  it('debounces the header search before writing the q query param', async () => {
    jest.useFakeTimers();
    try {
      const { http, cmp, router } = await setup();
      flushTypes(http);
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
      const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);

      cmp.onSearch('bea');
      // a second keystroke before the timer fires must reset the debounce
      cmp.onSearch('beamer');
      expect(navigate).not.toHaveBeenCalled();
      jest.advanceTimersByTime(400);
      expect(navigate).toHaveBeenCalledTimes(1);
      expect(navigate).toHaveBeenCalledWith(
        [],
        expect.objectContaining({ queryParams: { q: 'beamer', offset: null } }),
      );
    } finally {
      jest.useRealTimers();
    }
  });

  it('clears the q param when the debounced search is emptied', async () => {
    jest.useFakeTimers();
    try {
      const { http, cmp, router } = await setup();
      flushTypes(http);
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
      const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
      cmp.onSearch('   ');
      jest.advanceTimersByTime(400);
      // blank search → q:null (the `|| null` branch)
      expect(navigate).toHaveBeenCalledWith(
        [],
        expect.objectContaining({ queryParams: { q: null, offset: null } }),
      );
    } finally {
      jest.useRealTimers();
    }
  });

  it('navigates to the chosen cost-centre on tree selection (and clears it for "all")', async () => {
    const { http, cmp, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);

    cmp.selectBudgetNode('b-42');
    expect(cmp.budgetId()).toBe('b-42');
    expect(navigate).toHaveBeenLastCalledWith(
      [],
      expect.objectContaining({ queryParams: { budget: 'b-42', offset: null } }),
    );

    cmp.selectBudgetNode('');
    // empty id → budget:null (the `id || null` branch)
    expect(navigate).toHaveBeenLastCalledWith(
      [],
      expect.objectContaining({ queryParams: { budget: null, offset: null } }),
    );
    http.verify();
  });

  it('toggles the mobile tree open/closed', async () => {
    const { http, cmp } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    expect(cmp.treeOpen()).toBe(false);
    const toggle = screen.getByRole('button', { name: /Kostenstelle|Budget|Topf/i });
    await userEvent.click(toggle);
    expect(cmp.treeOpen()).toBe(true);
    http.verify();
  });

  it('ignores loadMore while loading, while already loading more, or when nothing is left', async () => {
    const { http, cmp, detectChanges } = await setup();
    flushTypes(http);
    // exactly all items loaded → hasMore() is false
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM], 1));
    detectChanges();
    cmp.loadMore();
    http.expectNone((r) => r.url === '/api/applications');

    // simulate the initial-load guard
    cmp.loading.set(true);
    cmp.loadMore();
    http.expectNone((r) => r.url === '/api/applications');
    cmp.loading.set(false);

    // simulate the already-loading-more guard
    cmp.loadingMore.set(true);
    cmp.loadMore();
    http.expectNone((r) => r.url === '/api/applications');
    http.verify();
  });

  it('discards an out-of-order page from a superseded filter (fetchSeq guard)', async () => {
    const { http, cmp, router } = await setup();
    flushTypes(http);
    // first (initial) fetch — keep its request pending
    const first = http.expectOne((r) => r.url === '/api/applications');

    // a real filter change triggers a reload, bumping fetchSeq and issuing a new request
    await router.navigate([], { queryParams: { q: 'beamer' } });
    const second = http.expectOne((r) => r.url === '/api/applications');

    // the stale first response arrives late — it must be ignored entirely
    first.flush(listPage([ITEM], 99));
    expect(cmp.items()).toEqual([]);
    expect(cmp.total()).toBe(0);

    // the current response wins
    second.flush(listPage([ITEM2], 1));
    expect(cmp.items().map((i) => i.id)).toEqual(['app-2']);
    expect(cmp.total()).toBe(1);
    http.verify();
  });

  it('ignores a late ERROR from a superseded fetch (error fetchSeq guard)', async () => {
    const { http, cmp, detectChanges, router } = await setup();
    flushTypes(http);
    const first = http.expectOne((r) => r.url === '/api/applications');
    await router.navigate([], { queryParams: { q: 'beamer' } });
    const second = http.expectOne((r) => r.url === '/api/applications');

    // stale error must not flip the error flag
    first.flush(null, { status: 500, statusText: 'late' });
    expect(cmp.error()).toBe(false);

    second.flush(listPage([ITEM], 1));
    detectChanges();
    expect(cmp.error()).toBe(false);
    http.verify();
  });

  it('builds the list query from every active filter field', async () => {
    const { http, cmp, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));

    await router.navigate([], {
      queryParams: {
        q: ' beamer ',
        type: 't1',
        state: 's1',
        gremium: 'g1',
        topf: 'topf1',
        budget: 'b1',
        amountMin: '100',
        amountMax: '500',
        createdFrom: '2026-01-01',
        createdTo: '2026-12-31',
        sort: 'amount',
        order: 'asc',
      },
    });
    const req = http.expectOne((r) => r.url === '/api/applications');
    const p = req.request.params;
    expect(p.get('q')).toBe('beamer');
    expect(p.get('type')).toBe('t1');
    expect(p.get('state')).toBe('s1');
    expect(p.get('gremium')).toBe('g1');
    expect(p.get('topf')).toBe('topf1');
    expect(p.get('budget')).toBe('b1');
    expect(p.get('amountMin')).toBe('100');
    expect(p.get('amountMax')).toBe('500');
    expect(p.get('createdFrom')).toBe('2026-01-01');
    expect(p.get('createdTo')).toBe('2026-12-31');
    expect(p.get('sort')).toBe('amount');
    expect(p.get('order')).toBe('asc');
    req.flush(listPage([ITEM]));
    // activeFilterCount counts q/type/state/amountMin/amountMax/createdFrom/createdTo
    // (budget/gremium/topf are NOT part of the indicator) → 7 active here
    expect(cmp.activeFilterCount()).toBe(7);
    http.verify();
  });

  it('wires an IntersectionObserver to the sentinel that triggers loadMore', async () => {
    const observed: Element[] = [];
    let trigger: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
    const disconnect = jest.fn();
    class FakeObserver {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        trigger = cb;
      }
      observe(el: Element) {
        observed.push(el);
      }
      disconnect = disconnect;
    }
    const original = (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;
    (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver =
      FakeObserver as unknown as typeof IntersectionObserver;
    try {
      const { http, cmp, detectChanges } = await setup();
      flushTypes(http);
      // more pages remain → the sentinel (and observer) appear
      http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM], 50));
      detectChanges();
      expect(observed.length).toBe(1);

      const loadMore = jest.spyOn(cmp, 'loadMore');
      // a non-intersecting entry is ignored; an intersecting one loads more
      trigger?.([{ isIntersecting: false }]);
      expect(loadMore).not.toHaveBeenCalled();
      trigger?.([{ isIntersecting: true }]);
      expect(loadMore).toHaveBeenCalled();
      const more = http.expectOne((r) => r.url === '/api/applications');
      more.flush(listPage([ITEM2], 50));
      detectChanges();
      http.verify();
    } finally {
      (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = original;
    }
  });
});
