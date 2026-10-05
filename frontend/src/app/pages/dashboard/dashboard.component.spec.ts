import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
  type TestRequest,
} from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
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
} from '@core/api/models';

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['application.read'],
  groups: [],
};

const OPEN_STATE: StateOutWire = {
  id: 's-open',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};
const REJECTED_STATE: StateOutWire = {
  id: 's-rej',
  key: 'rejected',
  label: { de: 'Abgelehnt', en: 'Rejected' },
  color: '#d0343a',
  editAllowed: false,
};

const TYPES: Page<ApplicationTypeListItemWire> = {
  items: [
    { id: 't1', name: 'Finanzantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' },
    { id: 't2', name: 'Veranstaltung', hasBudget: false, active: true, activeFormVersionId: 'v2' },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

function item(
  id: string,
  typeId: string,
  state: StateOutWire,
  extra: Partial<ApplicationListItemWire> = {},
): ApplicationListItemWire {
  return {
    id,
    typeId,
    state,
    gremiumId: null,
    amount: null,
    currency: 'EUR',
    createdAt: '2026-05-30T09:00:00Z',
    updatedAt: '2026-05-30T09:00:00Z',
    ...extra,
  };
}

const PAGE: Page<ApplicationListItemWire> = {
  items: [
    item('app-1', 't1', OPEN_STATE, { title: 'Sommerfest', stateSince: '2026-08-28T10:00:00Z' }),
    item('app-2', 't2', REJECTED_STATE),
  ],
  total: 7,
  limit: 4,
  offset: 0,
};

const TASKS: ApplicationListItemWire[] = [item('app-1', 't1', OPEN_STATE, { title: 'Sommerfest' })];

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
    gremiumId: null,
    gremiumName: null,
    votes: [],
    protocolId: null,
    createdAt: '2026-06-01T10:00:00Z',
    ...extra,
  };
}

function delegation(
  id: string,
  direction: string | null,
  extra: Record<string, unknown> = {},
): unknown {
  return {
    id,
    meetingId: 'm-planned',
    meetingTitle: '12. Sitzung',
    meetingDate: '2026-10-02',
    gremiumId: 'g1',
    gremiumName: 'StuPa',
    delegatorId: 'p1',
    delegatorName: 'Konrad Pfeiffer',
    delegateId: 'p2',
    delegateName: 'Mia Member',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-06-01T10:00:00Z',
    revocable: false,
    direction,
    ...extra,
  };
}

interface SetupOpts {
  apps?: 'ok' | 'empty' | 'error' | 'pending';
  page?: Page<ApplicationListItemWire>;
  tasks?: ApplicationListItemWire[] | 'error';
  typesError?: boolean;
  meetings?: unknown[] | 'error';
  delegations?: unknown[] | 'error';
  phone?: boolean;
}

/** Answer a request with a body or with a 500. */
function answer(req: TestRequest, body: unknown): void {
  if (body === 'error') req.flush(null, { status: 500, statusText: 'Server Error' });
  else req.flush(body);
}

async function setup(principal: Principal, opts: SetupOpts = {}) {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({
    matches: !!opts.phone && query === '(max-width: 768px)',
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
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  window.matchMedia = original;
  const auth = view.fixture.debugElement.injector.get(AuthService);
  const http = view.fixture.debugElement.injector.get(HttpTestingController);

  auth.ensureLoaded().subscribe();
  http.expectOne('/api/auth/me').flush(principal);

  const requests = {
    apps: http.expectOne((r) => r.url.endsWith('/api/applications')),
    tasks: http.expectOne((r) => r.url.endsWith('/api/applications/tasks')),
    types: http.expectOne((r) => r.url.endsWith('/api/application-types')),
    meetings: http.expectOne((r) => r.url.endsWith('/api/meetings') && r.method === 'GET'),
    delegations: http.expectOne((r) => r.url.endsWith('/api/delegations') && r.method === 'GET'),
  };

  if (opts.apps !== 'pending') {
    answer(
      requests.apps,
      opts.apps === 'error'
        ? 'error'
        : opts.apps === 'empty'
          ? { items: [], total: 0, limit: 4, offset: 0 }
          : (opts.page ?? PAGE),
    );
    answer(requests.tasks, opts.tasks ?? (opts.apps === 'empty' ? [] : TASKS));
    answer(requests.types, opts.typesError ? 'error' : TYPES);
    answer(requests.meetings, opts.meetings ?? []);
    answer(requests.delegations, opts.delegations ?? []);
  }

  view.detectChanges();
  return { ...view, auth, http, requests };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const cmp = (fixture: { componentInstance: unknown }): any => fixture.componentInstance;

describe('DashboardComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

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
      // A role name says nothing a member acts on.
      expect(screen.queryByText('Mitglied')).not.toBeInTheDocument();
      http.verify();
    });

    it('shows no gremien line for a user in no gremium', async () => {
      const { http } = await setup(MEMBER);
      expect(document.querySelector('.ph__subtitle')).toBeNull();
      http.verify();
    });

    it('offers "Antrag stellen" and opens the search from the pill', async () => {
      const { http, fixture } = await setup(MEMBER);
      expect(screen.getByRole('link', { name: /Antrag stellen/ })).toHaveAttribute('href', '/apply');
      const palette = fixture.debugElement.injector.get(CommandPaletteService);
      const pill = screen.getByRole('button', { name: 'Suche' });
      expect(pill).toHaveAttribute('aria-keyshortcuts');
      pill.click();
      expect(palette.isOpen()).toBe(true);
      http.verify();
    });

    it('keeps every request off the global overlay; the sections show their own state', async () => {
      const { requests } = await setup(MEMBER, { apps: 'pending' });
      for (const req of Object.values(requests)) {
        expect(req.request.context.get(SKIP_LOADING)).toBe(true);
        req.flush(req.request.url.endsWith('/applications') ? PAGE : []);
      }
    });
  });

  describe('meetings', () => {
    it('shows the live meeting with its start, the current item and the progress', async () => {
      const started = '2026-09-29T16:04:00Z';
      const { http } = await setup(MEMBER, {
        meetings: [
          meeting('m-live', 'live', {
            title: '34. Sitzung',
            date: '2026-09-29',
            startTime: '18:00:00',
            gremiumName: 'Studierendenparlament',
            startedAt: started,
            currentAgendaItem: { position: 3, title: 'Zuschuss Party' },
            agendaItemCount: 8,
          }),
        ],
      });
      const time = new Date(started).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
      expect(screen.getByText(`Studierendenparlament · seit ${time}`)).toBeInTheDocument();
      expect(screen.getByText('Jetzt: TOP 3 · Zuschuss Party')).toBeInTheDocument();
      expect(screen.getByText('3 / 8')).toBeInTheDocument();
      expect(screen.getByRole('img', { name: 'TOP 3 von 8' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /Live beitreten/ })).toHaveAttribute('href', '/meetings/m-live');
      // "Live" is status text, not a badge.
      const live = screen.getByText('Live');
      expect(live.closest('app-status-text')).not.toBeNull();
      expect(live.closest('app-badge')).toBeNull();
      http.verify();
    });

    it('falls back to the planned start and hides "Jetzt" without a current item', async () => {
      const { http } = await setup(MEMBER, {
        meetings: [
          meeting('m-live', 'live', {
            date: '2026-09-29',
            startTime: '18:00:00',
            gremiumName: 'StuPa',
            startedAt: null,
            agendaItemCount: 8,
          }),
        ],
      });
      expect(screen.getByText('StuPa · seit 18:00')).toBeInTheDocument();
      expect(screen.queryByText(/Jetzt:/)).not.toBeInTheDocument();
      http.verify();
    });

    it('shows weekday and time of a planned meeting and links to its agenda', async () => {
      // 10 July 2026 is a Friday.
      const { http } = await setup(MEMBER, {
        meetings: [
          meeting('m-plan', 'planned', {
            title: '12. Sitzung',
            date: '2026-07-10',
            startTime: '17:30:00',
            gremiumName: 'Finanzausschuss',
          }),
        ],
      });
      expect(screen.getByText('Finanzausschuss · Fr, 17:30')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: '12. Sitzung' })).toHaveAttribute('href', '/meetings/m-plan');
      expect(screen.getByText('Tagesordnung ansehen')).toBeInTheDocument();
      http.verify();
    });

    it('ranks live first, then planned by date, drops closed and caps at 4', async () => {
      const { fixture, http } = await setup(MEMBER, {
        meetings: [
          meeting('a', 'planned', { date: '2026-07-10' }),
          meeting('b', 'live'),
          meeting('c', 'closed'),
          meeting('d', 'planned', { date: '2026-06-20' }),
          meeting('e', 'planned'),
          meeting('f', 'planned', { date: '2026-08-01' }),
        ],
      });
      const c = cmp(fixture);
      const ids = c.sessions().map((s: { meeting: { id: string } }) => s.meeting.id);
      // A null date sorts first among the planned meetings.
      expect(ids).toEqual(['b', 'e', 'd', 'a']);
      // The count names all live and planned meetings, also those not shown.
      expect(c.sessionCount()).toBe(5);
      const head = screen.getByRole('heading', { name: 'Laufende & anstehende Sitzungen' });
      expect(within(head.parentElement!).getByText('5')).toBeInTheDocument();
      http.verify();
    });

    it('has no meetings section and one column when nothing runs or is planned', async () => {
      const { http } = await setup(MEMBER, { meetings: [meeting('c', 'closed')] });
      expect(screen.queryByText('Laufende & anstehende Sitzungen')).not.toBeInTheDocument();
      expect(document.querySelector('.dash__grid--one')).not.toBeNull();
      http.verify();
    });
  });

  describe('delegations', () => {
    it('shows no delegation section without a delegation', async () => {
      const { http } = await setup(MEMBER);
      expect(screen.queryByText('Vertretung')).not.toBeInTheDocument();
      http.verify();
    });

    it('lists an incoming delegation with the person, the meeting and the voting tag', async () => {
      const { http } = await setup(MEMBER, {
        meetings: [meeting('m-planned', 'planned', { date: '2026-10-02' })],
        delegations: [delegation('d1', 'incoming')],
      });
      expect(screen.getByRole('heading', { name: 'Vertretung' })).toBeInTheDocument();
      const row = screen.getByRole('link', { name: 'Du vertrittst Konrad Pfeiffer' });
      expect(row).toHaveAttribute('href', '/meetings/m-planned');
      expect(screen.getByText('12. Sitzung, 02.10.2026')).toBeInTheDocument();
      expect(screen.getByText('Stimmrecht')).toBeInTheDocument();
      // A person gets an avatar with the initials.
      expect(screen.getByText('KP')).toBeInTheDocument();
      http.verify();
    });

    it('shows at most four delegations on a wide screen', async () => {
      const five = Array.from({ length: 5 }, (_, i) =>
        delegation(`d${i}`, 'incoming', { meetingId: `m${i}`, meetingDate: '2999-01-01' }),
      );
      const { fixture, http } = await setup(MEMBER, { delegations: five });
      expect(cmp(fixture).delegations().length).toBe(4);
      http.verify();
    });

    it('keeps only own delegations of meetings that are not over', async () => {
      const { fixture, http } = await setup(MEMBER, {
        meetings: [
          meeting('m-live', 'live'),
          meeting('m-closed', 'closed', { date: '2999-01-01' }),
        ],
        delegations: [
          // A live meeting from the list counts, whatever its date.
          delegation('live', 'outgoing', { meetingId: 'm-live', meetingDate: '2020-01-01' }),
          // A closed meeting from the list does not.
          delegation('closed', 'incoming', { meetingId: 'm-closed', meetingDate: '2999-01-01' }),
          // A meeting outside the list counts while its date is not past.
          delegation('future', 'incoming', { meetingId: 'm-x', meetingDate: '2999-01-01' }),
          delegation('past', 'incoming', { meetingId: 'm-y', meetingDate: '2020-01-01' }),
          delegation('nodate', 'incoming', { meetingId: 'm-z', meetingDate: null }),
          // An admin sees the rows of others too, without a direction.
          delegation('other', null, { meetingId: 'm-live' }),
        ],
      });
      const c = cmp(fixture);
      expect(c.delegations().map((d: { id: string }) => d.id)).toEqual(['live', 'future']);
      expect(screen.getByRole('link', { name: 'Du wirst vertreten von Mia Member' })).toBeInTheDocument();
      http.verify();
    });
  });

  describe('tasks and own applications', () => {
    it('shows the type and the status as coloured text, never as a badge', async () => {
      const { http } = await setup(MEMBER);
      const task = within(document.getElementById('dash-tasks-h')!.closest('section')!);
      expect(task.getByRole('link', { name: 'Sommerfest' })).toHaveAttribute('href', '/applications/app-1');
      expect(task.getByText('Finanzantrag')).toBeInTheDocument();
      const state = task.getByText('Eingereicht');
      expect(state.closest('app-status-text')).not.toBeNull();
      expect(document.querySelector('app-badge')).toBeNull();
      http.verify();
    });

    it('shows the own applications with type, status and date', async () => {
      const { http } = await setup(MEMBER);
      const apps = within(document.getElementById('dash-apps-h')!.closest('section')!);
      // Without a title the type is the title, and the sub line does not repeat it.
      const untitled = apps.getByRole('link', { name: 'Veranstaltung' });
      expect(untitled).toHaveAttribute('href', '/applications/app-2');
      expect(apps.getByText('Abgelehnt').closest('app-status-text')).not.toBeNull();
      // The date is the last status change (stateSince), else the last change.
      expect(apps.getByText('28.08.')).toBeInTheDocument();
      expect(apps.getByText('30.05.')).toBeInTheDocument();
      // The count is the total, not the rows shown.
      expect(apps.getByText('7')).toBeInTheDocument();
      http.verify();
    });

    it('asks the server for the own applications only, four of them', async () => {
      const { requests, http } = await setup(MEMBER);
      expect(requests.apps.request.params.get('mine')).toBe('true');
      expect(requests.apps.request.params.get('limit')).toBe('4');
      http.verify();
    });

    it('caps both lists at 4 rows and links "Alle ansehen" to the full lists', async () => {
      const many = Array.from({ length: 6 }, (_, i) => item(`a${i}`, 't1', OPEN_STATE, { title: `A${i}` }));
      const { fixture, http } = await setup(MEMBER, {
        tasks: many,
        page: { items: many, total: 6, limit: 4, offset: 0 },
      });
      const c = cmp(fixture);
      expect(c.taskRows().length).toBe(4);
      expect(c.applicationRows().length).toBe(4);
      const links = screen.getAllByRole('link', { name: 'Alle ansehen' });
      expect(links.map((l) => l.getAttribute('href'))).toEqual(['/tasks', '/applications?mine=true']);
      http.verify();
    });

    it('shows the empty states with the apply CTA', async () => {
      const { http } = await setup(MEMBER, { apps: 'empty' });
      expect(screen.getByText('Nichts zu erledigen.')).toBeInTheDocument();
      expect(screen.getByText('Noch keine Anträge.')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Ersten Antrag stellen' })).toHaveAttribute('href', '/apply');
      expect(screen.queryByRole('link', { name: 'Alle ansehen' })).not.toBeInTheDocument();
      http.verify();
    });

    it('shows an error in each section whose request failed', async () => {
      const { http } = await setup(MEMBER, { apps: 'error', tasks: 'error' });
      expect(screen.getAllByRole('alert').map((a) => a.textContent?.trim())).toEqual([
        'Konnte nicht geladen werden.',
        'Konnte nicht geladen werden.',
      ]);
      http.verify();
    });

    it('survives failing types, meetings and delegations', async () => {
      const { fixture, http } = await setup(MEMBER, {
        typesError: true,
        meetings: 'error',
        delegations: 'error',
      });
      const c = cmp(fixture);
      expect(c.sessions()).toEqual([]);
      expect(c.delegations()).toEqual([]);
      // Without the types no raw id shows: an untitled row reads "Ohne Titel", and the
      // sub line leaves the type out.
      expect(c.name({ typeId: 't1' })).toBe('');
      expect(c.titleOf({ typeId: 't1', title: null })).toBe('Ohne Titel');
      expect(c.typeOf({ typeId: 't1', title: 'Sommerfest' })).toBeNull();
      http.verify();
    });

    it('shows row placeholders while the lists load', async () => {
      const { requests } = await setup(MEMBER, { apps: 'pending' });
      expect(document.querySelectorAll('app-skeleton').length).toBe(2);
      for (const req of Object.values(requests)) req.flush(req.request.url.endsWith('/applications') ? PAGE : []);
    });

    it('hides both lists without application.read', async () => {
      const { http } = await setup({ ...MEMBER, permissions: [] });
      expect(screen.queryByText('Offene Aufgaben')).not.toBeInTheDocument();
      expect(screen.queryByText('Meine Anträge')).not.toBeInTheDocument();
      http.verify();
    });
  });

  describe('edge cases', () => {
    it('handles missing names, titles, counts and dates', async () => {
      const { fixture, http } = await setup(MEMBER);
      const c = cmp(fixture);
      // A live meeting with an item without a title and without an agenda count.
      const row = c.sessionRow({
        id: 'x',
        title: 'X',
        status: 'live',
        date: null,
        startTime: null,
        gremiumName: null,
        startedAt: 'kein Datum',
        currentAgendaItem: { position: 1, title: null },
      });
      expect(row.now).toBeNull();
      expect(row.sub).toBe('');
      const withCount = c.sessionRow({
        id: 'y',
        title: 'Y',
        status: 'live',
        date: null,
        startTime: '18:00',
        gremiumName: 'G',
        startedAt: null,
        currentAgendaItem: { position: 2, title: null },
        agendaItemCount: 4,
      });
      expect(withCount.now).toEqual({ position: 2, title: '', count: 4 });
      // A planned meeting without date and time has no time line.
      expect(c.sessionRow({ id: 'z', title: 'Z', status: 'planned', date: 'bald', startTime: null }).sub).toBe('');

      expect(c.otherName({ direction: 'incoming', delegatorName: null })).toBe('?');
      expect(c.delegationSub({ meetingTitle: null, meetingDate: 'bald' })).toBe('bald');
      expect(c.delegationSub({ meetingTitle: 'S', meetingDate: null })).toBe('S');

      expect(c.dateOf({ stateSince: null, updatedAt: '2026-01-02T10:00:00Z' })).toBe('2026-01-02T10:00:00Z');
      expect(c.dateOf({ stateSince: undefined, updatedAt: undefined })).toBeNull();
      expect(c.shortDay(null)).toBe('');
      expect(c.shortDay('kein Datum')).toBe('');
      // Another year shows the year too.
      expect(c.shortDay('2020-03-05T10:00:00Z')).toBe('05.03.2020');
      expect(c.typeOf({ typeId: 't1', title: '  ' })).toBeNull();
      http.verify();
    });

    it('greets with the whole name when it is one word', async () => {
      const { http } = await setup({ ...MEMBER, display_name: 'Mia' });
      expect(screen.getByRole('heading', { level: 1, name: 'Willkommen, Mia' })).toBeInTheDocument();
      http.verify();
    });
  });

  describe('phone', () => {
    const live = meeting('m-live', 'live', {
      date: '2026-09-29',
      currentAgendaItem: { position: 3, title: 'Zuschuss' },
      agendaItemCount: 8,
    });

    it('has a compact head, a floating apply button and short section heads', async () => {
      const many = Array.from({ length: 5 }, (_, i) => item(`a${i}`, 't1', OPEN_STATE, { title: `A${i}` }));
      const { fixture, http } = await setup(MEMBER, {
        phone: true,
        tasks: many,
        meetings: [live, meeting('p1', 'planned'), meeting('p2', 'planned')],
      });
      expect(screen.queryByRole('link', { name: /Antrag stellen/ })).not.toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Antrag' })).toHaveAttribute('href', '/apply');
      expect(screen.getByRole('button', { name: 'Suche' })).not.toHaveAttribute('aria-keyshortcuts');
      expect(screen.getByRole('heading', { name: 'Sitzungen' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Offene Aufgaben · 5' })).toBeInTheDocument();
      expect(screen.getByText('Jetzt: TOP 3 von 8')).toBeInTheDocument();
      const c = cmp(fixture);
      // The live meeting and the next one; three tasks.
      expect(c.sessions().length).toBe(2);
      expect(c.taskRows().length).toBe(3);
      http.verify();
    });

    it('shows the gremium and the start of a live meeting without a current item', async () => {
      const { http } = await setup(MEMBER, {
        phone: true,
        meetings: [
          meeting('m-live', 'live', {
            date: '2026-09-29',
            startTime: '18:00:00',
            gremiumName: 'StuPa',
            startedAt: null,
            agendaItemCount: 8,
          }),
        ],
      });
      expect(screen.getByText('StuPa · seit 18:00')).toBeInTheDocument();
      expect(screen.queryByText(/Jetzt:/)).not.toBeInTheDocument();
      http.verify();
    });

    it('shows three delegations on a phone, like the tasks (four on a wide screen)', async () => {
      const five = Array.from({ length: 5 }, (_, i) =>
        delegation(`d${i}`, 'incoming', { meetingId: `m${i}`, meetingDate: '2999-01-01' }),
      );
      const { fixture, http } = await setup(MEMBER, { phone: true, delegations: five });
      expect(cmp(fixture).delegations().length).toBe(3);
      http.verify();
    });

    it('opens the account menu in a sheet from the avatar in the pill', async () => {
      const { fixture, http } = await setup(MEMBER, { phone: true });
      const me = screen.getByRole('button', { name: 'Konto: Mia Member' });
      expect(me).toHaveAttribute('aria-expanded', 'false');
      me.click();
      fixture.detectChanges();
      expect(cmp(fixture).accountOpen()).toBe(true);
      expect(me).toHaveAttribute('aria-expanded', 'true');
      cmp(fixture).closeAccount();
      expect(cmp(fixture).accountOpen()).toBe(false);
      http.verify();
    });
  });
});
