/**
 * The header of the application detail (board Anträge): the meta line, the status line,
 * the transition buttons, the actions and their menu, and the tabs of the narrow layout.
 *
 * Its own file, like the comments spec: the base spec is large already.
 */
import { signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BehaviorSubject } from 'rxjs';
import { ToastService } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import type {
  ApplicationOutWire,
  GremiumRef,
  StateOutWire,
  TransitionOutWire,
  VersionOutWire,
} from '@core/api/models';
import { RailStatusService } from '../../layout/rail-status.service';
import { ApplicationsDetailComponent } from './applications-detail.component';
import { ApplicationsPageService, type ApplicationChange } from './applications-page.service';

const SUBMITTED: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht' },
  color: '#4a90d9',
  editAllowed: true,
};

function appWire(over: Partial<ApplicationOutWire> = {}): ApplicationOutWire {
  return {
    id: 'app-1',
    typeId: 't1',
    state: SUBMITTED,
    gremiumId: 'g1',
    amount: '1250.00',
    currency: 'EUR',
    data: { title: 'Zuschuss Erstsemester-Abend' },
    version: 2,
    lang: 'de',
    createdAt: '2026-09-26T12:12:00Z',
    updatedAt: '2026-09-28T14:20:00Z',
    applicant: { email: 'lea@example.org', name: 'Lea', anonymized: false },
    canEdit: true,
    isOwner: false,
    archivedAt: null,
    ...over,
  };
}

const VERSIONS: VersionOutWire[] = [
  { version: 1, data: {}, diff: null, changedBy: 'Lea', at: '2026-09-26T12:12:00Z' },
  { version: 2, data: {}, diff: { added: {}, removed: {}, changed: {} }, changedBy: 'applicant', at: '2026-09-27T21:05:00Z' },
];

const TRANSITIONS: TransitionOutWire[] = [
  { id: 'tr-reject', fromStateId: 's1', toStateId: 's9', label: { de: 'Ablehnen' }, color: '#c0392b' },
  { id: 'tr-agenda', fromStateId: 's1', toStateId: 's3', label: { de: 'Auf Tagesordnung setzen' }, addsToAgenda: true },
  { id: 'tr-more', fromStateId: 's1', toStateId: 's1', label: { de: 'Nachforderung stellen' }, color: '#e8a33d' },
];

const ALL = [
  'application.read',
  'application.manage',
  'application.transition',
  'application.share',
  'application.archive',
  'application.force_status',
  'application.delete',
];

interface Opts {
  perms?: string[];
  app?: Partial<ApplicationOutWire>;
  versions?: VersionOutWire[];
  transitions?: TransitionOutWire[];
  gremien?: GremiumRef[];
  split?: boolean;
  page?: boolean;
  phone?: boolean;
  tree?: unknown[];
}

async function setup(opts: Opts = {}) {
  const perms = new Set(opts.perms ?? ALL);
  const page = new ApplicationsPageService();
  page.split.set(opts.split ?? true);
  const paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' }));
  const originalMatch = window.matchMedia;
  if (opts.phone) {
    window.matchMedia = ((q: string) => ({
      ...originalMatch(q),
      matches: q.includes('max-width: 768px'),
    })) as typeof window.matchMedia;
  }
  const view = await render(ApplicationsDetailComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      {
        provide: AuthService,
        useValue: {
          can: (p: string) => perms.has(p),
          gremien: signal(opts.gremien ?? [{ id: 'g1', name: 'Studierendenparlament', slug: 'stupa' }]),
        },
      },
      { provide: RailStatusService, useValue: { refresh: jest.fn() } },
      { provide: ActivatedRoute, useValue: { paramMap: paramMap$ } },
      ...(opts.page === false ? [] : [{ provide: ApplicationsPageService, useValue: page }]),
    ],
  });
  window.matchMedia = originalMatch;
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const cmp = view.fixture.componentInstance;
  const notices: ApplicationChange[] = [];
  page.changes$.subscribe((c) => notices.push(c));

  http.expectOne((r) => r.url === '/api/application-types').flush({
    items: [{ id: 't1', name: 'Förderantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' }],
    total: 1,
    limit: 20,
    offset: 0,
  });
  http.expectOne((r) => r.url === '/api/applications/app-1').flush(appWire(opts.app));
  http.expectOne((r) => r.url === '/api/applications/app-1/versions').flush(opts.versions ?? VERSIONS);
  http.expectOne((r) => r.url === '/api/applications/app-1/comments').flush([]);
  if (perms.has('application.transition')) {
    http.expectOne((r) => r.url === '/api/applications/app-1/transitions').flush(opts.transitions ?? TRANSITIONS);
  }
  http
    .expectOne((r) => r.url === '/api/applications/app-1/form')
    .flush({ applicationTypeId: 't1', formVersionId: 'fv', sections: [] });
  view.detectChanges();
  if (opts.tree) {
    for (const req of http.match((r) => r.url === '/api/budgets')) req.flush(opts.tree);
  }
  flushRest(http);
  view.detectChanges();
  return { ...view, http, toast, cmp, page, notices, paramMap$ };
}

/** The budget tree (managers) and the attachments load on their own. */
function flushRest(http: HttpTestingController) {
  for (const req of http.match((r) => r.url === '/api/budgets' || /\/attachments$/.test(r.url))) {
    req.flush([]);
  }
}

/** Answer the reload after a change. */
function flushRefresh(http: HttpTestingController, over: Partial<ApplicationOutWire> = {}) {
  http.expectOne((r) => r.url === '/api/applications/app-1').flush(appWire(over));
  http.expectOne((r) => r.url === '/api/applications/app-1/versions').flush(VERSIONS);
  http.expectOne((r) => r.url === '/api/applications/app-1/comments').flush([]);
  for (const req of http.match((r) => r.url === '/api/applications/app-1/transitions')) req.flush([]);
  flushRest(http);
}

async function openMenu(detectChanges: () => void) {
  await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
  await new Promise((r) => setTimeout(r));
  detectChanges();
}

describe('ApplicationsDetailComponent — header', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows "<Typ> · Version n", the title, and status · gremium · amount', async () => {
    await setup();
    expect(screen.getByText('Förderantrag · Version 2')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Zuschuss Erstsemester-Abend' })).toBeInTheDocument();
    const line = document.querySelector('.ad__line') as HTMLElement;
    // Intl puts a non-breaking space before the currency sign.
    const parts = [...line.children].map((el) => el.textContent?.replace(/\s/g, ' ').trim());
    expect(parts).toEqual(['Eingereicht', '·', 'Studierendenparlament', '·', '1.250,00 €']);
  });

  it('leaves out an unknown type, a missing gremium and a missing amount', async () => {
    const { cmp, http } = await setup({ app: { gremiumId: null, amount: null, typeId: 'other' } });
    expect(document.querySelector('.ad__meta')?.textContent?.trim()).toBe('Version 2');
    expect(document.querySelector('.ad__line')!.textContent?.trim()).toBe('Eingereicht');
    expect(cmp.gremiumName()).toBeNull();
    http.verify();
  });

  it('asks for the gremium names once when the gremium is not one of the reader’s', async () => {
    const { http, cmp, paramMap$, detectChanges } = await setup({ gremien: [] });
    http
      .expectOne((r) => r.url === '/api/meetings/gremien')
      .flush([{ id: 'g1', name: 'Haushaltsausschuss' }]);
    detectChanges();
    expect(cmp.gremiumName()).toBe('Haushaltsausschuss');
    // The next application does not ask again.
    paramMap$.next(convertToParamMap({ id: 'app-1' }));
    flushRefresh(http);
    http.expectOne((r) => r.url === '/api/applications/app-1/form').flush({ sections: [] });
    http.verify();
  });

  it('shows no gremium when its name stays unknown', async () => {
    const { http, cmp } = await setup({ gremien: [] });
    http.expectOne((r) => r.url === '/api/meetings/gremien').flush({}, { status: 403, statusText: 'x' });
    expect(cmp.gremiumName()).toBeNull();
  });

  it('shows the transitions as buttons: the first main, a rejection red, the rest tonal', async () => {
    await setup();
    const group = screen.getByRole('group', { name: 'Übergänge' });
    const buttons = within(group).getAllByRole('button');
    expect(buttons.map((b) => b.textContent?.trim())).toEqual([
      'Ablehnen',
      'Auf Tagesordnung setzen',
      'Nachforderung stellen',
    ]);
    expect(buttons[0]).toHaveClass('btn--danger');
    expect(buttons[1]).toHaveClass('btn--fill');
    expect(buttons[2]).toHaveClass('btn--tonal');
  });

  it('fires a transition and tells the list pane', async () => {
    const { http, notices } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Nachforderung stellen' }));
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/transition')
      .flush({ newStateId: 's1', statusEventId: 'e', dispatchedActions: [] });
    flushRefresh(http);
    expect(notices).toEqual([{ id: 'app-1', kind: 'updated', source: 'detail' }]);
  });

  it('offers share, edit and archive as icon buttons with their rights', async () => {
    await setup();
    expect(screen.getByRole('button', { name: 'Öffentliche Links' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Bearbeiten' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Archivieren' })).toBeInTheDocument();
  });

  it('offers no edit in a locked state and no actions without rights', async () => {
    const { http } = await setup({
      perms: ['application.read'],
      app: { state: { ...SUBMITTED, editAllowed: false } },
      versions: [VERSIONS[0]],
    });
    expect(screen.queryByRole('button', { name: 'Bearbeiten' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Öffentliche Links' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Übergänge' })).not.toBeInTheDocument();
    http.verify();
  });

  it('opens the share links from the header', async () => {
    const { http, cmp } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Öffentliche Links' }));
    expect(cmp.shareDialogOpen()).toBe(true);
    http.expectOne((r) => r.url === '/api/applications/app-1/shares').flush([]);
  });

  it('archives from the header and says so on the page', async () => {
    const { http, notices, detectChanges } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Archivieren' }));
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/archive')
      .flush(appWire({ archivedAt: '2026-09-30T10:00:00Z' }));
    detectChanges();
    expect(notices).toEqual([{ id: 'app-1', kind: 'updated', source: 'detail' }]);
    expect(screen.getByRole('status')).toHaveTextContent('Archiviert am');
    expect(screen.getByRole('button', { name: 'Aus Archiv holen' })).toBeInTheDocument();
  });

  describe('menu', () => {
    it('holds Status setzen, Versionen vergleichen and Löschen in red', async () => {
      const { detectChanges } = await setup();
      await openMenu(detectChanges);
      const items = screen.getAllByRole('menuitem').map((el) => el.textContent?.trim());
      expect(items).toEqual(['Status setzen', 'Versionen vergleichen', 'Löschen']);
      expect(screen.getByRole('menuitem', { name: 'Löschen' })).toHaveClass('rm__item--danger');
    });

    it('offers the owner the anonymization, and nobody once it is anonymized', async () => {
      const owner = await setup({ perms: ['application.read'], app: { isOwner: true } });
      await openMenu(owner.detectChanges);
      expect(screen.getAllByRole('menuitem').map((el) => el.textContent?.trim())).toEqual([
        'Versionen vergleichen',
        'Anonymisierung beantragen',
      ]);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Anonymisierung beantragen' }));
      expect(owner.cmp.confirmErase()).toBe(true);
      owner.cmp.app.update((a) => (a ? { ...a, applicant: { name: null, email: null, anonymized: true } } : a));
      expect(owner.cmp.canRequestErasure()).toBe(false);
    });

    it('leaves "Versionen vergleichen" out with only one version', async () => {
      const { cmp } = await setup({ versions: [VERSIONS[0]] });
      expect(cmp.menuSections().flatMap((s) => s.items.map((i) => i.id))).toEqual(['force', 'delete']);
    });

    it('opens the force dialog, confirms the delete, and reloads after a forced state', async () => {
      const { cmp, http, detectChanges, notices } = await setup();
      await openMenu(detectChanges);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Status setzen' }));
      detectChanges();
      expect(cmp.forceDialogOpen()).toBe(true);
      http.expectOne((r) => r.url === '/api/applications/app-1/flow-states').flush([]);
      cmp.onForced();
      flushRefresh(http);
      expect(notices).toHaveLength(1);

      cmp.onMenu({ id: 'delete', label: '' });
      expect(cmp.confirmDelete()).toBe(true);
    });

    it('scrolls to the history side by side', async () => {
      const { cmp } = await setup();
      const el = document.getElementById('ad-history')!;
      const scroll = jest.fn();
      el.scrollIntoView = scroll;
      cmp.onMenu({ id: 'versions', label: '' });
      expect(scroll).toHaveBeenCalled();
      expect(document.activeElement).toBe(el);
    });

    it('does nothing for an unknown item or without an application', async () => {
      const { cmp } = await setup();
      cmp.onMenu({ id: 'nope', label: '' });
      cmp.app.set(null);
      expect(cmp.menuSections()).toEqual([]);
      expect(cmp.metaLine()).toBe('');
      cmp.onMenu({ id: 'delete', label: '' });
      expect(cmp.confirmDelete()).toBe(false);
    });

    it('holds only the rights the reader has on a phone', async () => {
      const { cmp } = await setup({ phone: true, perms: ['application.read'], versions: [VERSIONS[0]], app: { state: { ...SUBMITTED, editAllowed: false } } });
      expect(cmp.menuSections()).toEqual([]);
    });

    it('takes the header actions into the menu on a phone', async () => {
      const { cmp, http, detectChanges } = await setup({ phone: true });
      expect(screen.queryByRole('button', { name: 'Öffentliche Links' })).not.toBeInTheDocument();
      expect(cmp.menuSections()[0].items.map((i) => i.id)).toEqual(['share', 'edit', 'archive']);
      cmp.onMenu({ id: 'share', label: '' });
      detectChanges();
      http.expectOne((r) => r.url.endsWith('/shares')).flush([]);
      cmp.onMenu({ id: 'archive', label: '' });
      http.expectOne((r) => r.url.endsWith('/archive')).flush(appWire({ archivedAt: 'x' }));
      expect(cmp.menuSections()[0].items[2].label).toBe('Aus Archiv holen');
      // The edit form needs structuredClone, which jsdom lacks.
      const g = globalThis as unknown as { structuredClone?: unknown };
      const saved = g.structuredClone;
      g.structuredClone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
      cmp.onMenu({ id: 'edit', label: '' });
      g.structuredClone = saved;
      expect(cmp.editing()).toBe(true);
    });
  });

  describe('tabs (one pane at a time)', () => {
    it('shows the sections in tabs with their counts', async () => {
      const { detectChanges } = await setup({ split: false });
      const tabs = screen.getAllByRole('tab').map((t) => t.getAttribute('aria-label') ?? t.textContent?.trim());
      expect(tabs).toEqual(['Antrag', 'Verlauf 2', 'Kommentare 0', 'Anhänge 0']);
      expect(screen.getByRole('tabpanel', { name: 'Antrag' })).toBeVisible();
      await userEvent.click(screen.getByRole('tab', { name: 'Verlauf 2' }));
      detectChanges();
      expect(screen.getByRole('tabpanel', { name: 'Verlauf 2' })).toBeInTheDocument();
      expect(screen.queryByRole('tabpanel', { name: 'Antrag' })).not.toBeInTheDocument();
    });

    it('switches to the history for "Versionen vergleichen"', async () => {
      const { cmp } = await setup({ split: false });
      cmp.showVersions();
      expect(cmp.tab()).toBe('history');
      cmp.selectTab('files');
      expect(cmp.tab()).toBe('files');
      cmp.selectTab('nope');
      cmp.selectTab(null);
      expect(cmp.tab()).toBe('files');
      cmp.selectTab('comments');
      cmp.selectTab('app');
      expect(cmp.tab()).toBe('app');
    });

    it('works without the list page: tabs, no notices', async () => {
      const { cmp, http } = await setup({ page: false });
      expect(cmp.split()).toBe(false);
      cmp.toggleArchived();
      http.expectOne((r) => r.url.endsWith('/archive')).flush(appWire({ archivedAt: 'x' }));
    });
  });

  describe('changes from the list pane', () => {
    it('loads the application again when the list changed it', async () => {
      const { page, http } = await setup();
      page.notify({ id: 'app-1', kind: 'updated', source: 'list' });
      flushRefresh(http);
    });

    it('ignores its own notices, other applications and deletes', async () => {
      const { page, http } = await setup();
      page.notify({ id: 'app-1', kind: 'updated', source: 'detail' });
      page.notify({ id: 'app-2', kind: 'updated', source: 'list' });
      page.notify({ id: 'app-1', kind: 'deleted', source: 'list' });
      http.verify();
    });

    it('tells the list pane about a delete and keeps the filters', async () => {
      const { cmp, http, notices, fixture } = await setup();
      const router = fixture.debugElement.injector.get(Router);
      const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
      cmp.doDelete();
      http.expectOne((r) => r.method === 'DELETE').flush(null);
      expect(notices).toEqual([{ id: 'app-1', kind: 'deleted', source: 'detail' }]);
      expect(nav).toHaveBeenCalledWith(['/applications'], { queryParamsHandling: 'preserve' });
    });
  });

  describe('cost centre and fiscal year', () => {
    const TREE = [
      { id: 'b0', parentId: null, key: '000', pathKey: '000', name: 'Leer', children: [] },
      { id: 'b1', parentId: null, key: '100', pathKey: '100', name: 'Haushalt', children: [
        { id: 'b2', parentId: 'b1', key: '110', pathKey: '100-110', name: 'Kultur', children: [] },
      ] },
    ];
    const YEARS = [
      { id: 'fy1', budgetId: 'b1', year: 2026, display: '2026', startDate: '', endDate: '', active: true },
      { id: 'fy0', budgetId: 'b1', year: 2025, display: '2025', startDate: '', endDate: '', active: false },
    ];
    const YEARS_URL = (r: { url: string }) => r.url === '/api/budgets/b1/fiscal-years';

    it('names the cost centre with its fiscal year and changes both in the dialog', async () => {
      const { http, cmp, detectChanges } = await setup({ app: { budgetId: 'b2', fiscalYearId: 'fy1' }, tree: TREE });
      http.expectOne(YEARS_URL).flush(YEARS);
      detectChanges();
      expect(screen.getByText('Kostenstelle · HHJ 2026')).toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Kostenstelle ändern' }));
      http.expectOne(YEARS_URL).flush(YEARS);
      detectChanges();
      const c = cmp as unknown as {
        fiscalOptions: () => { value: string; label: string }[];
        onBudgetPicked: (id: string) => void;
        fiscalChoice: () => string;
        fiscalYears: () => unknown[];
      };
      expect(c.fiscalOptions().map((o) => o.label)).toEqual(['Automatisch (aktives HHJ)', '2026', '2025 (inaktiv)']);

      // Another cost centre of the same top budget: the year choice goes back to automatic.
      c.onBudgetPicked('b1');
      expect(c.fiscalChoice()).toBe('');
      http.expectOne(YEARS_URL).flush({}, { status: 500, statusText: 'x' });
      expect(c.fiscalYears()).toEqual([]);
      // The original cost centre again: its year comes back.
      c.onBudgetPicked('b2');
      expect(c.fiscalChoice()).toBe('fy1');
      http.expectOne(YEARS_URL).flush(YEARS);
      // No cost centre, or one outside the tree: no years to choose.
      c.onBudgetPicked('');
      c.onBudgetPicked('gone');
      expect(c.fiscalYears()).toEqual([]);
      http.verify();
    });

    it('names a cost centre without a year and offers "Zuordnen" without one', async () => {
      const { http } = await setup({ app: { budgetId: null, fiscalYearId: null }, tree: TREE });
      expect(screen.getByRole('button', { name: 'Kostenstelle' })).toHaveTextContent('Zuordnen');
      expect(screen.getAllByText('Keine').length).toBeGreaterThan(0);
      http.verify();
    });

    it('drops the years of an application it no longer shows', async () => {
      const { http, cmp, paramMap$ } = await setup({ app: { budgetId: 'b2', fiscalYearId: 'fy1' }, tree: TREE });
      const stale = http.expectOne(YEARS_URL);
      paramMap$.next(convertToParamMap({ id: 'app-1' }));
      stale.flush(YEARS);
      expect((cmp as unknown as { fiscalYears: () => unknown[] }).fiscalYears()).toEqual([]);
      for (const req of http.match(() => true)) req.flush([]);
    });
  });

  it('reports a failed archive', async () => {
    const { http, cmp, toast } = await setup();
    const error = jest.spyOn(toast, 'error');
    cmp.toggleArchived();
    cmp.toggleArchived();
    http.expectOne((r) => r.url.endsWith('/archive')).flush({}, { status: 500, statusText: 'x' });
    expect(error).toHaveBeenCalled();
    expect(cmp.archiving()).toBe(false);
  });
});
