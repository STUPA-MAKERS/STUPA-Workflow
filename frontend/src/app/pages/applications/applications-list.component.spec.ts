import { Component } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
  type TestRequest,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import type {
  ApplicationListItemWire,
  ApplicationTypeListItemWire,
  Page,
  StateOutWire,
  TransitionOutWire,
} from '@core/api/models';
import type { BudgetTreeNode } from '../budget/budget-tree.api';
import { RailStatusService } from '../../layout/rail-status.service';
import { ApplicationsListComponent, actionErrorKey } from './applications-list.component';
import { ApplicationsPageService } from './applications-page.service';

/** The detail of the outlet. The detail has its own spec; here only the route matters. */
@Component({ standalone: true, template: '<p>detail</p>' })
class DetailStub {}

@Component({ standalone: true, template: '' })
class NoneStub {}

@Component({ standalone: true, template: '' })
class ApplyStub {}

const SUBMITTED: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};
const REVIEW: StateOutWire = {
  id: 's2',
  key: 'review',
  label: { de: 'In Prüfung', en: 'In review' },
  color: '#e8a33d',
  editAllowed: false,
};

const TYPES: Page<ApplicationTypeListItemWire> = {
  items: [{ id: 't1', name: 'Förderantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' }],
  total: 1,
  limit: 20,
  offset: 0,
};

function row(over: Partial<ApplicationListItemWire> = {}): ApplicationListItemWire {
  return {
    id: 'app-1',
    typeId: 't1',
    title: 'Zuschuss Kennenlernwochenende',
    state: SUBMITTED,
    gremiumId: null,
    amount: '1250.00',
    currency: 'EUR',
    createdAt: '2026-09-26T12:00:00',
    updatedAt: '2026-09-26T12:00:00',
    archivedAt: null,
    ...over,
  };
}

const ROWS: ApplicationListItemWire[] = [
  row(),
  row({ id: 'app-2', title: 'Flyer für die Hochschulgruppen-Messe', state: REVIEW, amount: '480.00', createdAt: '2026-09-02T12:00:00' }),
  row({ id: 'app-3', title: 'Trikots', amount: null, createdAt: '2026-08-15T12:00:00', archivedAt: '2026-09-01T10:00:00Z' }),
];

function page(items: ApplicationListItemWire[], total = items.length, offset = 0): Page<ApplicationListItemWire> {
  return { items, total, limit: 20, offset };
}

const TREE: BudgetTreeNode[] = [
  {
    id: 'b1',
    parentId: null,
    name: 'Haushalt',
    hiddenInBudget: false,
    children: [
      { id: 'b2', parentId: 'b1', name: 'Kultur', hiddenInBudget: false, children: [] },
      { id: 'b3', parentId: 'b1', name: 'Versteckt', hiddenInBudget: true, children: [] },
    ],
  } as unknown as BudgetTreeNode,
];

const ALL = [
  'application.read',
  'application.transition',
  'application.export',
  'application.share',
  'application.archive',
  'application.force_status',
  'application.delete',
];

const LIST = (r: { url: string; method: string }) => r.method === 'GET' && r.url === '/api/applications';

interface Opts {
  perms?: string[];
  rows?: ApplicationListItemWire[];
  total?: number;
  tree?: BudgetTreeNode[] | 'error';
  types?: 'error';
  /** Leave the first list request open. */
  holdList?: boolean;
}

async function start(url = '/applications', opts: Opts = {}) {
  const perms = new Set(opts.perms ?? ALL);
  const rail = { refresh: jest.fn() };
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        {
          path: 'applications',
          component: ApplicationsListComponent,
          children: [
            { path: '', component: NoneStub },
            { path: ':id', component: DetailStub },
          ],
        },
        { path: 'apply', component: ApplyStub },
      ]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: RailStatusService, useValue: rail },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const harness = await RouterTestingHarness.create();
  const cmp = await harness.navigateByUrl(url, ApplicationsListComponent);
  // The row menu renders its items after a timer; it needs change detection on its own.
  harness.fixture.autoDetectChanges(true);
  if (opts.types === 'error') {
    http.expectOne((r) => r.url === '/api/application-types').flush({}, { status: 500, statusText: 'x' });
  } else {
    http.expectOne((r) => r.url === '/api/application-types').flush(TYPES);
  }
  const tree = opts.tree ?? TREE;
  const treeReq = http.expectOne((r) => r.url === '/api/budgets');
  if (tree === 'error') treeReq.flush({}, { status: 403, statusText: 'x' });
  else treeReq.flush(tree);
  let first: TestRequest | null = null;
  if (opts.holdList) first = http.expectOne(LIST);
  else http.expectOne(LIST).flush(page(opts.rows ?? ROWS, opts.total));
  harness.detectChanges();
  const router = TestBed.inject(Router);
  const toast = TestBed.inject(ToastService);
  const pageService = harness.routeDebugElement!.injector.get(ApplicationsPageService);
  /** Navigate and answer the reload of the list. */
  const go = async (path: string, items = opts.rows ?? ROWS) => {
    await router.navigateByUrl(path);
    const req = http.expectOne(LIST);
    req.flush(page(items));
    harness.detectChanges();
    return req;
  };
  const settle = async () => {
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  return { harness, cmp, http, router, toast, rail, pageService, go, settle, first };
}

/** Open the row menu of a row and answer its transitions. */
async function openRowMenu(
  http: HttpTestingController,
  title: string,
  transitions: TransitionOutWire[] = [],
  detect: () => void = () => {},
) {
  const trigger = screen.getByRole('button', { name: `Aktionen für ${title}` });
  await userEvent.click(trigger);
  const req = http.expectOne((r) => r.url.endsWith('/transitions'));
  req.flush(transitions);
  await new Promise((r) => setTimeout(r));
  detect();
  return req;
}

/** Let a download run without a real file. Returns the undo. */
function stubDownload() {
  const u = URL as unknown as { createObjectURL?: unknown; revokeObjectURL?: unknown };
  u.createObjectURL = () => 'blob:mock';
  u.revokeObjectURL = () => undefined;
  const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  return () => click.mockRestore();
}

describe('ApplicationsListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  describe('rows', () => {
    it('groups the rows by the month of submission', async () => {
      await start();
      const months = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent?.trim());
      expect(months).toEqual(['September 2026', 'August 2026']);
      const sept = screen.getByRole('region', { name: 'September 2026' });
      expect(within(sept).getAllByRole('listitem')).toHaveLength(2);
    });

    it('shows title, status text, type and amount; an archived row says so', async () => {
      await start();
      expect(screen.getByRole('link', { name: 'Zuschuss Kennenlernwochenende' })).toBeInTheDocument();
      expect(screen.getAllByText('Eingereicht').length).toBeGreaterThan(0);
      const items = screen.getAllByRole('listitem');
      expect(items.filter((li) => within(li).queryByText('Förderantrag')).length).toBe(3);
      expect(screen.getByText('1.250,00 €')).toBeInTheDocument();
      expect(screen.getByText('Archiviert')).toBeInTheDocument();
      // No amount, no placeholder.
      const trikots = screen.getByRole('link', { name: 'Trikots' }).closest('app-list-item')!;
      expect(trikots.querySelector('.apps__amount')).toBeNull();
    });

    it('names an untitled row and leaves an unknown type and a missing state out', async () => {
      await start('/applications', {
        rows: [row({ title: '  ', typeId: 'unknown', state: null, amount: 'abc', currency: null })],
      });
      expect(screen.getByRole('link', { name: 'Ohne Titel' })).toBeInTheDocument();
      // An amount the browser cannot read stays as the server sent it.
      expect(screen.getByText('abc')).toBeInTheDocument();
      expect(document.querySelector('.apps__dot')).toBeNull();
    });

    it('starts an archived row without state and type with the marker, not with a dot', async () => {
      await start('/applications?archived=all', {
        rows: [row({ typeId: 'unknown', state: null, archivedAt: '2026-09-01T10:00:00Z' })],
      });
      expect(screen.getByText('Archiviert')).toBeInTheDocument();
      expect(document.querySelector('.apps__dot')).toBeNull();
    });

    it('puts a chevron in the place of the row menu in the full-width list', async () => {
      const { cmp } = await start();
      expect(cmp.split()).toBe(false);
      const chevrons = document.querySelectorAll('.apps__menuSlot .apps__chev');
      expect(chevrons).toHaveLength(ROWS.length);
      // The chevron is decoration. The row menu stays the control.
      expect(chevrons[0].getAttribute('aria-hidden')).toBe('true');
    });

    it('formats an amount without a currency as euros', async () => {
      await start('/applications', { rows: [row({ currency: null, amount: '12.50' })] });
      expect(screen.getByText('12,50 €')).toBeInTheDocument();
    });

    it('opens the filter sheets from the bottom on a phone', async () => {
      const original = window.matchMedia;
      window.matchMedia = ((q: string) => ({ ...original(q), matches: q === '(max-width: 768px)' })) as typeof window.matchMedia;
      try {
        const { cmp } = await start();
        expect(cmp.sheetSide()).toBe('bottom');
        expect(screen.getByRole('button', { name: 'Liste sortieren oder exportieren' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Exportieren' })).not.toBeInTheDocument();
      } finally {
        window.matchMedia = original;
      }
    });

    it('shows one group without a heading while the list sorts by amount', async () => {
      const { go } = await start();
      await go('/applications?sort=amount&order=desc');
      expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0);
      expect(screen.getAllByRole('listitem')).toHaveLength(3);
    });

    it('shows the empty text and no group for no rows', async () => {
      const { cmp } = await start('/applications', { rows: [] });
      expect(screen.getByText('Keine Anträge gefunden.')).toBeInTheDocument();
      expect(cmp.groups()).toEqual([]);
      cmp.sortField.set('amount');
      expect(cmp.groups()).toEqual([]);
    });

    it('shows the error when the list fails, and a placeholder while it loads', async () => {
      const { first, harness } = await start('/applications', { holdList: true });
      expect(screen.getByText('Anträge werden geladen …')).toBeInTheDocument();
      first!.flush({}, { status: 500, statusText: 'x' });
      harness.detectChanges();
      expect(screen.getByRole('alert')).toHaveTextContent('Anträge konnten nicht geladen werden.');
    });

    it('puts the number of applications into the search field', async () => {
      const { cmp } = await start('/applications', { total: 132 });
      expect(screen.getByPlaceholderText('132 Anträge durchsuchen')).toBeInTheDocument();
      cmp.total.set(1);
      expect(cmp.searchPlaceholder()).toBe('1 Antrag durchsuchen');
      cmp.total.set(0);
      cmp.loading.set(true);
      expect(cmp.searchPlaceholder()).toBe('Anträge durchsuchen');
    });
  });

  describe('paging', () => {
    it('loads the next page on "Mehr laden" and shows the count', async () => {
      const { http, harness } = await start('/applications', { rows: [ROWS[0]], total: 2 });
      expect(screen.getByText('1 von 2')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Mehr laden' }));
      const req = http.expectOne(LIST);
      expect(req.request.params.get('offset')).toBe('1');
      harness.detectChanges();
      expect(screen.getByText('Weitere Anträge werden geladen …')).toBeInTheDocument();
      req.flush(page([ROWS[1]], 2, 1));
      harness.detectChanges();
      expect(screen.getAllByRole('listitem')).toHaveLength(2);
      expect(screen.queryByRole('button', { name: 'Mehr laden' })).not.toBeInTheDocument();
    });

    it('keeps the loaded rows when a further page fails, and guards double loads', async () => {
      const { http, cmp, harness } = await start('/applications', { rows: [ROWS[0]], total: 3 });
      cmp.loadMore();
      cmp.loadMore();
      http.expectOne(LIST).flush({}, { status: 500, statusText: 'x' });
      harness.detectChanges();
      expect(cmp.error()).toBe(false);
      expect(cmp.items()).toHaveLength(1);
    });

    it('does nothing while the first page loads or when nothing is left', async () => {
      const { http, cmp, first } = await start('/applications', { holdList: true });
      cmp.loadMore();
      first!.flush(page([ROWS[0]]));
      cmp.loadMore();
      http.verify();
    });

    it('drops a late page of an earlier filter, also a late error', async () => {
      const { http, router, cmp } = await start();
      await router.navigateByUrl('/applications?q=a');
      const stale = http.expectOne(LIST);
      await router.navigateByUrl('/applications?q=ab');
      const fresh = http.expectOne(LIST);
      stale.flush(page([row({ id: 'stale', title: 'Alt' })]));
      expect(cmp.items().map((i) => i.id)).not.toContain('stale');
      fresh.flush(page([row({ id: 'new', title: 'Neu' })]));
      expect(cmp.items().map((i) => i.id)).toEqual(['new']);
      await router.navigateByUrl('/applications?q=abc');
      const stale2 = http.expectOne(LIST);
      await router.navigateByUrl('/applications?q=abcd');
      const fresh2 = http.expectOne(LIST);
      stale2.flush({}, { status: 500, statusText: 'x' });
      expect(cmp.error()).toBe(false);
      fresh2.flush(page([]));
    });

    it('loads the next page when the end of the list comes into view', async () => {
      let trigger: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
      const disconnect = jest.fn();
      class FakeObserver {
        constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
          trigger = cb;
        }
        observe(): void {}
        disconnect = disconnect;
      }
      const g = globalThis as { IntersectionObserver?: unknown };
      const original = g.IntersectionObserver;
      g.IntersectionObserver = FakeObserver;
      try {
        const { http, harness } = await start('/applications', { rows: [ROWS[0]], total: 2 });
        trigger!([{ isIntersecting: false }]);
        http.verify();
        trigger!([{ isIntersecting: true }]);
        http.expectOne(LIST).flush(page([ROWS[1]], 2, 1));
        harness.detectChanges();
        expect(disconnect).toHaveBeenCalled();
      } finally {
        g.IntersectionObserver = original;
      }
    });
  });

  describe('filters', () => {
    it('sends nothing for the defaults: no archived rows, newest first', async () => {
      const { http, router } = await start();
      await router.navigateByUrl('/applications?x=1');
      const req = http.expectOne(LIST);
      const p = req.request.params;
      expect(p.keys().sort()).toEqual(['limit', 'offset', 'order', 'sort']);
      expect(p.get('sort')).toBe('createdAt');
      expect(p.get('order')).toBe('desc');
      req.flush(page([]));
    });

    it('builds every filter from the URL, the status repeated', async () => {
      const { http, router, cmp } = await start();
      await router.navigateByUrl(
        '/applications?state=s1&state=s2&type=t1&budget=b2&q=%20fest%20&amountMin=100&amountMax=500' +
          '&createdFrom=2026-01-01&createdTo=2026-12-31&archived=all&gremium=g1&mine=true&sort=amount&order=asc',
      );
      const req = http.expectOne(LIST);
      const p = req.request.params;
      expect(p.getAll('state')).toEqual(['s1', 's2']);
      expect(p.get('type')).toBe('t1');
      expect(p.get('budget')).toBe('b2');
      expect(p.get('q')).toBe('fest');
      expect(p.get('amountMin')).toBe('100');
      expect(p.get('amountMax')).toBe('500');
      expect(p.get('createdFrom')).toBe('2026-01-01');
      expect(p.get('createdTo')).toBe('2026-12-31');
      expect(p.get('archived')).toBe('all');
      expect(p.get('gremium')).toBe('g1');
      expect(p.get('mine')).toBe('true');
      expect(p.get('sort')).toBe('amount');
      expect(p.get('order')).toBe('asc');
      req.flush(page(ROWS));
      expect(cmp.activeFilterCount()).toBe(10);
    });

    it('reads a hand-edited archive and mine value as the default', async () => {
      const { http, router, cmp } = await start();
      await router.navigateByUrl('/applications?archived=maybe&mine=yes&state=%20');
      const req = http.expectOne(LIST);
      expect(req.request.params.has('archived')).toBe(false);
      expect(req.request.params.has('mine')).toBe(false);
      expect(req.request.params.has('state')).toBe(false);
      req.flush(page([]));
      expect(cmp.archived()).toBe('false');
    });

    it('checks and unchecks states in the status menu, each as a repeated param', async () => {
      const { cmp, harness } = await start();
      const http = TestBed.inject(HttpTestingController);
      const reloadAfter = async (label: string) => {
        await userEvent.click(screen.getByRole('option', { name: label }));
        await harness.fixture.whenStable();
        const req = http.expectOne(LIST);
        const state = req.request.params.getAll('state');
        req.flush(page(ROWS));
        harness.detectChanges();
        return state;
      };
      await userEvent.click(screen.getByRole('button', { name: 'Status' }));
      harness.detectChanges();
      const list = screen.getByRole('listbox', { name: 'Status' });
      expect(list).toHaveAttribute('aria-multiselectable', 'true');
      expect(await reloadAfter('Eingereicht')).toEqual(['s1']);
      // Several choices: the menu stays open.
      expect(await reloadAfter('In Prüfung')).toEqual(['s1', 's2']);
      expect(screen.getByRole('option', { name: 'In Prüfung' })).toHaveAttribute('aria-selected', 'true');
      expect(cmp.stateChipLabel()).toBe('Eingereicht, In Prüfung');
      expect(screen.getByRole('button', { name: 'Status: Eingereicht, In Prüfung' })).toBeInTheDocument();
      expect(await reloadAfter('Eingereicht')).toEqual(['s2']);
      // Unchecking the last state drops the param.
      expect(await reloadAfter('In Prüfung')).toBeNull();
      expect(await reloadAfter('In Prüfung')).toEqual(['s2']);
      // The reset in the menu clears all states.
      await userEvent.click(document.querySelector<HTMLElement>('.fs__reset')!);
      await harness.fixture.whenStable();
      const reload = http.expectOne(LIST);
      expect(reload.request.params.has('state')).toBe(false);
      reload.flush(page(ROWS));
    });

    it('counts states it has not seen yet instead of naming them', async () => {
      const { go, cmp } = await start('/applications', { rows: [] });
      await go('/applications?state=x1&state=x2', []);
      expect(cmp.stateChipLabel()).toBe('2 Status');
    });

    it('says when there is no state to pick yet', async () => {
      const { harness } = await start('/applications', { rows: [] });
      await userEvent.click(screen.getByRole('button', { name: 'Status' }));
      harness.detectChanges();
      expect(screen.getByText('Noch keine Status in der Liste.')).toBeInTheDocument();
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });

    it('collects the states of every page, also past a row without a state', async () => {
      const { cmp, go } = await start();
      await go('/applications?q=x', [row({ id: 'n', state: null }), row({ id: 'm', state: REVIEW })]);
      expect(cmp.stateOptions().map((o) => o.value)).toEqual(['s1', 's2']);
    });

    it('picks a cost centre in the tree sheet, without the hidden ones', async () => {
      const { cmp, harness, http } = await start();
      expect(cmp.budgetTree()[0].children.map((c) => c.id)).toEqual(['b2']);
      await userEvent.click(screen.getByRole('button', { name: 'Kostenstelle' }));
      harness.detectChanges();
      expect(cmp.budgetSheetOpen()).toBe(true);
      cmp.selectBudgetNode('b2');
      await harness.fixture.whenStable();
      const req = http.expectOne(LIST);
      expect(req.request.params.get('budget')).toBe('b2');
      req.flush(page(ROWS));
      harness.detectChanges();
      expect(cmp.sheet()).toBeNull();
      expect(cmp.budgetChipLabel()).toBe('Kultur');
      cmp.selectBudgetNode('');
      await harness.fixture.whenStable();
      const back = http.expectOne(LIST);
      expect(back.request.params.has('budget')).toBe(false);
      back.flush(page(ROWS));
    });

    it('names an unknown cost centre with the filter name', async () => {
      const { cmp, go } = await start();
      await go('/applications?budget=gone');
      expect(cmp.budgetChipLabel()).toBe('Kostenstelle');
    });

    it('hides the cost-centre chip without a tree, and the type chip without types', async () => {
      await start('/applications', { tree: 'error', types: 'error' });
      expect(screen.queryByRole('button', { name: 'Kostenstelle' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Typ' })).not.toBeInTheDocument();
    });

    it('filters by type and by archive through the menus of the chips', async () => {
      const { cmp, http, harness } = await start();
      // No native select: every chip opens the menu of the app.
      expect(document.querySelector('.apps__chips select')).toBeNull();
      const pick = async (chip: string, option: string) => {
        await userEvent.click(screen.getByRole('button', { name: chip }));
        harness.detectChanges();
        await userEvent.click(screen.getByRole('option', { name: option }));
        await harness.fixture.whenStable();
        const req = http.expectOne(LIST);
        req.flush(page(ROWS));
        harness.detectChanges();
        return req.request.params;
      };
      expect((await pick('Typ', 'Förderantrag')).get('type')).toBe('t1');
      expect(cmp.typeChipLabel()).toBe('Förderantrag');
      // A single choice closes the menu and the focus goes back to the chip.
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Typ: Förderantrag' }));

      expect((await pick('Archiv', 'Nur archivierte')).get('archived')).toBe('true');
      expect(cmp.archivedChipLabel()).toBe('Archiv: Nur archivierte');
      cmp.archived.set('all');
      expect(cmp.archivedChipLabel()).toBe('Archiv: Alle');
      harness.detectChanges();

      // Back to the default: the param goes away.
      expect((await pick('Archiv: Alle', 'Ohne archivierte')).has('archived')).toBe(false);
      expect((await pick('Typ: Förderantrag', 'Alle Typen')).has('type')).toBe(false);
    });

    it('names an unknown type with the filter name', async () => {
      const { cmp, go } = await start();
      await go('/applications?type=gone');
      expect(cmp.typeChipLabel()).toBe('Typ');
    });

    it('applies the amount and the date range of "Weitere Filter" and clears them', async () => {
      const { cmp, http, harness } = await start();
      await userEvent.click(screen.getByRole('button', { name: 'Weitere Filter' }));
      harness.detectChanges();
      expect(cmp.moreSheetOpen()).toBe(true);
      cmp.draftAmountMin.set(' 100 ');
      cmp.draftAmountMax.set('');
      cmp.draftCreatedFrom.set('2026-01-01');
      cmp.draftCreatedTo.set('2026-06-30');
      cmp.applyMore();
      await harness.fixture.whenStable();
      let req = http.expectOne(LIST);
      expect(req.request.params.get('amountMin')).toBe('100');
      expect(req.request.params.has('amountMax')).toBe(false);
      expect(req.request.params.get('createdFrom')).toBe('2026-01-01');
      expect(req.request.params.get('createdTo')).toBe('2026-06-30');
      req.flush(page(ROWS));
      harness.detectChanges();
      expect(cmp.moreCount()).toBe(3);
      expect(screen.getByRole('button', { name: 'Weitere Filter, 3 aktiv' })).toBeInTheDocument();

      // The sheet opens again with the applied values as its draft.
      cmp.openMore();
      expect(cmp.draftAmountMin()).toBe('100');
      expect(cmp.draftCreatedTo()).toBe('2026-06-30');

      cmp.clearMore();
      await harness.fixture.whenStable();
      req = http.expectOne(LIST);
      expect(req.request.params.has('amountMin')).toBe(false);
      expect(req.request.params.has('createdFrom')).toBe(false);
      req.flush(page(ROWS));
    });

    it('drops the draft of "Weitere Filter" when the sheet closes without "Anwenden"', async () => {
      const restore = stubDownload();
      try {
        const { cmp, http, harness } = await start('/applications', { total: 40 });
        await userEvent.click(screen.getByRole('button', { name: 'Weitere Filter' }));
        harness.detectChanges();
        cmp.draftAmountMin.set('500');
        cmp.draftCreatedFrom.set('2026-01-01');
        // Escape, the scrim or a swipe: the sheet closes, nothing is applied.
        cmp.sheet.set(null);
        harness.detectChanges();
        expect(cmp.moreCount()).toBe(0);
        expect(cmp.activeFilterCount()).toBe(0);
        expect(screen.getByRole('button', { name: 'Weitere Filter' })).toBeInTheDocument();

        // The next page and the export send no unapplied value.
        cmp.loadMore();
        const more = http.expectOne(LIST);
        expect(more.request.params.has('amountMin')).toBe(false);
        expect(more.request.params.has('createdFrom')).toBe(false);
        expect(more.request.params.get('offset')).toBe('3');
        more.flush(page(ROWS));
        cmp.onExport();
        const xlsx = http.expectOne((r) => r.url === '/api/applications/export.xlsx');
        expect(xlsx.request.params.has('amountMin')).toBe(false);
        xlsx.flush(new Blob(['x']));

        // A new open of the sheet starts from the applied values again.
        cmp.openMore();
        expect(cmp.draftAmountMin()).toBe('');
        expect(cmp.draftCreatedFrom()).toBe('');
      } finally {
        restore();
      }
    });

    it('sends only the applied search while the debounce waits', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http } = await start('/applications', { total: 40 });
        cmp.onSearch('fest');
        expect(cmp.searchText()).toBe('fest');
        expect(cmp.q()).toBe('');
        cmp.loadMore();
        const more = http.expectOne(LIST);
        expect(more.request.params.has('q')).toBe(false);
        more.flush(page(ROWS));
      } finally {
        jest.useRealTimers();
      }
    });

    it('debounces the search and writes q to the URL', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http, router } = await start();
        cmp.onSearch('fe');
        cmp.onSearch(' fest ');
        jest.advanceTimersByTime(400);
        await Promise.resolve();
        jest.useRealTimers();
        await new Promise((r) => setTimeout(r));
        expect(router.url).toBe('/applications?q=fest');
        http.expectOne(LIST).flush(page(ROWS));
        // An emptied search drops the param.
        jest.useFakeTimers();
        cmp.onSearch('  ');
        jest.advanceTimersByTime(400);
        jest.useRealTimers();
        await new Promise((r) => setTimeout(r));
        expect(router.url).toBe('/applications');
        http.expectOne(LIST).flush(page(ROWS));
      } finally {
        jest.useRealTimers();
      }
    });

    it('cancels a pending search when the page goes away', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, harness, http } = await start();
        cmp.onSearch('x');
        harness.fixture.destroy();
        jest.advanceTimersByTime(500);
        http.verify();
      } finally {
        jest.useRealTimers();
      }
    });

    it('shows "Nur meine Anträge" as a chip that removes the filter', async () => {
      const { go, cmp, http, harness } = await start();
      await go('/applications?mine=true');
      expect(cmp.activeFilterCount()).toBe(1);
      await userEvent.click(screen.getByRole('button', { name: 'Filter „Nur meine Anträge“ entfernen' }));
      await harness.fixture.whenStable();
      const req = http.expectOne(LIST);
      expect(req.request.params.has('mine')).toBe(false);
      req.flush(page(ROWS));
    });

    it('resets every filter in the signals and in the URL', async () => {
      const { go, cmp, http, harness, router } = await start();
      await go('/applications?state=s1&type=t1&q=x&archived=all&amountMin=5&mine=true&sort=amount');
      expect(cmp.activeFilterCount()).toBe(6);
      // A search still waiting for its debounce must not undo the reset.
      cmp.onSearch('pending');
      await userEvent.click(screen.getByRole('button', { name: 'Zurücksetzen' }));
      await harness.fixture.whenStable();
      const req = http.expectOne(LIST);
      expect(req.request.params.keys().sort()).toEqual(['limit', 'offset', 'order', 'sort']);
      req.flush(page(ROWS));
      expect(router.url).toBe('/applications?sort=amount');
      expect(cmp.activeFilterCount()).toBe(0);
      await new Promise((r) => setTimeout(r, 450));
      http.verify();
    });
  });

  describe('sort and export', () => {
    it('sorts through the sort menu', async () => {
      const { http, harness } = await start();
      await userEvent.click(screen.getByRole('button', { name: 'Sortieren' }));
      await new Promise((r) => setTimeout(r));
      harness.detectChanges();
      expect(screen.getByRole('menuitemcheckbox', { name: 'Neueste zuerst' })).toHaveAttribute('aria-checked', 'true');
      await userEvent.click(screen.getByRole('menuitemcheckbox', { name: 'Höchster Betrag zuerst' }));
      await harness.fixture.whenStable();
      const req = http.expectOne(LIST);
      expect(req.request.params.get('sort')).toBe('amount');
      expect(req.request.params.get('order')).toBe('desc');
      req.flush(page(ROWS));
    });

    it('exports the list with its filters, without paging and without mine', async () => {
      const restore = stubDownload();
      try {
        const { go, http, cmp } = await start();
        await go('/applications?state=s1&state=s2&q=fest&sort=amount&order=asc');
        await userEvent.click(screen.getByRole('button', { name: 'Exportieren' }));
        cmp.onExport();
        const req = http.expectOne((r) => r.url === '/api/applications/export.xlsx');
        const p = req.request.params;
        expect(p.getAll('state')).toEqual(['s1', 's2']);
        expect(p.get('q')).toBe('fest');
        expect(p.get('sort')).toBe('amount');
        expect(p.has('limit')).toBe(false);
        expect(p.has('offset')).toBe(false);
        req.flush(new Blob(['x']));
        expect(cmp.exporting()).toBe(false);
      } finally {
        restore();
      }
    });

    it('reports a failed export', async () => {
      const { http, cmp, toast } = await start();
      const error = jest.spyOn(toast, 'error');
      cmp.onExport();
      http.expectOne((r) => r.url === '/api/applications/export.xlsx').flush(null, { status: 500, statusText: 'x' });
      expect(cmp.exporting()).toBe(false);
      expect(error).toHaveBeenCalledWith('Der Export ist fehlgeschlagen.');
    });

    it('hides the export without the right', async () => {
      await start('/applications', { perms: ['application.read'] });
      expect(screen.queryByRole('button', { name: 'Exportieren' })).not.toBeInTheDocument();
    });

    it('exports the archived rows when the list shows them', async () => {
      const restore = stubDownload();
      try {
        const { go, http, cmp } = await start();
        await go('/applications?archived=all');
        expect(screen.getByRole('button', { name: 'Exportieren' })).toBeInTheDocument();
        cmp.onExport();
        const req = http.expectOne((r) => r.url === '/api/applications/export.xlsx');
        expect(req.request.params.get('archived')).toBe('all');
        req.flush(new Blob(['x']));
      } finally {
        restore();
      }
    });

    it('hides the export while mine is set', async () => {
      const { go, cmp, http } = await start();
      expect(screen.getByRole('button', { name: 'Exportieren' })).toBeInTheDocument();
      await go('/applications?mine=true');
      expect(screen.queryByRole('button', { name: 'Exportieren' })).not.toBeInTheDocument();
      // A call from elsewhere (the phone menu) sends nothing either.
      cmp.onExport();
      http.expectNone((r) => r.url === '/api/applications/export.xlsx');
    });

    it('puts the sort orders and the export into one menu on a phone', async () => {
      const { cmp, http, router } = await start();
      expect(cmp.phoneMenuSections().map((s) => s.items.map((i) => i.id))).toEqual([
        ['createdAt:desc', 'createdAt:asc', 'amount:desc', 'amount:asc'],
        ['export'],
      ]);
      cmp.onHeaderMenu({ id: 'export', label: 'Exportieren' });
      http.expectOne((r) => r.url === '/api/applications/export.xlsx').flush(null, { status: 500, statusText: 'x' });
      cmp.onHeaderMenu({ id: 'createdAt:asc', label: '' });
      await new Promise((r) => setTimeout(r));
      expect(router.url).toBe('/applications?sort=createdAt&order=asc');
      http.expectOne(LIST).flush(page(ROWS));
      cmp.mine.set('true');
      expect(cmp.phoneMenuSections()).toHaveLength(1);
    });
  });

  describe('list and detail', () => {
    it('opens a row in the detail and keeps the filters', async () => {
      const { go, router, cmp, harness } = await start();
      await go('/applications?q=fest');
      // The title is a real link with the filters, so it also opens in a new tab.
      const link = screen.getByRole('link', { name: 'Flyer für die Hochschulgruppen-Messe' });
      expect(link).toHaveAttribute('href', '/applications/app-2?q=fest');
      await userEvent.click(link);
      await harness.fixture.whenStable();
      harness.detectChanges();
      expect(router.url).toBe('/applications/app-2?q=fest');
      expect(cmp.selectedId()).toBe('app-2');
      // The list stays (one pane at a time here, so hidden): the filters did not change,
      // so nothing reloads, and the open row is marked.
      expect(
        screen.getByRole('link', { name: 'Flyer für die Hochschulgruppen-Messe', hidden: true }),
      ).toHaveAttribute('aria-current', 'true');
      expect(screen.getByText('detail')).toBeInTheDocument();
    });

    it('opens a deep link with the application in the detail', async () => {
      const { cmp } = await start('/applications/app-1');
      expect(cmp.selectedId()).toBe('app-1');
      expect(screen.getByText('detail')).toBeInTheDocument();
    });

    it('opens the deep link of an owner without application.read', async () => {
      // The server lists only the own applications; the page asks the same way.
      const { cmp } = await start('/applications/app-1', { perms: [] });
      expect(cmp.selectedId()).toBe('app-1');
      expect(screen.getByText('detail')).toBeInTheDocument();
    });

    it('goes back to the list with "Zur Liste" and keeps the filters', async () => {
      const { cmp, router, go } = await start();
      await go('/applications?q=x');
      await router.navigateByUrl('/applications/app-1?q=x');
      cmp.closeDetail();
      await new Promise((r) => setTimeout(r));
      expect(router.url).toBe('/applications?q=x');
      expect(cmp.selectedId()).toBeNull();
    });

    it('keeps the detail open while a filter changes', async () => {
      const { router, cmp, http, harness } = await start();
      await router.navigateByUrl('/applications/app-1');
      cmp.setFilter('type', 't1');
      await harness.fixture.whenStable();
      http.expectOne(LIST).flush(page(ROWS));
      expect(router.url).toBe('/applications/app-1?type=t1');
    });

    it('links "Antrag stellen" to the wizard', async () => {
      await start();
      expect(screen.getByRole('link', { name: 'Antrag stellen' })).toHaveAttribute('href', '/apply');
    });

    it('keeps every loaded page when the detail changes an application', async () => {
      const first = Array.from({ length: 20 }, (_, i) => row({ id: `p0-${i}`, title: `Antrag ${i}` }));
      const second = Array.from({ length: 5 }, (_, i) => row({ id: `p1-${i}`, title: `Antrag ${20 + i}` }));
      const { http, cmp, pageService, harness } = await start('/applications', { rows: first, total: 25 });
      cmp.loadMore();
      http.expectOne(LIST).flush(page(second, 25, 20));
      expect(cmp.items()).toHaveLength(25);

      pageService.notify({ id: 'p1-3', kind: 'updated', source: 'detail' });
      const req = http.expectOne(LIST);
      expect(req.request.params.get('offset')).toBe('0');
      expect(req.request.params.get('limit')).toBe('25');
      req.flush({ items: [...first, ...second], total: 25, limit: 25, offset: 0 });
      harness.detectChanges();
      expect(cmp.items().map((i) => i.id)).toContain('p1-3');
      expect(cmp.hasMore()).toBe(false);

      // A deleted application leaves the list; the other rows stay, without a request.
      pageService.notify({ id: 'p1-4', kind: 'deleted', source: 'detail' });
      http.verify();
      expect(cmp.items()).toHaveLength(24);
      expect(cmp.total()).toBe(24);
      // An unknown id changes nothing.
      pageService.notify({ id: 'gone', kind: 'deleted', source: 'detail' });
      expect(cmp.total()).toBe(24);
    });

    it('keeps the rows when the refresh after a change fails, and loads on from the old end', async () => {
      const first = Array.from({ length: 20 }, (_, i) => row({ id: `p0-${i}`, title: `Antrag ${i}` }));
      const { http, cmp, pageService } = await start('/applications', { rows: first, total: 30 });
      pageService.notify({ id: 'p0-1', kind: 'updated', source: 'detail' });
      http.expectOne(LIST).flush({}, { status: 500, statusText: 'x' });
      expect(cmp.error()).toBe(false);
      expect(cmp.items()).toHaveLength(20);
      cmp.loadMore();
      const more = http.expectOne(LIST);
      expect(more.request.params.get('offset')).toBe('20');
      more.flush(page([], 30, 20));
    });

    it('reloads the first page when a change arrives before any row', async () => {
      const { http, cmp, pageService, first } = await start('/applications', { holdList: true });
      pageService.notify({ id: 'x', kind: 'updated', source: 'detail' });
      const req = http.expectOne(LIST);
      expect(req.request.params.get('limit')).toBe('20');
      first!.flush(page(ROWS));
      expect(cmp.items()).toHaveLength(0);
      req.flush(page(ROWS));
      expect(cmp.items()).toHaveLength(3);
    });

    it('tells the detail the layout and reloads when the detail changed an application', async () => {
      const { pageService, http, cmp } = await start();
      expect(pageService.split()).toBe(cmp.split());
      pageService.notify({ id: 'app-1', kind: 'updated', source: 'detail' });
      http.expectOne(LIST).flush(page(ROWS));
      // Its own notices do not reload it a second time.
      pageService.notify({ id: 'app-1', kind: 'updated', source: 'list' });
      http.verify();
    });
  });

  describe('row menu', () => {
    const START: TransitionOutWire = { id: 'tr-1', fromStateId: 's1', toStateId: 's2', label: { de: 'Prüfung beginnen' } };
    const AGENDA: TransitionOutWire = {
      id: 'tr-2',
      fromStateId: 's1',
      toStateId: 's3',
      label: { de: 'Auf Tagesordnung setzen' },
      addsToAgenda: true,
    };

    it('loads the transitions only when the menu opens, and fires one', async () => {
      const { http, harness, toast, rail, pageService, cmp } = await start();
      const success = jest.spyOn(toast, 'success');
      const notices: unknown[] = [];
      pageService.changes$.subscribe((c) => notices.push(c));
      http.verify();
      await openRowMenu(http, 'Zuschuss Kennenlernwochenende', [START], () => harness.detectChanges());
      await userEvent.click(screen.getByRole('menuitem', { name: 'Prüfung beginnen' }));
      const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/transition');
      expect(post.request.body).toEqual({ transitionId: 'tr-1' });
      expect(cmp.busyRow()).toBe('app-1');
      // A second action waits for the first.
      cmp.onRowAction(cmp.items()[0], { kind: 'archive' });
      post.flush({ newStateId: 's2', statusEventId: 'e', dispatchedActions: [] });
      expect(success).toHaveBeenCalledWith('Status geändert.');
      expect(rail.refresh).toHaveBeenCalled();
      http.expectOne(LIST).flush(page(ROWS));
      expect(notices).toEqual([{ id: 'app-1', kind: 'updated', source: 'list' }]);
    });

    it.each([
      [403, 'applications.transitions.forbidden'],
      [409, 'applications.actions.conflict'],
      [500, 'applications.actions.error'],
    ])('reports a failed transition (%s) and reloads', async (status, key) => {
      expect(actionErrorKey(status)).toBe(key);
      const { http, cmp, toast } = await start();
      const error = jest.spyOn(toast, 'error');
      cmp.onRowAction(cmp.items()[0], { kind: 'transition', transition: { ...START, label: 'x', color: null, addsToAgenda: false, agendaGremiumId: null } });
      http.expectOne((r) => r.method === 'POST').flush({}, { status, statusText: 'x' });
      expect(error).toHaveBeenCalled();
      http.expectOne(LIST).flush(page(ROWS));
    });

    it('opens the agenda dialog for a transition onto the agenda and reloads after it', async () => {
      const { http, harness, router, cmp } = await start();
      await openRowMenu(http, 'Zuschuss Kennenlernwochenende', [{ ...AGENDA, agendaGremiumId: 'g1' }], () =>
        harness.detectChanges(),
      );
      await userEvent.click(screen.getByRole('menuitem', { name: 'Auf Tagesordnung setzen' }));
      harness.detectChanges();
      // The row stays where it is: the dialog asks for the meeting, nothing fires yet.
      expect(router.url).not.toBe('/applications/app-1');
      expect(cmp.agendaOpen()).toBe(true);
      expect(cmp.agendaFor()?.item.id).toBe('app-1');
      http.expectNone((r) => r.url === '/api/applications/app-1/transition');
      http.expectOne((r) => r.url === '/api/meetings' && r.params.get('gremiumId') === 'g1').flush([]);
      harness.detectChanges();
      expect(screen.getByRole('dialog', { name: /Auf Tagesordnung setzen/ })).toBeInTheDocument();

      // The dialog fired: the list loads its rows again.
      cmp.onAgendaDone();
      http.expectOne(LIST).flush(page(ROWS));
      cmp.agendaFor.set(null);
      cmp.onAgendaDone();
      http.verify();
    });

    it('opens the row through "Öffnen"', async () => {
      const { http, harness, router } = await start();
      await openRowMenu(http, 'Flyer für die Hochschulgruppen-Messe', [], () => harness.detectChanges());
      await userEvent.click(screen.getByRole('menuitem', { name: 'Öffnen' }));
      await harness.fixture.whenStable();
      expect(router.url).toBe('/applications/app-2');
    });

    it('opens the share links of the row', async () => {
      const { http, harness, cmp } = await start();
      await openRowMenu(http, 'Flyer für die Hochschulgruppen-Messe', [], () => harness.detectChanges());
      await userEvent.click(screen.getByRole('menuitem', { name: 'Öffentliche Links' }));
      harness.detectChanges();
      expect(cmp.shareFor()).toBe('app-2');
      http.expectOne((r) => r.url === '/api/applications/app-2/shares').flush([]);
      expect(screen.getByRole('dialog', { name: 'Öffentlicher Link' })).toBeInTheDocument();
    });

    it('opens "Status setzen" for the row and reloads after it', async () => {
      const { http, harness, cmp } = await start();
      await openRowMenu(http, 'Flyer für die Hochschulgruppen-Messe', [], () => harness.detectChanges());
      await userEvent.click(screen.getByRole('menuitem', { name: 'Status setzen' }));
      harness.detectChanges();
      http.expectOne((r) => r.url === '/api/applications/app-2/flow-states').flush([]);
      expect(cmp.forceOpen()).toBe(true);
      cmp.onForced();
      http.expectOne(LIST).flush(page(ROWS));
      cmp.forceFor.set(null);
      cmp.onForced();
      http.verify();
    });

    it('archives a row and brings an archived one back, without a question', async () => {
      const { http, harness, toast, cmp } = await start();
      const success = jest.spyOn(toast, 'success');
      await openRowMenu(http, 'Flyer für die Hochschulgruppen-Messe', [], () => harness.detectChanges());
      await userEvent.click(screen.getByRole('menuitem', { name: 'Archivieren' }));
      http.expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-2/archive').flush(ROWS[1]);
      expect(success).toHaveBeenCalledWith('Antrag archiviert.');
      http.expectOne(LIST).flush(page(ROWS));

      cmp.onRowAction(cmp.items()[2], { kind: 'archive' });
      http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/applications/app-3/archive').flush(ROWS[2]);
      http.expectOne(LIST).flush(page(ROWS));
    });

    it('reports a failed archive', async () => {
      const { http, cmp, toast } = await start();
      const error = jest.spyOn(toast, 'error');
      cmp.onRowAction(cmp.items()[0], { kind: 'archive' });
      // One row action at a time.
      cmp.onRowAction(cmp.items()[1], { kind: 'archive' });
      cmp.onRowAction(cmp.items()[1], {
        kind: 'transition',
        transition: { id: 't', fromStateId: 'a', toStateId: 'b', label: 'x', color: null, addsToAgenda: false, agendaGremiumId: null },
      });
      http.expectOne((r) => r.url.endsWith('/archive')).flush({}, { status: 500, statusText: 'x' });
      expect(error).toHaveBeenCalled();
      expect(cmp.busyRow()).toBeNull();
    });

    it('deletes only after the red confirmation', async () => {
      const { http, harness, toast, cmp } = await start();
      const success = jest.spyOn(toast, 'success');
      await openRowMenu(http, 'Flyer für die Hochschulgruppen-Messe', [], () => harness.detectChanges());
      const del = screen.getByRole('menuitem', { name: 'Löschen' });
      expect(del).toHaveClass('rm__item--danger');
      await userEvent.click(del);
      harness.detectChanges();
      http.verify();
      const dialog = screen.getByRole('dialog', { name: 'Antrag löschen' });
      expect(dialog).toHaveTextContent('„Flyer für die Hochschulgruppen-Messe“ endgültig löschen?');
      const confirm = within(dialog).getAllByRole('button', { name: 'Löschen' }).pop()!;
      await userEvent.click(confirm);
      cmp.confirmDelete();
      http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/applications/app-2').flush(null);
      expect(success).toHaveBeenCalled();
      expect(cmp.deleteFor()).toBeNull();
      // The row leaves the list without a new request.
      http.verify();
      expect(cmp.items().map((i) => i.id)).toEqual(['app-1', 'app-3']);
      expect(cmp.total()).toBe(2);
    });

    it('closes the detail when the open application was deleted', async () => {
      const { http, cmp, router } = await start();
      await router.navigateByUrl('/applications/app-1');
      cmp.deleteFor.set(cmp.items()[0]);
      cmp.confirmDelete();
      http.expectOne((r) => r.method === 'DELETE').flush(null);
      await new Promise((r) => setTimeout(r));
      expect(router.url).toBe('/applications');
    });

    it('keeps the confirmation open when the delete fails, and does nothing without a row', async () => {
      const { http, cmp, toast } = await start();
      const error = jest.spyOn(toast, 'error');
      cmp.confirmDelete();
      cmp.deleteFor.set(cmp.items()[0]);
      cmp.confirmDelete();
      cmp.confirmDelete();
      http.expectOne((r) => r.method === 'DELETE').flush({}, { status: 500, statusText: 'x' });
      expect(error).toHaveBeenCalled();
      expect(cmp.deleteFor()).not.toBeNull();
      expect(cmp.deleting()).toBe(false);
    });
  });
});
