import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import { DashboardComponent } from './dashboard.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
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
  permissions: ['application.read', 'vote.cast'],
  groups: [],
};

const OPEN_STATE: StateOutWire = {
  id: 's-open',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};
const CLOSED_STATE: StateOutWire = {
  id: 's-closed',
  key: 'decided',
  label: { de: 'Entschieden', en: 'Decided' },
  color: null,
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

function item(id: string, typeId: string, state: StateOutWire): ApplicationListItemWire {
  return {
    id,
    typeId,
    state,
    gremiumId: null,
    budgetPotId: null,
    amount: null,
    currency: 'EUR',
    createdAt: '2026-05-30T09:00:00Z',
    updatedAt: '2026-05-30T09:00:00Z',
  };
}

// Two applications; one open (a task) + one closed (only "my applications").
const PAGE: Page<ApplicationListItemWire> = {
  items: [item('app-1', 't1', OPEN_STATE), item('app-2', 't2', CLOSED_STATE)],
  total: 2,
  limit: 20,
  offset: 0,
};

// Offene Aufgaben (GET /applications/tasks): nur der actionable Antrag app-1.
const TASKS: ApplicationListItemWire[] = [item('app-1', 't1', OPEN_STATE)];

async function setup(
  principal: Principal,
  opts: {
    apps?: 'ok' | 'empty' | 'error';
    tasks?: ApplicationListItemWire[];
    tasksError?: boolean;
    typesError?: boolean;
    meetings?: unknown[];
    meetingsError?: boolean;
    delegations?: unknown[];
    delegationsError?: boolean;
  } = {},
) {
  const view = await render(DashboardComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const auth = view.fixture.debugElement.injector.get(AuthService);
  const http = view.fixture.debugElement.injector.get(HttpTestingController);

  auth.ensureLoaded().subscribe();
  http.expectOne('/api/auth/me').flush(principal);

  const appsReq = http.expectOne((r) => r.url.endsWith('/api/applications'));
  if (opts.apps === 'error') {
    appsReq.flush(null, { status: 500, statusText: 'Server Error' });
  } else if (opts.apps === 'empty') {
    appsReq.flush({ items: [], total: 0, limit: 20, offset: 0 });
  } else {
    appsReq.flush(PAGE);
  }
  // „Offene Aufgaben" laden GET /applications/tasks getrennt von „Meine Anträge".
  const tasksReq = http.expectOne((r) => r.url.endsWith('/api/applications/tasks'));
  if (opts.tasksError) {
    tasksReq.flush(null, { status: 500, statusText: 'Server Error' });
  } else {
    tasksReq.flush(opts.tasks ?? (opts.apps === 'empty' ? [] : TASKS));
  }
  const typesReq = http.expectOne((r) => r.url.endsWith('/api/application-types'));
  if (opts.typesError) {
    typesReq.flush(null, { status: 500, statusText: 'Server Error' });
  } else {
    typesReq.flush(TYPES);
  }
  // Sitzungs-Shortcuts (#Sessions) laden `/meetings`.
  http
    .match((r) => r.url.endsWith('/api/meetings') && r.method === 'GET')
    .forEach((req) => {
      if (opts.meetingsError) req.flush(null, { status: 500, statusText: 'Server Error' });
      else req.flush(opts.meetings ?? []);
    });
  // Vertretungs-Karte (#delegation-rework) lädt `/delegations`.
  http
    .match((r) => r.url.endsWith('/api/delegations') && r.method === 'GET')
    .forEach((req) => {
      if (opts.delegationsError) req.flush(null, { status: 500, statusText: 'Server Error' });
      else req.flush(opts.delegations ?? []);
    });

  view.detectChanges();
  return { ...view, auth, http };
}

function meeting(id: string, status: string, date: string | null = null): unknown {
  return {
    id,
    title: `Sitzung ${id}`,
    date,
    startTime: null,
    endTime: null,
    status,
    activeApplicationId: null,
    gremiumId: null,
    gremiumName: null,
    votes: [],
    protocolId: null,
    createdAt: '2026-06-01T10:00:00Z',
    protokollantId: null,
    protokollantName: null,
    isProtokollant: false,
    canControl: false,
    canManage: false,
    canWrite: false,
    canManageVotes: false,
  };
}

function delegation(id: string, revocable: boolean, direction: string | null): unknown {
  return {
    id,
    meetingId: 'm1',
    meetingTitle: 'S',
    meetingDate: '2026-06-20',
    gremiumId: 'g1',
    gremiumName: 'StuPa',
    delegatorId: 'p1',
    delegatorName: 'A',
    delegateId: 'p2',
    delegateName: 'B',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-06-01T10:00:00Z',
    revocable,
    direction,
  };
}

describe('DashboardComponent', () => {
  it('greets the signed-in member by name and shows their roles', async () => {
    const { http } = await setup(MEMBER);
    expect(screen.getByText('Willkommen, Mia Member')).toBeInTheDocument();
    // Rolle 'member' lokalisiert (de → Mitglied).
    expect(screen.getByText('Mitglied')).toBeInTheDocument();
    http.verify();
  });

  it('offers a prominent "submit application" CTA linking to the wizard', async () => {
    const { http } = await setup(MEMBER);
    const cta = screen.getByRole('link', { name: /Antrag stellen/ });
    expect(cta).toHaveAttribute('href', '/apply');
    http.verify();
  });

  it('separates open tasks from my applications with distinct content', async () => {
    const { http } = await setup(MEMBER);
    expect(screen.getByText('Offene Aufgaben')).toBeInTheDocument();
    expect(screen.getByText('Meine Anträge')).toBeInTheDocument();

    // Open task = the non-closed application; appears in BOTH panels (tasks = the
    // actionable subset of my applications) and deep-links to its detail.
    const openLinks = screen.getAllByRole('link', { name: 'Finanzantrag' });
    expect(openLinks.length).toBe(2);
    for (const l of openLinks) expect(l).toHaveAttribute('href', '/applications/app-1');
    // The closed application is NOT a task — shows only under "my applications".
    const closedLinks = screen.getAllByRole('link', { name: 'Veranstaltung' });
    expect(closedLinks.length).toBe(1);
    expect(closedLinks[0]).toHaveAttribute('href', '/applications/app-2');
    // State labels are rendered as badges.
    expect(screen.getByText('Entschieden')).toBeInTheDocument();
    http.verify();
  });

  it('shows an empty state with an apply CTA when there are no applications', async () => {
    const { http } = await setup(MEMBER, { apps: 'empty' });
    expect(screen.getByText('Noch keine Anträge.')).toBeInTheDocument();
    const cta = screen.getByRole('link', { name: /Ersten Antrag stellen/ });
    expect(cta).toHaveAttribute('href', '/apply');
    http.verify();
  });

  it('surfaces an error state when the applications request fails', async () => {
    const { http } = await setup(MEMBER, { apps: 'error' });
    expect(screen.getAllByText('Konnte nicht geladen werden.').length).toBeGreaterThan(0);
    http.verify();
  });

  it('falls back to empty data when tasks/types/meetings/delegations all fail', async () => {
    const { fixture, http } = await setup(MEMBER, {
      tasksError: true,
      typesError: true,
      meetingsError: true,
      delegationsError: true,
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.openTasks()).toEqual([]);
    expect(c.sessionShortcuts()).toEqual([]);
    expect(c.delegations()).toEqual([]);
    // type name falls back to the raw id when types failed
    expect(c.name({ typeId: 't1' })).toBe('t1');
    http.verify();
  });

  it('resolves type names and prefers the system title over the type', async () => {
    const { fixture, http } = await setup(MEMBER);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.name({ typeId: 't1' })).toBe('Finanzantrag');
    expect(c.name({ typeId: 'unknown' })).toBe('unknown');
    expect(c.titleOf({ typeId: 't1', title: '  Mein Titel  ' })).toBe('Mein Titel');
    expect(c.titleOf({ typeId: 't2', title: '   ' })).toBe('Veranstaltung');
    expect(c.titleOf({ typeId: 't2' })).toBe('Veranstaltung');
    expect(c.created({ createdAt: '2026-05-30T09:00:00Z' })).toBe('2026-05-30T09:00:00Z');
    expect(c.created({})).toBeNull();
    http.verify();
  });

  it('ranks session shortcuts live-first, then planned by date, dropping closed', async () => {
    const { fixture, http } = await setup(MEMBER, {
      meetings: [
        meeting('a', 'planned', '2026-07-10'),
        meeting('b', 'live'),
        meeting('c', 'closed'),
        meeting('d', 'planned', '2026-06-20'),
        meeting('e', 'planned', null),
        // a non-live/planned/closed status survives the filter → rank's fallback (2) branch
        meeting('z', 'paused'),
      ],
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const ids = c.sessionShortcuts().map((m: { id: string }) => m.id);
    // closed dropped, live first, then planned by date asc (null sorts first), 'paused' last, capped at 4
    expect(ids).toEqual(['b', 'e', 'd', 'a']);
    expect(c.sessionStatusKey('live')).toBe('meetings.status.live');
    expect(c.sessionVariant('live')).toBe('success');
    expect(c.sessionVariant('planned')).toBe('info');
    expect(c.sessionVariant('closed')).toBe('neutral');
    http.verify();
  });

  it('roleLabel localises known roles and echoes unknown ones', async () => {
    const { fixture } = await setup(MEMBER);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.roleLabel('member')).toBe('Mitglied');
    expect(c.roleLabel('totally_unknown_role')).toBe('totally_unknown_role');
    expect(c.roles()).toContain('member');
    expect(Array.isArray(c.gremien())).toBe(true);
  });

  it('shows only revocable delegations and reports their direction', async () => {
    const { fixture, http } = await setup(MEMBER, {
      delegations: [
        delegation('d1', true, 'outgoing'),
        delegation('d2', false, 'incoming'),
        delegation('d3', true, 'incoming'),
      ],
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const ids = c.delegations().map((d: { id: string }) => d.id);
    expect(ids).toEqual(['d1', 'd3']);
    expect(c.isOutgoing({ direction: 'outgoing' })).toBe(true);
    expect(c.isOutgoing({ direction: 'incoming' })).toBe(false);
    http.verify();
  });

  it('gates the application panels on the application.read permission', async () => {
    const noRead: Principal = { ...MEMBER, permissions: [] };
    const { fixture, http } = await setup(noRead);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.canReadApplications()).toBe(false);
    http.verify();
  });

  it('reports loading and totals from the applications page', async () => {
    const { fixture, http } = await setup(MEMBER);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.loading()).toBe(false);
    expect(c.error()).toBe(false);
    expect(c.total()).toBe(2);
    expect(c.applicationRows().length).toBe(2);
    http.verify();
  });

  it('defaults total to 0 and rows to empty when the applications request errored', async () => {
    const { fixture, http } = await setup(MEMBER, { apps: 'error' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // applications() is null → the ?. / ?? fallbacks kick in
    expect(c.total()).toBe(0);
    expect(c.applicationRows()).toEqual([]);
    expect(c.loading()).toBe(false);
    expect(c.error()).toBe(true);
    http.verify();
  });

  it('sorts two null-date planned meetings deterministically (both ?? sides)', async () => {
    const { fixture, http } = await setup(MEMBER, {
      meetings: [
        meeting('p1', 'planned', null),
        meeting('p2', 'planned', null),
        meeting('p3', 'planned', '2026-06-20'),
      ],
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const ids = c.sessionShortcuts().map((m: { id: string }) => m.id);
    expect(ids).toContain('p1');
    expect(ids).toContain('p2');
    expect(ids).toContain('p3');
    http.verify();
  });
});
