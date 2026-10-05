import { Router, provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
  type TestRequest,
} from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DashboardComponent } from './dashboard.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { SKIP_LOADING } from '@core/loading/loading.interceptor';
import { CommandPaletteService } from '../../features/search/command-palette.service';
import type {
  ApplicationListItemWire,
  ApplicationTypeListItemWire,
  Page,
  Principal,
  StateOutWire,
  VoteListItem,
} from '@core/api/models';

/** "Now": Tuesday, 29 September 2026, 18:50 local time. */
const NOW = new Date(2026, 8, 29, 18, 50);

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['application.read'],
  groups: [],
};
/** A member with a voting right and the budget rights. */
const TREASURER: Principal = {
  ...MEMBER,
  permissions: ['application.read', 'budget.view'],
  gremien: [{ id: 'g1', name: 'Studierendenparlament', slug: 'stupa' }],
  gremium_permissions: { g1: ['vote.cast'] },
};

const OPEN_STATE: StateOutWire = {
  id: 's-open',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};
const OK_STATE: StateOutWire = {
  id: 's-ok',
  key: 'approved',
  label: { de: 'Bewilligt', en: 'Approved' },
  color: '#2e9e5b',
  editAllowed: false,
};

const TYPES: Page<ApplicationTypeListItemWire> = {
  items: [
    { id: 't1', name: 'Förderantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' },
    { id: 't2', name: 'Reisekosten', hasBudget: false, active: true, activeFormVersionId: 'v2' },
    { id: 't3', name: 'Alt', hasBudget: false, active: false, activeFormVersionId: null },
  ],
  total: 3,
  limit: 20,
  offset: 0,
};

function item(
  id: string,
  extra: Partial<ApplicationListItemWire> = {},
): ApplicationListItemWire {
  return {
    id,
    typeId: 't1',
    state: OPEN_STATE,
    gremiumId: null,
    amount: '1250.00',
    currency: 'EUR',
    createdAt: '2026-09-01T09:00:00Z',
    updatedAt: '2026-09-20T09:00:00Z',
    ...extra,
  };
}

const TASKS: ApplicationListItemWire[] = [
  item('task-1', { title: 'Zuschuss Erstsemester-Party', stateSince: new Date(2026, 8, 28, 10).toISOString() }),
];
const MINE: Page<ApplicationListItemWire> = {
  items: [item('app-1', { title: 'Filmabend', state: OK_STATE, stateSince: new Date(2026, 7, 28, 10).toISOString() })],
  total: 7,
  limit: 25,
  offset: 0,
};

function vote(id: string, extra: Partial<VoteListItem> = {}): VoteListItem {
  return {
    id,
    question: `Frage ${id}`,
    status: 'open',
    result: null,
    secret: false,
    applicationId: null,
    meetingId: 'm-live',
    meetingTitle: '34. Sitzung',
    agendaItemId: 'ag3',
    agendaPosition: 3,
    gremiumId: 'g1',
    gremiumName: 'Studierendenparlament',
    createdAt: '2026-09-29T16:00:00Z',
    openedAt: '2026-09-29T16:30:00Z',
    closedAt: null,
    closesAt: null,
    canCast: true,
    myBallot: { cast: false, choice: null },
    ...extra,
  };
}

const VOTES: Page<VoteListItem> = {
  items: [vote('v1'), vote('v2', { status: 'closed', result: 'passed', agendaPosition: null })],
  total: 2,
  limit: 25,
  offset: 0,
};

function meeting(id: string, status: string, extra: Record<string, unknown> = {}): unknown {
  return {
    id,
    title: `Sitzung ${id}`,
    date: null,
    startTime: null,
    endTime: null,
    status,
    activeApplicationId: null,
    currentAgendaItemId: null,
    gremiumId: 'g1',
    gremiumName: 'Studierendenparlament',
    votes: [],
    protocolId: null,
    createdAt: '2026-06-01T10:00:00Z',
    ...extra,
  };
}

function delegation(direction: string | null, extra: Record<string, unknown> = {}): unknown {
  return {
    id: `d-${direction}`,
    meetingId: 'm-plan',
    meetingTitle: '12. Sitzung',
    meetingDate: '2026-10-02',
    gremiumId: 'g1',
    gremiumName: 'StuPa',
    delegatorId: 'p1',
    delegatorName: 'Konrad Pfeiffer',
    delegateId: 'p2',
    delegateName: 'Jonas Weber',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-06-01T10:00:00Z',
    revocable: false,
    direction,
    ...extra,
  };
}

function budgetRoot(id: string, extra: Record<string, unknown> = {}): unknown {
  return {
    id,
    parentId: null,
    gremiumId: null,
    key: 'VS',
    pathKey: 'VS',
    name: `Haushalt ${id}`,
    currency: 'EUR',
    active: true,
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [
      {
        fiscalYearId: 'fy26',
        allocated: '186000.00',
        bound: '60000.00',
        expended: '27230.00',
        income: '0',
        committed: '87230.00',
        requested: '16061.20',
        available: '97770.00',
      },
    ],
    children: [],
    ...extra,
  };
}

function fiscalYear(id: string, year: number, extra: Record<string, unknown> = {}): unknown {
  return {
    id,
    budgetId: 'b1',
    year,
    display: String(year),
    startDate: `${year}-01-01`,
    endDate: `${year}-12-31`,
    active: false,
    ...extra,
  };
}

type Body = unknown | 'error' | 'pending';

interface SetupOpts {
  tasks?: Body;
  mine?: Body;
  votes?: Body;
  timeline?: Body;
  delegations?: Body;
  types?: Body;
  /** Budget tree, then the fiscal years by root id; only for a person with the right. */
  budgets?: Body;
  fiscalYears?: Record<string, Body>;
  invoices?: Body;
  phone?: boolean;
  wide?: boolean;
  extraWide?: boolean;
  url?: string;
}

/** Answer a request with a body or with a 500, or leave it open. */
function answer(req: TestRequest, body: Body): void {
  if (body === 'pending') return;
  if (body === 'error') req.flush(null, { status: 500, statusText: 'Server Error' });
  else req.flush(body);
}

async function setup(principal: Principal, opts: SetupOpts = {}) {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({
    matches:
      (!!opts.phone && query === '(max-width: 768px)') ||
      (!!opts.wide && query === '(min-width: 1200px)') ||
      (!!opts.extraWide && query === '(min-width: 1680px)'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;

  const view = await render(DashboardComponent, {
    providers: [
      provideRouter([{ path: '**', children: [] }]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  window.matchMedia = original;
  const injector = view.fixture.debugElement.injector;
  const auth = injector.get(AuthService);
  const http = injector.get(HttpTestingController);
  const router = injector.get(Router);
  if (opts.url) {
    await router.navigateByUrl(opts.url);
  }

  auth.ensureLoaded().subscribe();
  http.expectOne('/api/auth/me').flush(principal);

  const requests = {
    tasks: http.expectOne((r) => r.url.endsWith('/api/applications/tasks')),
    mine: http.expectOne((r) => r.url.endsWith('/api/applications')),
    votes: http.expectOne((r) => r.url.endsWith('/api/votes')),
    timeline: http.expectOne((r) => r.url.endsWith('/api/meetings/timeline')),
    delegations: http.expectOne((r) => r.url.endsWith('/api/delegations')),
    types: http.expectOne((r) => r.url.endsWith('/api/application-types')),
  };
  answer(requests.tasks, opts.tasks ?? TASKS);
  answer(requests.mine, opts.mine ?? MINE);
  answer(requests.votes, opts.votes ?? VOTES);
  answer(requests.timeline, opts.timeline ?? { items: [], nextCursor: null });
  answer(requests.delegations, opts.delegations ?? []);
  answer(requests.types, opts.types ?? TYPES);

  // The budget requests follow the session: they start once it shows the right.
  view.fixture.detectChanges();
  await view.fixture.whenStable();
  const budgetReq = http.match((r) => r.url.endsWith('/api/budgets'));
  for (const req of budgetReq) answer(req, opts.budgets ?? []);
  view.fixture.detectChanges();
  for (const [id, body] of Object.entries(opts.fiscalYears ?? {})) {
    for (const req of http.match((r) => r.url.endsWith(`/api/budgets/${id}/fiscal-years`))) {
      answer(req, body);
    }
  }
  const invoiceReq = http.match((r) => r.url.endsWith('/api/invoices'));
  for (const req of invoiceReq) answer(req, opts.invoices ?? { items: [], total: 0, limit: 1, offset: 0 });

  view.detectChanges();
  return { ...view, auth, http, router, requests, budgetReq, invoiceReq };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const cmp = (fixture: { componentInstance: unknown }): any => fixture.componentInstance;

describe('DashboardComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    jest.spyOn(Date, 'now').mockReturnValue(NOW.getTime());
  });
  afterEach(() => jest.restoreAllMocks());

  describe('head', () => {
    it('greets the member by first name and lists the gremien in one line', async () => {
      const { http } = await setup({
        ...MEMBER,
        gremien: [
          { id: 'g1', name: 'Studierendenparlament' },
          { id: 'g2', name: 'Finanzausschuss' },
        ],
      } as Principal);
      expect(screen.getByRole('heading', { level: 1, name: 'Willkommen, Mia' })).toBeInTheDocument();
      expect(screen.getByText('Studierendenparlament · Finanzausschuss')).toBeInTheDocument();
      http.verify();
    });

    it('offers "Antrag stellen" and opens the search from the pill', async () => {
      const { http, fixture } = await setup(MEMBER);
      expect(screen.getByRole('link', { name: /Antrag stellen/ })).toHaveAttribute('href', '/apply');
      const palette = fixture.debugElement.injector.get(CommandPaletteService);
      screen.getByRole('button', { name: 'Suche' }).click();
      expect(palette.isOpen()).toBe(true);
      http.verify();
    });

    it('keeps every request off the global overlay', async () => {
      const { requests } = await setup(MEMBER, {
        tasks: 'pending',
        mine: 'pending',
        votes: 'pending',
        timeline: 'pending',
        delegations: 'pending',
        types: 'pending',
      });
      for (const req of Object.values(requests)) {
        expect(req.request.context.get(SKIP_LOADING)).toBe(true);
      }
    });

    it('loads the own applications by the date of the last status change', async () => {
      const { requests } = await setup(MEMBER);
      const params = requests.mine.request.params;
      expect(params.get('mine')).toBe('true');
      expect(params.get('sort')).toBe('stateSince');
      expect(params.get('order')).toBe('desc');
    });

    it('loads only the upcoming meetings of the timeline, not every meeting', async () => {
      const { requests, http } = await setup(MEMBER);
      expect(requests.timeline.request.params.get('direction')).toBe('upcoming');
      http.expectNone((r) => r.url.endsWith('/api/meetings'));
    });
  });

  describe('work list', () => {
    it('shows the tasks as a table with type, status, waiting time and amount', async () => {
      const { http } = await setup(MEMBER);
      expect(screen.getByRole('tab', { name: 'Offene Aufgaben 1' })).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('tab', { name: 'Meine Anträge 7' })).toBeInTheDocument();
      // The tab counts the open votes only.
      expect(screen.getByRole('tab', { name: 'Abstimmungen 1' })).toBeInTheDocument();
      const table = screen.getByRole('table');
      expect(within(table).getByText('Wartet')).toBeInTheDocument();
      expect(within(table).getByText('Zuschuss Erstsemester-Party')).toBeInTheDocument();
      expect(within(table).getByText('Förderantrag')).toBeInTheDocument();
      expect(within(table).getByText('Eingereicht')).toBeInTheDocument();
      expect(within(table).getByText('1 Tag')).toBeInTheDocument();
      expect(within(table).getByText(/1\.250,00/)).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Alle Aufgaben öffnen' })).toHaveAttribute('href', '/tasks');
      http.verify();
    });

    it('opens the detail page of a row', async () => {
      const { fixture, router } = await setup(MEMBER);
      const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
      cmp(fixture).openRow(cmp(fixture).taskRows()[0]);
      expect(navigate).toHaveBeenCalledWith(['/tasks', 'task-1']);
    });

    it('keeps the tab in the URL; the first tab leaves no parameter', async () => {
      const { fixture, router } = await setup(MEMBER);
      const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
      await userEvent.click(screen.getByRole('tab', { name: /Meine Anträge/ }));
      expect(navigate).toHaveBeenLastCalledWith(
        [],
        expect.objectContaining({ queryParams: { tab: 'mine' }, replaceUrl: true }),
      );
      cmp(fixture).setTab('nonsense');
      expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { tab: null } }));
    });

    it('opens the tab of the URL: own applications with their date', async () => {
      const { fixture, http } = await setup(MEMBER, { url: '/?tab=mine' });
      expect(cmp(fixture).tab()).toBe('mine');
      const table = screen.getByRole('table');
      expect(within(table).getByText('Seit')).toBeInTheDocument();
      expect(within(table).getByText('28.08.')).toBeInTheDocument();
      expect(within(table).getByText('Bewilligt')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Alle Anträge öffnen' })).toHaveAttribute(
        'href',
        '/applications?mine=true',
      );
      expect(cmp(fixture).mineRows()[0].link).toEqual(['/applications', 'app-1']);
      http.verify();
    });

    it('opens the first tab for an unknown tab in the URL', async () => {
      const { fixture } = await setup(MEMBER, { url: '/?tab=nope' });
      expect(cmp(fixture).tab()).toBe('tasks');
    });

    it('shows the votes with the meeting, the status and the own ballot', async () => {
      const { fixture } = await setup(TREASURER, {
        url: '/?tab=votes',
        votes: {
          items: [
            vote('v1', { myBallot: { cast: true, choice: 'yes' } }),
            vote('v2'),
            vote('v3', { status: 'closed', result: 'rejected', canCast: false }),
            vote('v4', { status: 'draft', meetingTitle: null, question: ' ' }),
            vote('v5', { status: 'cancelled', meetingTitle: '33. Sitzung', agendaPosition: null }),
          ],
          total: 5,
          limit: 25,
          offset: 0,
        },
      });
      const table = screen.getByRole('table');
      expect(within(table).getByText('Eigener Stand')).toBeInTheDocument();
      expect(within(table).getAllByText('34. Sitzung · TOP 3')).toHaveLength(3);
      expect(within(table).getByText('Abgestimmt')).toBeInTheDocument();
      expect(within(table).getByText('Stimme offen')).toBeInTheDocument();
      expect(within(table).getByText('33. Sitzung')).toBeInTheDocument();
      const rows = cmp(fixture).voteRows();
      expect(rows.map((r: { ballot: string | null }) => r.ballot)).toEqual(['cast', 'pending', null, null, null]);
      // A vote without a meeting names its gremium.
      expect(rows[3].where).toBe('Studierendenparlament');
      expect(rows[3].statusKey).toBe('voting.list.status.draft');
      expect(rows[3].title).toBe('Beschlussfrage');
      expect(rows[2].statusKey).toBe('vote.result.rejected');
      expect(rows[0].link).toEqual(['/voting', 'v1']);
      expect(screen.getByRole('link', { name: 'Alle Abstimmungen öffnen' })).toHaveAttribute('href', '/voting');
    });

    it('hides "Alle Abstimmungen öffnen" from a person without a voting right', async () => {
      await setup(MEMBER, { url: '/?tab=votes' });
      expect(screen.queryByRole('link', { name: 'Alle Abstimmungen öffnen' })).not.toBeInTheDocument();
    });

    it('shows a skeleton while the tab loads and an error when it fails', async () => {
      const { fixture, requests } = await setup(MEMBER, { tasks: 'pending' });
      expect(cmp(fixture).tabLoading()).toBe(true);
      expect(screen.getByRole('tab', { name: 'Offene Aufgaben' })).toBeInTheDocument();
      requests.tasks.flush(null, { status: 500, statusText: 'x' });
      fixture.detectChanges();
      expect(screen.getByRole('alert')).toHaveTextContent('Konnte nicht geladen werden.');
      expect(cmp(fixture).tabEmpty()).toBe(false);
      expect(screen.queryByRole('link', { name: 'Alle Aufgaben öffnen' })).not.toBeInTheDocument();
    });

    it('counts nothing while every list failed', async () => {
      const { fixture } = await setup(MEMBER, { tasks: 'error', mine: 'error', votes: 'error' });
      expect(cmp(fixture).taskRows()).toEqual([]);
      expect(cmp(fixture).mineRows()).toEqual([]);
      expect(cmp(fixture).voteRows()).toEqual([]);
      expect(cmp(fixture).tabs().map((t: { count: number | null }) => t.count)).toEqual([null, null, null]);
    });

    it('shows the empty state of each tab', async () => {
      const { fixture, router } = await setup(MEMBER, {
        tasks: [],
        votes: { items: [], total: 0, limit: 25, offset: 0 },
      });
      expect(screen.getByText('Nichts zu tun')).toBeInTheDocument();
      expect(cmp(fixture).tabEmpty()).toBe(true);
      // The user has own applications: no card "Antrag stellen".
      expect(screen.queryByRole('heading', { name: 'Antrag stellen' })).not.toBeInTheDocument();
      await router.navigateByUrl('/?tab=votes');
      fixture.detectChanges();
      expect(screen.getByText('Keine Abstimmungen')).toBeInTheDocument();
    });

    it('gives a new user the empty tab and the card "Antrag stellen" with the active types', async () => {
      const { fixture, router } = await setup(MEMBER, {
        tasks: [],
        mine: { items: [], total: 0, limit: 25, offset: 0 },
      });
      expect(cmp(fixture).newUser()).toBe(true);
      const card = screen.getByRole('region', { name: 'Antrag stellen' });
      expect(within(card).getByRole('link', { name: 'Förderantrag' })).toHaveAttribute('href', '/apply?type=t1');
      expect(within(card).getByRole('link', { name: 'Reisekosten' })).toBeInTheDocument();
      expect(within(card).queryByRole('link', { name: 'Alt' })).not.toBeInTheDocument();
      await router.navigateByUrl('/?tab=mine');
      fixture.detectChanges();
      expect(screen.getByText('Noch keine Anträge')).toBeInTheDocument();
    });

    it('builds the rows from what the list item holds', async () => {
      const { fixture } = await setup(MEMBER, {
        types: 'error',
        tasks: [
          item('a', { title: '  ', state: null as unknown as StateOutWire, amount: null, stateSince: null }),
          item('b', { title: null as unknown as string, amount: '12', currency: null as unknown as string, updatedAt: 'kaputt' }),
          item('c', { title: 'Heute', stateSince: new Date(2026, 8, 29, 9).toISOString() }),
          item('d', { title: 'Alt', amount: 'abc', stateSince: new Date(2026, 8, 19, 9).toISOString() }),
        ],
        mine: {
          items: [
            item('m1', { title: 'Vorjahr', stateSince: new Date(2025, 4, 3, 9).toISOString() }),
            item('m2', { title: 'Ohne', stateSince: null, updatedAt: 'kaputt' }),
          ],
          total: 2,
          limit: 25,
          offset: 0,
        },
      });
      const rows = cmp(fixture).taskRows();
      // No type name (the types failed) and no title: "Ohne Titel".
      expect(rows[0].title).toBe(cmp(fixture).i18n.translate('applications.list.untitled'));
      expect(rows[0].statusLabel).toBe('');
      expect(rows[0].amount).toBeNull();
      // Without `stateSince` the waiting time counts from the last change.
      expect(rows[0].since).toBe('9 Tage');
      expect(rows[1].amount).toMatch(/^12,00\s€$/);
      expect(rows[3].amount).toBe('abc');
      expect(rows[1].since).toBe('—');
      expect(rows[1].sinceTitle).toBeNull();
      expect(rows[2].since).toBe('heute');
      expect(rows[3].since).toBe('10 Tage');
      const mine = cmp(fixture).mineRows();
      expect(mine[0].since).toBe('03.05.2025');
      expect(mine[1].since).toBe('—');
    });

    it('shows list rows and fewer of them on a phone, with short tab labels', async () => {
      const many = Array.from({ length: 7 }, (_, i) => item(`t${i}`, { title: `Aufgabe ${i}` }));
      const { fixture, router } = await setup(MEMBER, { phone: true, tasks: many });
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      expect(cmp(fixture).taskRows()).toHaveLength(5);
      expect(screen.getByRole('tab', { name: 'Aufgaben 7' })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: 'Anträge 7' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Aufgabe 0' })).toHaveAttribute('href', '/tasks/t0');
      await router.navigateByUrl('/?tab=votes');
      fixture.detectChanges();
      expect(screen.getByRole('link', { name: 'Frage v1' })).toHaveAttribute('href', '/voting/v1');
      expect(screen.getByText('Stimme offen')).toBeInTheDocument();
    });
  });

  describe('Heute', () => {
    it('shows the live meeting with progress, keeper, own vote state and "Live beitreten"', async () => {
      const started = new Date(2026, 8, 29, 18, 4).toISOString();
      const { fixture, http } = await setup(MEMBER, {
        wide: true,
        timeline: {
          items: [
            meeting('m-live', 'live', {
              title: '34. Sitzung',
              date: '2026-09-29',
              startedAt: started,
              isProtokollant: true,
              currentAgendaItem: { position: 3, title: 'Zuschuss Party' },
              agendaItemCount: 8,
              canVote: true,
              votes: [{ id: 'v1', status: 'open', myBallot: { cast: true, choice: null } }],
            }),
          ],
          nextCursor: null,
        },
      });
      expect(fixture.nativeElement.classList).toContain('pane-page');
      const live = screen.getByRole('region', { name: 'Laufende Sitzung' });
      expect(within(live).getByText('seit 18:04 · Du führst Protokoll')).toBeInTheDocument();
      expect(within(live).getByText('3 / 8')).toBeInTheDocument();
      expect(within(live).getByRole('img', { name: 'TOP 3 von 8' })).toBeInTheDocument();
      expect(within(live).getByText('Zuschuss Party')).toBeInTheDocument();
      expect(within(live).getByText('Du hast abgestimmt')).toBeInTheDocument();
      expect(within(live).getByRole('link', { name: /Live beitreten/ })).toHaveAttribute('href', '/meetings/m-live');
      expect(cmp(fixture).noMeetings()).toBe(false);
      http.verify();
    });

    it('falls back to the planned start; says when the own vote is missing', async () => {
      const { fixture } = await setup(MEMBER, {
        timeline: {
          items: [
            meeting('a', 'live', {
              startTime: '18:00:00',
              currentAgendaItem: { position: 2, title: null },
              agendaItemCount: 8,
              canVote: true,
              votes: [{ id: 'v1', status: 'open' }],
            }),
            meeting('b', 'live', {
              currentAgendaItem: { position: 1, title: null },
              agendaItemCount: 0,
              votes: [{ id: 'v2', status: 'open', myBallot: { cast: false, choice: null } }],
            }),
            meeting('c', 'live', { startedAt: 'kaputt', votes: [{ id: 'v3', status: 'closed' }] }),
          ],
          nextCursor: null,
        },
      });
      const [a, b, c] = cmp(fixture).live();
      expect(a.sub).toBe('seit 18:00');
      expect(a.now).toEqual({ position: 2, title: '', count: 8 });
      expect(a.vote).toEqual({ ballot: 'pending' });
      expect(screen.getByText('Deine Stimme fehlt')).toBeInTheDocument();
      expect(b.sub).toBe('');
      expect(b.now).toBeNull();
      expect(b.vote).toEqual({ ballot: null });
      expect(c.vote).toBeNull();
      expect(c.sub).toBe('');
    });

    it('lists the next meetings with the delegation note, weekday and time', async () => {
      // 2 October 2026 is a Friday.
      const { fixture } = await setup(TREASURER, {
        timeline: {
          items: [
            meeting('m-plan', 'planned', { title: '12. Sitzung', date: '2026-10-02', startTime: '17:30:00' }),
            meeting('m-2', 'planned', { title: '35. Sitzung', date: '2026-10-13', startTime: '18:00:00' }),
            meeting('m-3', 'planned', { title: 'Ohne Datum', gremiumName: null }),
            meeting('m-4', 'planned', { title: 'Vierte', date: '2026-10-27' }),
          ],
          nextCursor: 'more',
        },
        delegations: [delegation(null, { id: 'admin-row', meetingId: 'm-2' }), delegation('incoming')],
      });
      expect(screen.getByRole('heading', { name: 'Anstehende Sitzungen · 4+' })).toBeInTheDocument();
      const rows = cmp(fixture).upcoming();
      expect(rows).toHaveLength(3);
      expect(rows[0].note).toBe('Du vertrittst Konrad Pfeiffer');
      expect(rows[0].when).toBe('Fr, 17:30');
      // A row of other persons (no direction) gives no note.
      expect(rows[1].note).toBeNull();
      expect(rows[2].when).toBe('');
      expect(screen.getByText('Du vertrittst Konrad Pfeiffer')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: '12. Sitzung' })).toHaveAttribute('href', '/meetings/m-plan');
      expect(screen.getByRole('link', { name: 'Sitzungen öffnen' })).toHaveAttribute('href', '/meetings');
    });

    const PLANNED = Array.from({ length: 6 }, (_, i) =>
      meeting(`p${i}`, 'planned', { date: '2026-10-0' + (i + 1) }),
    );

    it('notes an outgoing delegation and shows five meetings on a very wide screen', async () => {
      const out = delegation('outgoing', { meetingId: 'p0', delegateName: null });
      const inc = delegation('incoming', { id: 'd-in', meetingId: 'p1', delegatorName: null });
      const { fixture } = await setup(MEMBER, {
        extraWide: true,
        timeline: { items: PLANNED, nextCursor: null },
        delegations: [out, inc],
      });
      expect(cmp(fixture).upcoming()[1].note).toBe('Du vertrittst ?');
      expect(cmp(fixture).upcoming()).toHaveLength(5);
      expect(cmp(fixture).upcoming()[0].note).toBe('Du wirst vertreten von ?');
      expect(cmp(fixture).plannedCount()).toBe('6');
    });

    it('shows two meetings on a phone', async () => {
      const { fixture } = await setup(MEMBER, { phone: true, timeline: { items: PLANNED, nextCursor: null } });
      expect(cmp(fixture).upcoming()).toHaveLength(2);
    });

    it('says "Keine Sitzungen" and why for a person in no gremium', async () => {
      const { fixture } = await setup(MEMBER, { delegations: 'error' });
      expect(cmp(fixture).noMeetings()).toBe(true);
      expect(screen.getByText('Keine Sitzungen')).toBeInTheDocument();
      expect(screen.getByText(/Du bist in keinem Gremium/)).toBeInTheDocument();
      // Without access to the meetings page, the sheet has no link to it.
      expect(screen.queryByRole('link', { name: 'Sitzungen öffnen' })).not.toBeInTheDocument();
    });

    it('says "Keine Sitzungen" to a member when nothing is planned', async () => {
      await setup(TREASURER);
      expect(screen.getByText('Für deine Gremien ist keine Sitzung geplant.')).toBeInTheDocument();
    });

    it('shows a skeleton while the timeline loads', async () => {
      const { fixture } = await setup(MEMBER, { timeline: 'pending' });
      expect(cmp(fixture).meetingsLoading()).toBe(true);
      expect(cmp(fixture).noMeetings()).toBe(false);
    });

    it('treats a failed timeline as no meetings', async () => {
      const { fixture } = await setup(MEMBER, { timeline: 'error' });
      expect(cmp(fixture).noMeetings()).toBe(true);
    });

    it('names the date of today', async () => {
      const { fixture } = await setup(MEMBER);
      expect(cmp(fixture).todayLabel()).toBe('Di, 29.09.2026');
    });
  });

  describe('budget', () => {
    it('loads no budget for a person without the right', async () => {
      const { budgetReq, invoiceReq, fixture } = await setup(MEMBER);
      expect(budgetReq).toHaveLength(0);
      expect(invoiceReq).toHaveLength(0);
      expect(cmp(fixture).budgets()).toEqual([]);
      expect(screen.queryByRole('heading', { name: 'Finanzen' })).not.toBeInTheDocument();
    });

    it('shows the current fiscal year: available, used share and open invoices', async () => {
      const { fixture } = await setup(TREASURER, {
        budgets: [budgetRoot('b1')],
        fiscalYears: { b1: [fiscalYear('fy25', 2025), fiscalYear('fy26', 2026)] },
        invoices: { items: [], total: 2, limit: 1, offset: 0 },
      });
      const [b] = cmp(fixture).budgets();
      expect(b).toEqual(
        expect.objectContaining({ id: 'b1', fyId: 'fy26', title: 'Budget HHJ 2026', used: 47 }),
      );
      expect(screen.getByRole('heading', { name: 'Finanzen' })).toBeInTheDocument();
      const link = screen.getByRole('link', { name: /Budget HHJ 2026/ });
      expect(link).toHaveAttribute('href', '/budget?budget=b1&fy=fy26');
      expect(link).toHaveTextContent('2 offene Rechnungen');
      expect(link).toHaveTextContent('47 % gebunden oder ausgegeben');
    });

    it('names each root when there are more, and picks the active or the first year', async () => {
      const { fixture } = await setup(TREASURER, {
        budgets: [
          budgetRoot('b1'),
          budgetRoot('b2', {
            byFiscalYear: [
              { fiscalYearId: 'fyx', allocated: '0', bound: 'x', expended: '0', income: '0', committed: '0', requested: '0', available: '0' },
            ],
          }),
          budgetRoot('b3'),
          budgetRoot('hidden', { hiddenInBudget: true }),
        ],
        fiscalYears: {
          b1: [fiscalYear('fy26', 2027), fiscalYear('fy99', 2028, { active: true })],
          b2: [fiscalYear('fyx', 2030)],
        },
        invoices: { items: [], total: 1, limit: 1, offset: 0 },
      });
      const rows = cmp(fixture).budgets();
      // b1: no year holds today and the active one has no figures.
      expect(rows.map((r: { id: string }) => r.id)).toEqual(['b2']);
      expect(rows[0].title).toBe('Haushalt b2 · HHJ 2030');
      expect(rows[0].used).toBe(0);
      expect(screen.getByText(/1 offene Rechnung$/)).toBeInTheDocument();
    });

    it('picks the active year when no year holds today', async () => {
      const { fixture } = await setup(TREASURER, {
        budgets: [budgetRoot('b1')],
        fiscalYears: { b1: [fiscalYear('fy0', 2020), fiscalYear('fy26', 2027, { active: true })] },
      });
      expect(cmp(fixture).budgets()[0].fyId).toBe('fy26');
      expect(cmp(fixture).budgets()[0].available).toMatch(/97\.770,00/);
    });

    it('drops a root whose years fail or are missing; a failed invoice count is 0', async () => {
      const { fixture } = await setup(TREASURER, {
        budgets: [budgetRoot('b1'), budgetRoot('b2')],
        fiscalYears: { b1: 'error', b2: [] },
        invoices: 'error',
      });
      expect(cmp(fixture).budgets()).toEqual([]);
      expect(cmp(fixture).openInvoices()).toBe(0);
    });

    it('leaves the amount out when the server sends none', async () => {
      const root = budgetRoot('b1') as { byFiscalYear: Record<string, string>[] };
      root.byFiscalYear[0]['available'] = '';
      const { fixture } = await setup(TREASURER, {
        budgets: [root],
        fiscalYears: { b1: [fiscalYear('fy26', 2026)] },
      });
      expect(cmp(fixture).budgets()[0].available).toBe('');
    });

    it('survives a failed tree', async () => {
      const { fixture } = await setup(TREASURER, { budgets: 'error' });
      expect(cmp(fixture).budgets()).toEqual([]);
    });

    it('shows nothing when every root is hidden', async () => {
      const { fixture } = await setup(TREASURER, { budgets: [budgetRoot('h', { hiddenInBudget: true })] });
      expect(cmp(fixture).budgets()).toEqual([]);
    });
  });

  describe('phone', () => {
    it('gives the compact head with the account sheet and the floating button', async () => {
      const { fixture } = await setup(MEMBER, { phone: true });
      expect(screen.getByRole('link', { name: /^Antrag$/ })).toHaveAttribute('href', '/apply');
      const me = screen.getByRole('button', { name: /Konto/ });
      expect(me).toHaveAttribute('aria-expanded', 'false');
      cmp(fixture).openAccount();
      fixture.detectChanges();
      expect(cmp(fixture).accountOpen()).toBe(true);
      cmp(fixture).closeAccount();
      expect(cmp(fixture).accountOpen()).toBe(false);
    });
  });
});
