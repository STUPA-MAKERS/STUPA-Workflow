import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject } from 'rxjs';
import { EMPTY, of } from 'rxjs';
import { ToastService } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Meeting, MeetingOutWire, ProtocolOutWire } from '@core/api/models';
import { WsService, type MeetingChannel } from '@core/ws/ws.service';
import type { ServerMessage } from '@core/ws/ws-messages';
import { MeetingAgendaService } from './meeting-agenda.service';
import { MeetingSessionService } from './meeting-session.service';
import { MeetingsComponent } from './meetings.component';

const MEETING: MeetingOutWire = {
  id: 'm-1',
  title: 'StuPa-Sitzung',
  status: 'live',
  // Date and time are required. Without them the settings dialog does not save.
  date: '2026-06-12',
  startTime: '17:00',
  endTime: null,
  activeApplicationId: 'app-1',
  currentAgendaItemId: null,
  gremiumId: null,
  protocolId: 'p-1',
  canControl: true,
  canManage: true,
  canWrite: true,
  canManageVotes: true,
  canVote: false,
  canFinalize: true,
  votes: [
    {
      id: 'v-1',
      applicationId: 'app-1',
      title: 'Antrag A',
      status: 'open',
      result: null,
      counts: { ja: 5, nein: 2 },
      leading: 'ja',
      closesAt: null,
    },
    {
      id: 'v-2',
      applicationId: 'app-2',
      title: 'Antrag B',
      status: 'draft',
      result: null,
      counts: null,
      leading: null,
      closesAt: null,
    },
  ],
  createdAt: '2026-06-12T17:00:00Z',
};

/** Domain form (all fields required) for places that expect `Meeting` instead of
 *  `MeetingOutWire`, for example `meeting.set` or `openSettings`. Without it tsc
 *  complains about the optional wire fields. Content is identical to `MEETING`. */
const MEETING_MODEL: Meeting = {
  id: 'm-1',
  title: 'StuPa-Sitzung',
  status: 'live',
  date: '2026-06-12',
  startTime: '17:00',
  endTime: null,
  activeApplicationId: 'app-1',
  currentAgendaItemId: null,
  gremiumId: null,
  gremiumName: null,
  protocolId: 'p-1',
  createdAt: '2026-06-12T17:00:00Z',
  protokollantId: null,
  protokollantName: null,
  isProtokollant: false,
  canControl: true,
  canManage: true,
  canWrite: true,
  canManageVotes: true,
  canVote: false,
  canFinalize: true,
  keeperPeriods: [],
  plannedHandover: null,
  votes: [
    {
      id: 'v-1', applicationId: 'app-1', agendaItemId: null, title: 'Antrag A',
      question: null, options: [], status: 'open', result: null,
      counts: { ja: 5, nein: 2 }, leading: 'ja', closesAt: null,
      voted: 0, present: 0, revealed: true, failedReason: null,
    },
    {
      id: 'v-2', applicationId: 'app-2', agendaItemId: null, title: 'Antrag B',
      question: null, options: [], status: 'draft', result: null,
      counts: null, leading: null, closesAt: null,
      voted: 0, present: 0, revealed: true, failedReason: null,
    },
  ],
};

const PROTOCOL: ProtocolOutWire = {
  id: 'p-1',
  meetingId: 'm-1',
  markdown: '# Protokoll',
  status: 'draft',
  pdfUrl: null,
  sentAt: null,
};

/** Fake WsService that provides a controllable message stream. */
class FakeWs {
  readonly subject = new Subject<ServerMessage>();
  sent: unknown[] = [];
  closed = false;
  connectMeeting(): MeetingChannel {
    return {
      messages$: this.subject.asObservable(),
      send: (m) => this.sent.push(m),
      close: () => {
        this.closed = true;
      },
    };
  }
}

function fakeAuth(perms: string[], userId: string | null = 'pr-1'): Partial<AuthService> {
  const set = new Set(perms);
  return {
    can: (p: string) => set.has(p),
    canAny: (...p: string[]) => p.some((x) => set.has(x)),
    isAdmin: (() => set.has('admin')) as unknown as AuthService['isAdmin'],
    userId: (() => userId) as unknown as AuthService['userId'],
    gremien: (() => []) as unknown as AuthService['gremien'],
    sessionManageGremien: (() => []) as unknown as AuthService['sessionManageGremien'],
    inSubstitutePool: (() => false) as unknown as AuthService['inSubstitutePool'],
  };
}

/**
 * Router double. `navigate` is the only method the component calls. The rest is
 * the read-only surface that the breadcrumbs of `app-page-header` read.
 */
function routerStub(navigate: jest.Mock = jest.fn(() => Promise.resolve(true))) {
  return {
    navigate,
    events: EMPTY,
    config: [],
    routerState: { snapshot: { root: { url: [], data: {}, firstChild: null } } },
  };
}

async function setup(
  opts: {
    perms?: string[];
    id?: string | null;
    gremien?: { id: string; name: string }[];
    meetings?: MeetingOutWire[];
    userId?: string | null;
    /** Do NOT auto-answer the initial timeline requests. The test flushes them itself. */
    skipTimelineFlush?: boolean;
  } = {},
) {
  const perms = opts.perms ?? ['admin', 'protocol.write'];
  const userId = opts.userId === undefined ? 'pr-1' : opts.userId;
  const id = opts.id === undefined ? 'm-1' : opts.id;
  const ws = new FakeWs();
  const navigate = jest.fn(() => Promise.resolve(true));
  const view = await render(MeetingsComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(perms, userId) },
      { provide: WsService, useValue: ws },
      { provide: Router, useValue: routerStub(navigate) },
      {
        provide: ActivatedRoute,
        useValue: { paramMap: of(convertToParamMap(id ? { id } : {})) },
      },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  // The Gremium dropdown loads `/gremien` at start, only for a meeting manager.
  http.match((r) => r.url.endsWith('/gremien')).forEach((req) => req.flush(opts.gremien ?? []));
  // The overview route loads the timeline: one cursor page each for past and upcoming.
  const isPast = (m: MeetingOutWire) => m.status === 'closed';
  if (!opts.skipTimelineFlush) {
    http
      .match((r) => r.url.endsWith('/meetings/timeline') && r.method === 'GET')
      .forEach((req) => {
        const past = req.request.params.get('direction') === 'past';
        const items = (opts.meetings ?? []).filter((m) => (past ? isPast(m) : !isPast(m)));
        req.flush({ items, nextCursor: null });
      });
  }
  return { ...view, http, ws, navigate };
}

/** Load meeting + (auto) protocol + attendance + agenda — answer all requests. */
function flushLoad(http: HttpTestingController): void {
  http.expectOne('/api/meetings/m-1').flush(MEETING);
  http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
  http.expectOne('/api/meetings/m-1/attendance').flush([]);
  http.expectOne('/api/meetings/m-1/agenda').flush([]);
  flushDelegationContext(http);
}

/** Delegation card: answer the meeting context neutrally. The feature is disabled
 *  in the test Gremium, so the card stays hidden. */
function flushDelegationContext(http: HttpTestingController): void {
  http
    .match((r) => r.url.endsWith('/api/delegations/meetings/m-1/context'))
    .forEach((req) =>
      req.flush({
        meetingId: 'm-1',
        gremiumId: 'g-1',
        allowVoteDelegation: false,
        votingDelegationEnabled: false,
        delegationAllowExternal: false,
        deadline: null,
        deadlinePassed: false,
        meetingStarted: false,
        canDelegate: false,
        myDelegation: null,
        incoming: [],
        recipients: [],
      }),
    );
}

describe('MeetingsComponent', () => {
  it('shows a forbidden notice without the required permissions', async () => {
    await setup({ perms: [], id: null });
    expect(screen.getByRole('alert')).toHaveTextContent(/Keine Berechtigung/i);
    // The list (and its header) does not show, so the page header titles the notice.
    expect(screen.getByRole('heading', { level: 1, name: 'Sitzungen' })).toBeInTheDocument();
  });

  it('loads the meeting and renders session control with votes', async () => {
    const { http } = await setup();
    flushLoad(http);
    expect(await screen.findByText('Sitzungssteuerung')).toBeInTheDocument();
    expect(screen.getByText('Antrag A')).toBeInTheDocument();
    expect(screen.getByText('Antrag B')).toBeInTheDocument();
    // The delegation card loads its context only after rendering, so flush again.
    flushDelegationContext(http);
    http.verify();
  });

  it('opens a planned vote via the API', async () => {
    const { http } = await setup();
    flushLoad(http);
    const openBtn = await screen.findByRole('button', { name: /Abstimmung öffnen/i });
    await userEvent.click(openBtn);
    const req = http.expectOne('/api/votes/v-2/open');
    expect(req.request.method).toBe('POST');
    req.flush(null, { status: 204, statusText: 'No Content' });
  });

  it('closes an open vote via the API', async () => {
    const { http } = await setup();
    flushLoad(http);
    const closeBtn = await screen.findByRole('button', { name: /Abstimmung schließen/i });
    await userEvent.click(closeBtn);
    const req = http.expectOne('/api/votes/v-1/close');
    expect(req.request.method).toBe('POST');
    req.flush({
      id: 'v-1',
      applicationId: 'app-1',
      result: 'passed',
      tally: { counts: {}, eligible: 0, quorumMet: true, leading: null },
      branchFired: true,
    });
  });

  it('sets the active application via PATCH', async () => {
    const { http } = await setup();
    flushLoad(http);
    // "Set active" on the second (not-yet-active) vote.
    const buttons = await screen.findAllByRole('button', { name: /Aktiv setzen/i });
    await userEvent.click(buttons[buttons.length - 1]);
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ activeApplicationId: 'app-2' });
    req.flush({ ...MEETING, activeApplicationId: 'app-2' });
  });

  it('closes without a finalize, then finalizes as a step of its own (O13)', async () => {
    const { http } = await setup();
    const idle: MeetingOutWire = { ...MEETING, votes: [] };
    http.expectOne('/api/meetings/m-1').flush(idle);
    http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([
      { id: 't-1', applicationId: null, title: 'Begrüßung', body: 'Eröffnet.', position: 0 },
    ]);
    flushDelegationContext(http);

    // Closing is final: the toolbar button opens the confirmation dialog.
    const bar = await screen.findByRole('toolbar', { name: 'Sitzungssteuerung' });
    await userEvent.click(within(bar).getByRole('button', { name: 'Sitzung schließen' }));
    const confirm = await screen.findByRole('dialog', { name: 'Sitzung schließen?' });
    expect(within(confirm).getByText('Keine offene Abstimmung')).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole('button', { name: 'Sitzung schließen' }));
    const closeReq = http.expectOne('/api/meetings/m-1');
    expect(closeReq.request.method).toBe('PATCH');
    expect(closeReq.request.body).toEqual({ status: 'closed' });
    closeReq.flush({ ...idle, status: 'closed' });
    // The close never finalizes.
    http.expectNone('/api/protocols/p-1');
    http.expectNone('/api/protocols/p-1/finalize');
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Sitzung schließen?' })).toBeNull(),
    );

    // The finalize is the next step on the closed meeting.
    await userEvent.click(await screen.findByRole('button', { name: 'Finalisieren & versenden' }));
    const saveReq = http.expectOne('/api/protocols/p-1');
    expect(saveReq.request.method).toBe('PATCH');
    // Top-level `#` without a "TOP n:" prefix, because the renderer numbers the TOPs itself.
    expect(saveReq.request.body.markdown).toContain('# Begrüßung');
    saveReq.flush(PROTOCOL);
    const finReq = http.expectOne('/api/protocols/p-1/finalize');
    expect(finReq.request.method).toBe('POST');
    finReq.flush({ ...PROTOCOL, status: 'final', pdfUrl: 'https://example/p.pdf' });

    expect(await screen.findByText('Final')).toBeInTheDocument();
  });

  it('offers separate internal + public PDF links when a redacted variant exists', async () => {
    // Non-public TOPs ⇒ the backend returns both URLs.
    const { http } = await setup();
    http.expectOne('/api/meetings/m-1').flush(MEETING);
    http.expectOne('/api/meetings/m-1/protocol').flush({
      ...PROTOCOL,
      status: 'final',
      pdfUrl: '/api/protocols/p-1/pdf',
      publicPdfUrl: '/api/protocols/p-1/pdf/public',
    });
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    flushDelegationContext(http);

    const internal = await screen.findByRole('link', { name: 'Internes Protokoll' });
    expect(internal).toHaveAttribute('href', '/api/protocols/p-1/pdf');
    const pub = await screen.findByRole('link', { name: 'Öffentliches Protokoll' });
    expect(pub).toHaveAttribute('href', '/api/protocols/p-1/pdf/public');
  });

  it('offers a single generic PDF link when nothing is redacted', async () => {
    // No non-public TOPs ⇒ only one PDF (publicPdfUrl null) for internal and public use.
    const { http } = await setup();
    http.expectOne('/api/meetings/m-1').flush(MEETING);
    http.expectOne('/api/meetings/m-1/protocol').flush({
      ...PROTOCOL,
      status: 'final',
      pdfUrl: '/api/protocols/p-1/pdf',
    });
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    flushDelegationContext(http);

    expect(await screen.findByRole('link', { name: 'PDF öffnen' })).toHaveAttribute(
      'href',
      '/api/protocols/p-1/pdf',
    );
    expect(screen.queryByRole('link', { name: 'Öffentliches Protokoll' })).toBeNull();
  });

  it('marks non-public TOPs with a NÖ badge once the meeting is closed and finalized', async () => {
    const { http, container } = await setup();
    http.expectOne('/api/meetings/m-1').flush({ ...MEETING, status: 'closed' });
    // Finalized ⇒ editor locked ⇒ the non-public checkbox is gone. The badge takes over.
    http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final' });
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([
      { id: 't-1', applicationId: null, title: 'Vertraulich', body: '', position: 0, nonPublic: true },
      { id: 't-2', applicationId: null, title: 'Öffentlich', body: '', position: 1, nonPublic: false },
    ]);
    flushDelegationContext(http);

    // Below the wide layout the agenda is a sheet from the start edge.
    await userEvent.click(await screen.findByTitle('Tagesordnung öffnen'));
    const agendaSheet = await screen.findByRole('dialog', { name: 'Tagesordnung' });
    await within(agendaSheet).findByText('Vertraulich');
    const noe = Array.from(agendaSheet.querySelectorAll('app-badge')).filter(
      (b) => b.textContent?.trim() === 'NÖ',
    );
    expect(noe).toHaveLength(1); // only the non-public TOP, not the public one
    // The locked protocol leaves no row menu.
    expect(within(agendaSheet).queryByRole('button', { name: /Aktionen für/ })).toBeNull();
    void container;
  });

  it('tags the non-public TOP while the meeting is still live', async () => {
    const { http, container } = await setup();
    http.expectOne('/api/meetings/m-1').flush(MEETING); // status 'live'
    http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([
      { id: 't-1', applicationId: null, title: 'Vertraulich', body: '', position: 0, nonPublic: true },
    ]);
    flushDelegationContext(http);

    await userEvent.click(await screen.findByTitle('Tagesordnung öffnen'));
    const agendaSheet = await screen.findByRole('dialog', { name: 'Tagesordnung' });
    await within(agendaSheet).findByText('Vertraulich');
    const noe = Array.from(container.querySelectorAll('app-badge')).filter(
      (b) => b.textContent?.trim() === 'NÖ',
    );
    expect(noe).toHaveLength(1);
  });

  it('hides the save-state indicator once the protocol is finalized', async () => {
    const { http, container } = await setup();
    http.expectOne('/api/meetings/m-1').flush({ ...MEETING, status: 'closed' });
    http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final' });
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    flushDelegationContext(http);

    await screen.findByText('Final');
    expect(container.querySelector('.mtg__saveState')).toBeNull();
  });

  it('retries a failed finalize via the toolbar repeat button', async () => {
    const { http } = await setup();
    // The meeting is closed and the protocol is back to draft ⇒ the render failed.
    http.expectOne('/api/meetings/m-1').flush({ ...MEETING, status: 'closed' });
    http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);

    await userEvent.click(
      await screen.findByRole('button', { name: 'Finalisieren & versenden' }),
    );
    // The finalize action first saves the assembled markdown, then posts to /finalize.
    http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
    const finReq = http.expectOne('/api/protocols/p-1/finalize');
    expect(finReq.request.method).toBe('POST');
    finReq.flush({ ...PROTOCOL, status: 'final', pdfUrl: 'https://example/p.pdf' });
    expect(await screen.findByText('Final')).toBeInTheDocument();
  });

  it('applies live vote_tally updates from the WebSocket', async () => {
    const { http, ws, fixture } = await setup();
    flushLoad(http);
    await screen.findByText('Antrag A');
    ws.subject.next({
      type: 'vote_tally',
      voteId: 'v-1',
      counts: { ja: 99, nein: 2 },
      eligible: 120,
      quorumMet: true,
      leading: 'ja',
    });
    fixture.detectChanges();
    expect(screen.getByText('99')).toBeInTheDocument();
  });

  it('reflects a live meeting_state status change', async () => {
    const { http, ws, fixture } = await setup();
    flushLoad(http);
    await screen.findByText('Sitzungssteuerung');
    ws.subject.next({ type: 'meeting_state', activeApplicationId: 'app-2', status: 'closed' });
    fixture.detectChanges();
    expect(screen.getByText('Geschlossen')).toBeInTheDocument();
  });

  it('shows an error notice when the meeting fails to load', async () => {
    const { http } = await setup();
    http.expectOne('/api/meetings/m-1').flush(
      { title: 'fail' },
      { status: 500, statusText: 'Server Error' },
    );
    expect(await screen.findByText(/konnte nicht geladen/i)).toBeInTheDocument();
  });

  it('offers no on-demand protocol button — the protocol is created on start', async () => {
    // The protocol is created only at meeting start. A manual "create protocol"
    // button no longer exists.
    const { http } = await setup();
    http.expectOne('/api/meetings/m-1').flush({ ...MEETING, protocolId: null });
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    expect(
      await screen.findByText('Für diese Sitzung gibt es noch kein Protokoll.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Protokoll anlegen' })).not.toBeInTheDocument();
  });

  it('persists the selected protokollant via PATCH and marks the row in the roster', async () => {
    const { http } = await setup();
    http.expectOne('/api/meetings/m-1').flush(MEETING);
    http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    http.expectOne('/api/meetings/m-1/attendance').flush([
      { principalId: 'pr-1', displayName: 'Max P', email: 'm@x.de', status: null, source: null, isSelf: false, canKeepProtocol: true },
    ]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    flushDelegationContext(http);
    await userEvent.click(await screen.findByRole('button', { name: 'Sitzungsmenü' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Sitzung bearbeiten' }));
    // openSettings reloads the roster (minute-taker options).
    http.expectOne('/api/meetings/m-1/attendance').flush([
      { principalId: 'pr-1', displayName: 'Max P', email: 'm@x.de', status: null, source: null, isSelf: false, canKeepProtocol: true },
    ]);
    // Match the exact label. The start button carries an aria-label
    // "Protokollant zuweisen …", which makes a /Protokollant/ regex ambiguous.
    const select = await screen.findByLabelText('Protokollführung');
    await screen.findByRole('option', { name: 'Max P' });
    await userEvent.selectOptions(select, 'pr-1');
    await userEvent.click(screen.getByRole('button', { name: /Speichern/i }));
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body.protokollantId).toBe('pr-1');
    req.flush({ ...MEETING, protokollantId: 'pr-1', protokollantName: 'Max P' });
    // The roster marks the minute-taker after saving.
    await userEvent.click(await screen.findByTitle('Anwesenheit'));
    const popover = await screen.findByRole('dialog', { name: 'Anwesenheit' });
    expect(within(popover).getByText(/Max P/)).toBeInTheDocument();
    expect(within(popover).getByText('Protokollführung')).toBeInTheDocument();
  });

  it('gives non-protokollants the live read/vote view once a protokollant is assigned', async () => {
    // The meeting has an assigned minute-taker, and it is someone else. The
    // logged-in user is NOT the minute-taker ⇒ live/voting view, not the manager view.
    const assigned: MeetingOutWire = {
      ...MEETING,
      canControl: false,
      canManage: false,
      canWrite: false,
      canManageVotes: false,
      canVote: true,
      protokollantId: 'someone-else',
      protokollantName: 'Other P',
    };
    const { http } = await setup({ perms: ['vote.cast'], userId: 'pr-1' });
    http.expectOne('/api/meetings/m-1').flush(assigned);
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    flushDelegationContext(http);
    expect(await screen.findByText('Live-Sitzung')).toBeInTheDocument();
    expect(screen.queryByText('Sitzungssteuerung')).not.toBeInTheDocument();
  });

  it('keeps the follow view for a member without rights and without a minute-taker', async () => {
    // The follow view is the view of a plain member. It must not depend on a
    // minute-taker being assigned: no write and no manage right is enough.
    const member: MeetingOutWire = {
      ...MEETING,
      canControl: false,
      canManage: false,
      canWrite: false,
      canManageVotes: false,
      canVote: true,
      protokollantId: null,
      protokollantName: null,
    };
    const { http } = await setup({ perms: ['vote.cast'], userId: 'pr-1' });
    http.expectOne('/api/meetings/m-1').flush(member);
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    flushDelegationContext(http);
    expect(await screen.findByText('Live-Sitzung')).toBeInTheDocument();
    expect(screen.queryByRole('toolbar', { name: 'Sitzungssteuerung' })).not.toBeInTheDocument();
  });

  describe('minute-taker exclusivity is about the protocol only', () => {
    /** Detail load with the minute-taker assigned to somebody else. */
    async function loadOtherProtokollant(over: Partial<MeetingOutWire> = {}) {
      const view = await setup();
      const { http } = view;
      http.expectOne('/api/meetings/m-1').flush({
        ...MEETING,
        status: 'planned',
        protokollantId: 'someone-else',
        protokollantName: 'Other P',
        ...over,
      });
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      http
        .expectOne('/api/meetings/m-1/agenda')
        .flush([
          { id: 't-1', applicationId: null, title: 'Begrüßung', body: '', position: 0, nonPublic: false },
        ]);
      flushDelegationContext(http);
      return view;
    }

    it('keeps the control toolbar for a manager who is not the minute-taker', async () => {
      // The operational bite: the minute-taker is reassigned in the settings
      // dialog, and that dialog opens from this toolbar. Hiding the toolbar from
      // everybody else strands the meeting when the minute-taker drops out.
      await loadOtherProtokollant();

      expect(await screen.findByRole('toolbar', { name: 'Sitzungssteuerung' })).toBeInTheDocument();
      // The start sits in the header and in the checklist while the meeting is planned.
      const starts = screen.getAllByRole('button', { name: 'Sitzung eröffnen' });
      expect(starts).toHaveLength(2);
      starts.forEach((b) => expect(b).toBeEnabled());
      // Settings and delete are in the session menu.
      await userEvent.click(screen.getByRole('button', { name: 'Sitzungsmenü' }));
      expect(await screen.findByRole('menuitem', { name: 'Sitzung bearbeiten' })).toBeInTheDocument();
      expect(screen.getByRole('menuitem', { name: 'Sitzung löschen' })).toBeInTheDocument();
      // The follow view must not take the page over.
      expect(screen.queryByText('Live-Sitzung')).not.toBeInTheDocument();
    });

    it('keeps the agenda editor and vote creation for a manager who is not the minute-taker', async () => {
      // A vote needs a started meeting, so the page offers it while live only. An open
      // vote on any item blocks a new one, so this meeting has none.
      await loadOtherProtokollant({ status: 'live', votes: [] });

      expect(await screen.findByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeInTheDocument();
      // Below the wide layout the agenda opens as a sheet.
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      expect(await screen.findByRole('button', { name: 'TOP hinzufügen' })).toBeInTheDocument();
    });

    it('shows the protocol pane read-only to a manager who is not the minute-taker', async () => {
      // Two people must not type into one protocol. That is what the exclusivity
      // was written for, so the editor is disabled — not the whole page hidden.
      const { container } = await loadOtherProtokollant({ status: 'live' });

      expect(await screen.findByText('Entwurf')).toBeInTheDocument();
      expect(container.querySelector('.mde__host--disabled')).toBeTruthy();
      // Say who holds the pen, so the greyed editor is not a mystery.
      expect(screen.getByText(/Other P führt das Protokoll/)).toBeInTheDocument();
    });

    it('lets the minute-taker edit the protocol', async () => {
      const { container } = await loadOtherProtokollant({
        status: 'live',
        protokollantId: 'pr-1',
        protokollantName: 'Ich',
        isProtokollant: true,
      });

      expect(await screen.findByText('Entwurf')).toBeInTheDocument();
      expect(container.querySelector('.mde__host--disabled')).toBeNull();
    });
  });
});

// Instance-driven tests: call the public methods directly and check signals and
// HTTP. They reach the branches that the DOM alone does not trigger: error paths,
// search debounce, drag and drop, WS messages and helpers.
type Cmp = MeetingsComponent;

const AGENDA_ITEM = (over: Record<string, unknown> = {}) => ({
  id: 't-1',
  applicationId: null,
  title: 'Begrüßung',
  body: '',
  position: 0,
  nonPublic: false,
  ...over,
});

/** The component-scoped services of the meeting page. */
function services(fixture: { debugElement: { injector: { get<T>(t: new (...a: never[]) => T): T } } }) {
  return {
    session: fixture.debugElement.injector.get(MeetingSessionService),
    agenda: fixture.debugElement.injector.get(MeetingAgendaService),
  };
}

/** Set up a loaded detail meeting and return the instance. */
async function loaded(opts: Parameters<typeof setup>[0] = {}) {
  const view = await setup(opts);
  view.http.expectOne('/api/meetings/m-1').flush(MEETING);
  view.http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
  view.http.expectOne('/api/meetings/m-1/attendance').flush([]);
  view.http.expectOne('/api/meetings/m-1/agenda').flush([]);
  flushDelegationContext(view.http);
  const cmp = view.fixture.componentInstance as Cmp;
  return { ...view, cmp };
}

describe('MeetingsComponent — methods', () => {
  describe('meeting dialogs', () => {
    it('adds an agenda item through the dialog and shows the new agenda', async () => {
      const { cmp, http, fixture } = await loaded();
      cmp.openAgendaDialog();
      fixture.detectChanges();
      expect(screen.getByRole('dialog', { name: 'TOP hinzufügen' })).toBeInTheDocument();
      http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
      fixture.detectChanges();
      await userEvent.click(screen.getByRole('radio', { name: 'Freitext-TOP' }));
      await userEvent.type(screen.getByLabelText(/Titel/), 'Verschiedenes');
      const submit = screen
        .getAllByRole('button', { name: 'TOP hinzufügen' })
        .find((b) => b.closest('.dialog__footer')) as HTMLElement;
      await userEvent.click(submit);
      http.expectOne('/api/meetings/m-1/agenda').flush([AGENDA_ITEM({ id: 't-9', title: 'Verschiedenes' })]);
      fixture.detectChanges();
      expect(cmp.agenda().map((a) => a.id)).toEqual(['t-9']);
      expect(screen.queryByRole('dialog', { name: 'TOP hinzufügen' })).toBeNull();
    });

    it('opens a vote for an agenda item and takes the new vote into the page', async () => {
      const { cmp, http, fixture } = await loaded();
      expect(cmp.voteTopNumber()).toBe(0);
      cmp.agenda.set([AGENDA_ITEM({ id: 't-1' }), AGENDA_ITEM({ id: 't-2', title: 'Bericht' })] as never);
      cmp.openVoteDialog(AGENDA_ITEM({ id: 't-2', title: 'Bericht' }) as never);
      fixture.detectChanges();
      expect(cmp.voteTopNumber()).toBe(2);
      const dialog = screen.getByRole('dialog', { name: 'Abstimmung öffnen' });
      expect(dialog).toHaveAccessibleDescription('TOP 2 · Bericht');
      const submit = within(dialog).getAllByRole('button', { name: 'Abstimmung öffnen' }).pop() as HTMLElement;
      await userEvent.click(submit);
      http.expectOne('/api/meetings/m-1/votes').flush({ ...MEETING, votes: [] });
      fixture.detectChanges();
      expect(cmp.meeting()?.votes).toEqual([]);
      expect(screen.queryByRole('dialog', { name: 'Abstimmung öffnen' })).toBeNull();
    });

    it('deletes the open meeting through the dialog and goes back to the list', async () => {
      const { cmp, http, fixture, navigate } = await loaded();
      cmp.askDeleteMeeting(cmp.meeting()!);
      fixture.detectChanges();
      const dialog = screen.getByRole('dialog', { name: 'Sitzung löschen' });
      await userEvent.click(within(dialog).getByRole('button', { name: 'Endgültig löschen' }));
      http.expectOne((r) => r.url === '/api/meetings/m-1' && r.method === 'DELETE').flush(null);
      expect(navigate).toHaveBeenCalledWith(['/meetings']);
    });

    it('saves the open text before it asks to close', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http, fixture } = await loaded();
        cmp.onTopBodyChange('t-1', 'Letzter Satz');
        cmp.askCloseMeeting();
        http.expectOne('/api/meetings/m-1/agenda/t-1').flush([AGENDA_ITEM({ body: 'Letzter Satz' })]);
        fixture.detectChanges();
        expect(screen.getByRole('dialog', { name: 'Sitzung schließen?' })).toBeInTheDocument();
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe('display helpers', () => {
    it('maps status to badge variants and i18n keys', async () => {
      const { cmp } = await loaded();
      expect(cmp.statusVariant('live')).toBe('success');
      expect(cmp.statusVariant('closed')).toBe('info');
      expect(cmp.statusVariant('planned')).toBe('info');
      expect(cmp.statusKey('live')).toBe('meetings.status.live');
    });

    it('maps vote status to badge variants and keys', async () => {
      const { cmp } = await loaded();
      expect(cmp.voteVariant('open')).toBe('success');
      expect(cmp.voteVariant('closed')).toBe('info');
      expect(cmp.voteVariant('cancelled')).toBe('danger');
      expect(cmp.voteVariant('draft')).toBe('warning');
      expect(cmp.voteStatusKey('open')).toBe('meetings.voteStatus.open');
    });

    it('maps vote results to keys and variants including the tie fallback', async () => {
      const { cmp } = await loaded();
      expect(cmp.voteResultKey('passed')).toBe('vote.result.passed');
      expect(cmp.voteResultKey(null)).toBe('vote.result.tie');
      expect(cmp.voteResultKey(undefined)).toBe('vote.result.tie');
      expect(cmp.voteResultVariant('passed')).toBe('success');
      expect(cmp.voteResultVariant('rejected')).toBe('danger');
      expect(cmp.voteResultVariant('tie')).toBe('info');
    });

    it('labels vote options, falling back to the raw key when unknown', async () => {
      const { cmp } = await loaded();
      expect(cmp.voteOptionLabel('yes')).not.toBe('yes'); // translated
      expect(cmp.voteOptionLabel('weird-option')).toBe('weird-option');
    });

    it('counts vote entries from the counts map', async () => {
      const { cmp } = await loaded();
      const entries = cmp.countEntries({
        id: 'v', applicationId: null, agendaItemId: null, title: null, question: null,
        options: [], status: 'closed', result: null, counts: { yes: 3, no: 1 }, leading: null,
        closesAt: null, voted: 4, present: 5, revealed: true, failedReason: null,
      });
      expect(entries).toEqual([{ key: 'yes', value: 3 }, { key: 'no', value: 1 }]);
      const none = cmp.countEntries({
        id: 'v', applicationId: null, agendaItemId: null, title: null, question: null,
        options: [], status: 'closed', result: null, counts: null, leading: null,
        closesAt: null, voted: 0, present: 0, revealed: true, failedReason: null,
      });
      expect(none).toEqual([]);
    });

    it('computes vote options for a vote, falling back to count keys', async () => {
      const { cmp } = await loaded();
      const withOpts = cmp.voteOptionsFor({
        id: 'v', applicationId: null, agendaItemId: null, title: null, question: null,
        options: ['yes', 'no'], status: 'open', result: null, counts: null, leading: null,
        closesAt: null, voted: 0, present: 0, revealed: true, failedReason: null,
      });
      expect(withOpts).toEqual(['yes', 'no']);
      const fromCounts = cmp.voteOptionsFor({
        id: 'v', applicationId: null, agendaItemId: null, title: null, question: null,
        options: [], status: 'open', result: null, counts: { a: 1, b: 2 }, leading: null,
        closesAt: null, voted: 0, present: 0, revealed: true, failedReason: null,
      });
      expect(fromCounts).toEqual(['a', 'b']);
      // Neither options nor counts → empty list (covers the ?? {} fallback).
      const empty = cmp.voteOptionsFor({
        id: 'v', applicationId: null, agendaItemId: null, title: null, question: null,
        options: [], status: 'open', result: null, counts: null, leading: null,
        closesAt: null, voted: 0, present: 0, revealed: true, failedReason: null,
      });
      expect(empty).toEqual([]);
    });

    it('groups votes by TOP and collects loose votes', async () => {
      const { cmp, fixture } = await loaded();
      const { session } = services(fixture);
      expect(session.votesForTop('app-1')).toEqual([]); // votesForTop matches agendaItemId
      // The MEETING votes have no agendaItemId, so all of them are "loose".
      expect(cmp.looseVotes().length).toBe(2);
      // Bind a vote to a TOP → votesForTop matches, looseVotes shrinks.
      cmp.meeting.set({
        ...cmp.meeting()!,
        votes: [
          { ...cmp.meeting()!.votes[0], id: 'bound', agendaItemId: 't-7' },
          { ...cmp.meeting()!.votes[1], id: 'loose', agendaItemId: null },
        ],
      });
      expect(session.votesForTop('t-7').map((v) => v.id)).toEqual(['bound']);
      expect(cmp.looseVotes().map((v) => v.id)).toEqual(['loose']);
    });

    it('selects the beamer vote: open first, else last closed, else null', async () => {
      const { cmp } = await loaded();
      // The MEETING fixture has one open vote (v-1).
      expect(cmp.beamerVote()?.id).toBe('v-1');
      // No open votes → last closed one.
      cmp.meeting.set({
        ...cmp.meeting()!,
        votes: [
          { ...cmp.meeting()!.votes[0], id: 'c1', status: 'closed' },
          { ...cmp.meeting()!.votes[0], id: 'c2', status: 'closed' },
        ],
      });
      expect(cmp.beamerVote()?.id).toBe('c2');
      // Neither open nor closed → null.
      cmp.meeting.set({
        ...cmp.meeting()!,
        votes: [{ ...cmp.meeting()!.votes[0], id: 'p', status: 'draft' }],
      });
      expect(cmp.beamerVote()).toBeNull();
    });

  });

  describe('agenda + TOP editing', () => {
    it('selects a TOP and tracks the selected index', async () => {
      const { cmp, fixture } = await loaded();
      cmp.agenda.set([AGENDA_ITEM(), AGENDA_ITEM({ id: 't-2', position: 1 })] as never);
      cmp.selectTop('t-2');
      fixture.detectChanges();
      expect(cmp.selectedTopId()).toBe('t-2');
      expect(cmp.selectedTop()?.id).toBe('t-2');
      expect(cmp.selectedIndex()).toBe(1);
    });

    it('debounce-saves a TOP body and reflects the save state', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http, fixture } = await loaded();
        cmp.onTopBodyChange('t-1', 'Neuer Text');
        expect(cmp.saveState()).toBe('idle');
        // A second call before it fires resets the timer (covers the clearTimeout branch).
        cmp.onTopBodyChange('t-1', 'Neuer Text 2');
        jest.advanceTimersByTime(1000);
        expect(cmp.saveState()).toBe('saving');
        const req = http.expectOne('/api/meetings/m-1/agenda/t-1');
        expect(req.request.method).toBe('PATCH');
        expect(req.request.body).toEqual({ body: 'Neuer Text 2' });
        req.flush([AGENDA_ITEM({ body: 'Neuer Text 2' })]);
        expect(cmp.saveState()).toBe('saved');
        expect(services(fixture).agenda.savingTop()).toBe(false);
      } finally {
        jest.useRealTimers();
      }
    });

    it('sets the error save state when the body save fails', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http, fixture } = await loaded();
        cmp.onTopBodyChange('t-1', 'X');
        jest.advanceTimersByTime(1000);
        http.expectOne('/api/meetings/m-1/agenda/t-1').flush(null, { status: 500, statusText: 'e' });
        expect(cmp.saveState()).toBe('error');
        expect(services(fixture).agenda.savingTop()).toBe(false);
      } finally {
        jest.useRealTimers();
      }
    });

    it('does nothing on body change without a loaded meeting', async () => {
      const { fixture } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      cmp.onTopBodyChange('t-1', 'X'); // meeting() === null → early return
      expect(cmp.saveState()).toBe('idle');
    });

    it('removes a TOP from the agenda', async () => {
      const { cmp, http } = await loaded();
      cmp.removeFromAgenda('t-1');
      http.expectOne('/api/meetings/m-1/agenda/t-1').flush([]);
      expect(cmp.savingAgenda()).toBe(false);
    });

    it('ignores removeFromAgenda while saving and handles its error', async () => {
      const { cmp, http } = await loaded();
      cmp.savingAgenda.set(true);
      cmp.removeFromAgenda('t-1'); // savingAgenda → return
      cmp.savingAgenda.set(false);
      cmp.removeFromAgenda('t-1');
      http.expectOne('/api/meetings/m-1/agenda/t-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.savingAgenda()).toBe(false);
    });

    it('marks a TOP non-public', async () => {
      const { cmp, http } = await loaded();
      cmp.setNonPublic(AGENDA_ITEM() as never, true);
      const req = http.expectOne('/api/meetings/m-1/agenda/t-1');
      expect(req.request.body).toEqual({ nonPublic: true });
      req.flush([AGENDA_ITEM({ nonPublic: true })]);
      expect(cmp.savingAgenda()).toBe(false);
    });

    it('handles a setNonPublic error', async () => {
      const { cmp, http } = await loaded();
      cmp.setNonPublic(AGENDA_ITEM() as never, true);
      http.expectOne('/api/meetings/m-1/agenda/t-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.savingAgenda()).toBe(false);
    });

    it('does nothing on agenda actions without a loaded meeting', async () => {
      const { fixture } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      cmp.removeFromAgenda('t-1');
      cmp.setNonPublic(AGENDA_ITEM() as never, true);
      expect(cmp.savingAgenda()).toBe(false);
    });
  });

  describe('inline rename of a freetext TOP', () => {
    it('starts and cancels renaming', async () => {
      const { cmp } = await loaded();
      cmp.startRename(AGENDA_ITEM({ title: 'Alt' }) as never);
      expect(cmp.renamingTopId()).toBe('t-1');
      expect(cmp.renameDraft()).toBe('Alt');
      cmp.cancelRename();
      expect(cmp.renamingTopId()).toBeNull();
      expect(cmp.renameDraft()).toBe('');
    });

    it('does not start renaming an application TOP', async () => {
      const { cmp } = await loaded();
      cmp.startRename(AGENDA_ITEM({ applicationId: 'app-1' }) as never);
      expect(cmp.renamingTopId()).toBeNull();
    });

    it('saves a changed freetext title', async () => {
      const { cmp, http } = await loaded();
      cmp.startRename(AGENDA_ITEM({ title: 'Alt' }) as never);
      cmp.renameDraft.set('Neu');
      cmp.renameTop(AGENDA_ITEM({ title: 'Alt' }) as never);
      const req = http.expectOne('/api/meetings/m-1/agenda/t-1');
      expect(req.request.body).toEqual({ title: 'Neu' });
      req.flush([AGENDA_ITEM({ title: 'Neu' })]);
      expect(cmp.savingAgenda()).toBe(false);
      expect(cmp.renameDraft()).toBe('');
    });

    it('ignores renameTop when the active id changed (stale blur)', async () => {
      const { cmp, http } = await loaded();
      cmp.renamingTopId.set('other');
      cmp.renameTop(AGENDA_ITEM() as never);
      http.verify();
    });

    it('just closes the editor when the title is empty or unchanged', async () => {
      const { cmp, http } = await loaded();
      cmp.startRename(AGENDA_ITEM({ title: 'Alt' }) as never);
      cmp.renameDraft.set('   ');
      cmp.renameTop(AGENDA_ITEM({ title: 'Alt' }) as never); // empty → cancel
      expect(cmp.renamingTopId()).toBeNull();
      cmp.startRename(AGENDA_ITEM({ title: 'Alt' }) as never);
      cmp.renameDraft.set('Alt');
      cmp.renameTop(AGENDA_ITEM({ title: 'Alt' }) as never); // unchanged → cancel
      expect(cmp.renamingTopId()).toBeNull();
      http.verify();
    });

    it('handles a rename error', async () => {
      const { cmp, http } = await loaded();
      cmp.startRename(AGENDA_ITEM({ title: 'Alt' }) as never);
      cmp.renameDraft.set('Neu');
      cmp.renameTop(AGENDA_ITEM({ title: 'Alt' }) as never);
      http.expectOne('/api/meetings/m-1/agenda/t-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.savingAgenda()).toBe(false);
    });
  });

  describe('drag & drop reorder', () => {
    it('reorders TOPs and persists via PUT', async () => {
      const { cmp, http } = await loaded();
      cmp.agenda.set([
        AGENDA_ITEM({ id: 't-1' }),
        AGENDA_ITEM({ id: 't-2', position: 1 }),
        AGENDA_ITEM({ id: 't-3', position: 2 }),
      ] as never);
      cmp.onTopDragStart(0);
      cmp.onTopDrop(2); // t-1 to the end
      expect(cmp.agenda().map((a) => a.id)).toEqual(['t-2', 't-3', 't-1']);
      const req = http.expectOne('/api/meetings/m-1/agenda/order');
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({ itemIds: ['t-2', 't-3', 't-1'] });
      req.flush([AGENDA_ITEM({ id: 't-2' })]);
      expect(cmp.agenda().map((a) => a.id)).toEqual(['t-2']);
    });

    it('reloads the agenda when the reorder fails', async () => {
      const { cmp, http } = await loaded();
      cmp.agenda.set([AGENDA_ITEM({ id: 't-1' }), AGENDA_ITEM({ id: 't-2' })] as never);
      cmp.onTopDragStart(0);
      cmp.onTopDrop(1);
      http.expectOne('/api/meetings/m-1/agenda/order').flush(null, { status: 500, statusText: 'e' });
      http.expectOne('/api/meetings/m-1/agenda').flush([AGENDA_ITEM()]);
    });

    it('ignores a drop onto the same index or without a drag source', async () => {
      const { cmp, http } = await loaded();
      cmp.agenda.set([AGENDA_ITEM({ id: 't-1' })] as never);
      cmp.onTopDrop(0); // dragTopIndex null → return
      cmp.onTopDragStart(0);
      cmp.onTopDrop(0); // from === index → return
      http.verify();
    });

    it('moves a TOP up and down from the row menu', async () => {
      const { cmp, http } = await loaded();
      cmp.agenda.set([
        AGENDA_ITEM({ id: 't-1' }),
        AGENDA_ITEM({ id: 't-2', position: 1 }),
      ] as never);
      cmp.moveTop(1, 0);
      const req = http.expectOne('/api/meetings/m-1/agenda/order');
      expect(req.request.body).toEqual({ itemIds: ['t-2', 't-1'] });
      req.flush([AGENDA_ITEM({ id: 't-2' }), AGENDA_ITEM({ id: 't-1', position: 1 })]);
      // Out of range, onto itself or without a meeting: nothing to save.
      cmp.moveTop(1, 2);
      cmp.moveTop(0, -1);
      cmp.moveTop(1, 1);
      cmp.moveTop(5, 0);
      cmp.meeting.set(null);
      cmp.moveTop(1, 0);
      http.verify();
    });

    it('preventDefault only while dragging', async () => {
      const { cmp } = await loaded();
      const prevent = jest.fn();
      cmp.onTopDragOver({ preventDefault: prevent } as unknown as DragEvent);
      expect(prevent).not.toHaveBeenCalled();
      cmp.onTopDragStart(0);
      cmp.onTopDragOver({ preventDefault: prevent } as unknown as DragEvent);
      expect(prevent).toHaveBeenCalled();
    });
  });

  describe('attendance', () => {
    const SELF = { principalId: 'pr-1', displayName: 'Me', email: null, status: null, source: null, note: null, isSelf: true };
    const OTHER = { principalId: 'pr-2', displayName: 'X', email: null, status: 'absent', source: null, note: null, isSelf: false };

    /** A member without the lead rights of the meeting. */
    async function asMember() {
      const view = await loaded();
      view.cmp.meeting.set({ ...view.cmp.meeting()!, canControl: false, canWrite: false });
      return view;
    }

    it('reports the own attendance via the me-endpoint (member)', async () => {
      const { cmp, http } = await asMember();
      cmp.setAttendance(SELF as never, 'excused', 'Krank');
      const req = http.expectOne('/api/meetings/m-1/attendance/me');
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({ status: 'excused', note: 'Krank' });
      req.flush([]);
      expect(cmp.savingAttendance()).toBe(false);
    });

    it('never sends absent, another row or a lead record as a member (Z2, O15)', async () => {
      const { cmp, http } = await asMember();
      cmp.setAttendance(SELF as never, 'absent');
      cmp.setAttendance(OTHER as never, 'present');
      cmp.setAttendance({ ...SELF, status: 'absent', source: 'lead' } as never, 'present');
      http.verify();
    });

    it('sets any row via the principal endpoint as the lead, the own row too', async () => {
      const { cmp, http } = await loaded();
      cmp.setAttendance(OTHER as never, 'present');
      const req = http.expectOne('/api/meetings/m-1/attendance/pr-2');
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({ status: 'present' });
      req.flush([]);
      cmp.setAttendance(SELF as never, 'absent');
      http.expectOne('/api/meetings/m-1/attendance/pr-1').flush([]);
      expect(cmp.savingAttendance()).toBe(false);
    });

    it('saves a changed reason with the same status', async () => {
      const { cmp, http } = await loaded();
      const excused = { ...OTHER, status: 'excused', note: 'Alt' };
      cmp.setAttendance(excused as never, 'excused', 'Alt'); // unchanged → return
      http.verify();
      cmp.setAttendance(excused as never, 'excused', 'Neu');
      const req = http.expectOne('/api/meetings/m-1/attendance/pr-2');
      expect(req.request.body).toEqual({ status: 'excused', note: 'Neu' });
      req.flush([]);
    });

    it('skips when the status is unchanged or already saving', async () => {
      const { cmp, http } = await loaded();
      cmp.setAttendance({ ...OTHER, status: 'present' } as never, 'present'); // unchanged → return
      cmp.savingAttendance.set(true);
      cmp.setAttendance(OTHER as never, 'present');
      cmp.resetAttendance(OTHER as never);
      http.verify();
    });

    it('handles an attendance error with the server reason', async () => {
      const { cmp, http, fixture } = await asMember();
      const toast = fixture.debugElement.injector.get(ToastService);
      const spy = jest.spyOn(toast, 'error');
      cmp.setAttendance(SELF as never, 'present');
      http
        .expectOne('/api/meetings/m-1/attendance/me')
        .flush({ detail: 'kaputt' }, { status: 500, statusText: 'e' });
      expect(cmp.savingAttendance()).toBe(false);
      expect(spy).toHaveBeenCalledWith('Aktion fehlgeschlagen.: kaputt');
      cmp.setAttendance(SELF as never, 'present');
      http.expectOne('/api/meetings/m-1/attendance/me').flush(null, { status: 500, statusText: 'e' });
      expect(spy).toHaveBeenLastCalledWith('Aktion fehlgeschlagen.');
    });

    it('explains an active delegation (O23) and reloads the roster', async () => {
      const { cmp, http, fixture } = await loaded();
      const spy = jest.spyOn(fixture.debugElement.injector.get(ToastService), 'error');
      cmp.setAttendance(OTHER as never, 'present');
      http
        .expectOne('/api/meetings/m-1/attendance/pr-2')
        .flush({ code: 'delegation_active' }, { status: 409, statusText: 'Conflict' });
      expect(spy).toHaveBeenCalledWith(expect.stringContaining('Vertretung'));
      http.expectOne('/api/meetings/m-1/attendance').flush([OTHER]);
      expect(cmp.attendance()).toEqual([OTHER]);
    });

    it('explains the own delegation (O23) to a member and reloads the roster', async () => {
      const { cmp, http, fixture } = await asMember();
      const spy = jest.spyOn(fixture.debugElement.injector.get(ToastService), 'error');
      cmp.setAttendance(SELF as never, 'present');
      http
        .expectOne('/api/meetings/m-1/attendance/me')
        .flush({ code: 'delegation_active' }, { status: 409, statusText: 'Conflict' });
      expect(spy).toHaveBeenCalledWith(expect.stringContaining('Du hast für diese Sitzung eine Vertretung'));
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
    });

    it('explains a record that the lead set (O15) and reloads the roster', async () => {
      const { cmp, http, fixture } = await asMember();
      const spy = jest.spyOn(fixture.debugElement.injector.get(ToastService), 'error');
      cmp.setAttendance(SELF as never, 'present');
      http
        .expectOne('/api/meetings/m-1/attendance/me')
        .flush({ code: 'attendance_set_by_lead' }, { status: 409, statusText: 'Conflict' });
      expect(spy).toHaveBeenCalledWith(expect.stringContaining('Sitzungsleitung'));
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
    });

    it('resets a member to open as the lead', async () => {
      const { cmp, http } = await loaded();
      cmp.resetAttendance(OTHER as never);
      const req = http.expectOne('/api/meetings/m-1/attendance/pr-2');
      expect(req.request.method).toBe('DELETE');
      req.flush([{ ...OTHER, status: null }]);
      expect(cmp.attendance()[0].status).toBeNull();
    });

    it('does not reset an open row or as a member', async () => {
      const { cmp, http } = await loaded();
      cmp.resetAttendance({ ...OTHER, status: null } as never);
      cmp.meeting.set({ ...cmp.meeting()!, canControl: false });
      cmp.resetAttendance(OTHER as never);
      http.verify();
    });
  });

  describe('session control', () => {
    it('starts the session (status live) when a protokollant is set', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'planned', protokollantId: 'pr-9' });
      cmp.startMeeting();
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual({ status: 'live' });
      req.flush({ ...MEETING, status: 'live', protocolId: 'p-1' });
      // canWrite + protocolId → reload via refreshProtocol.
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    });

    it('refuses to start without a protokollant', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'planned', protokollantId: null });
      cmp.startMeeting();
      http.verify(); // no PATCH
    });

    it('reports an error on a failed status change and reloads the meeting', async () => {
      const { cmp, http, fixture } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'planned', protokollantId: 'pr-9' });
      cmp.startMeeting();
      http
        .expectOne('/api/meetings/m-1')
        .flush(
          { detail: 'a meeting cannot change from closed to live', code: 'invalid_status_transition' },
          { status: 409, statusText: 'Conflict' },
        );
      const toasts = fixture.debugElement.injector.get(ToastService).toasts();
      expect(toasts.map((t) => t.message)).toContain(
        'Aktion fehlgeschlagen.: a meeting cannot change from closed to live',
      );
      http.expectOne('/api/meetings/m-1').flush({ ...MEETING, status: 'closed' });
      expect(cmp.meeting()!.status).toBe('closed');
    });

    it('sets the active application', async () => {
      const { cmp, http } = await loaded();
      cmp.setActive('app-7');
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual({ activeApplicationId: 'app-7' });
      req.flush({ ...MEETING, activeApplicationId: 'app-7' });
      expect(cmp.meeting()?.activeApplicationId).toBe('app-7');
    });

    it('handles a setActive error', async () => {
      const { cmp, http } = await loaded();
      cmp.setActive('app-7');
      http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.meeting()?.activeApplicationId).toBe('app-1'); // unchanged
    });

    it('does nothing on setActive without a meeting', async () => {
      const { fixture } = await setup({ id: null });
      (fixture.componentInstance as Cmp).setActive('x');
      expect((fixture.componentInstance as Cmp).meeting()).toBeNull();
    });

  });

  describe('votes', () => {
    it('opens a vote and patches its status', async () => {
      const { cmp, http } = await loaded();
      cmp.openVote('v-2');
      http.expectOne('/api/votes/v-2/open').flush(null, { status: 204, statusText: 'No Content' });
      expect(cmp.meeting()?.votes.find((v) => v.id === 'v-2')?.status).toBe('open');
    });

    const closedBody = (over: Record<string, unknown> = {}) => ({
      id: 'v-1',
      applicationId: 'app-1',
      result: 'passed',
      tally: { counts: { yes: 1 }, eligible: 3, quorumMet: true, leading: 'yes' },
      branchFired: true,
      ...over,
    });

    it('closes a vote and patches its status', async () => {
      const { cmp, http, fixture } = await loaded();
      cmp.closeVote('v-1');
      http.expectOne('/api/votes/v-1/close').flush(closedBody());
      expect(cmp.meeting()?.votes.find((v) => v.id === 'v-1')?.status).toBe('closed');
      const toasts = fixture.debugElement.injector.get(ToastService).toasts();
      expect(toasts.some((t) => t.variant === 'warning')).toBe(false);
    });

    it('warns when the close could not fire the result branch', async () => {
      const { cmp, http, fixture } = await loaded();
      cmp.closeVote('v-1');
      http.expectOne('/api/votes/v-1/close').flush(closedBody({ branchFired: false }));
      expect(cmp.meeting()?.votes.find((v) => v.id === 'v-1')?.status).toBe('closed');
      const toasts = fixture.debugElement.injector.get(ToastService).toasts();
      expect(toasts).toContainEqual(
        expect.objectContaining({
          variant: 'warning',
          message:
            'Abstimmung geschlossen. Der Folgeschritt des Antrags ist blockiert. Der Antrag bleibt im Abstimmungszustand. Bitte am Antrag „Status setzen“ verwenden.',
        }),
      );
    });

    it('does not warn for a generic motion without an application', async () => {
      const { cmp, http, fixture } = await loaded();
      cmp.closeVote('v-1');
      http
        .expectOne('/api/votes/v-1/close')
        .flush(closedBody({ applicationId: null, branchFired: false }));
      const toasts = fixture.debugElement.injector.get(ToastService).toasts();
      expect(toasts.some((t) => t.variant === 'warning')).toBe(false);
    });

    it('cancels a vote and patches its status', async () => {
      const { cmp, http } = await loaded();
      cmp.cancelVote('v-1');
      http.expectOne('/api/votes/v-1/cancel').flush(null, { status: 204, statusText: 'No Content' });
      expect(cmp.meeting()?.votes.find((v) => v.id === 'v-1')?.status).toBe('cancelled');
    });

    it('shows the server detail and reloads the meeting on a vote action error', async () => {
      const { cmp, http } = await loaded();
      cmp.openVote('v-2');
      http
        .expectOne('/api/votes/v-2/open')
        .flush({ detail: 'Antrag nicht im vote-State' }, { status: 409, statusText: 'Conflict' });
      // voteActionFailed reloads the meeting.
      http.expectOne('/api/meetings/m-1').flush({ ...MEETING, status: 'live' });
    });

    it('falls back to a generic message when the vote error has no detail', async () => {
      const { cmp, http } = await loaded();
      cmp.closeVote('v-1');
      http.expectOne('/api/votes/v-1/close').flush(null, { status: 500, statusText: 'e' });
      http.expectOne('/api/meetings/m-1').flush(MEETING);
    });

    it('swallows a meeting-reload error after a vote action failure', async () => {
      const { cmp, http } = await loaded();
      cmp.cancelVote('v-1');
      http.expectOne('/api/votes/v-1/cancel').flush(null, { status: 500, statusText: 'e' });
      http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'e' });
    });

    it('decides whether a TOP may get another vote', async () => {
      const { cmp, fixture } = await loaded();
      const { session } = services(fixture);
      // A free-text TOP always allows another vote.
      expect(session.canAddVote(AGENDA_ITEM({ applicationId: null }) as never)).toBe(true);
      // An application TOP without a vote (votesForTop matches agendaItemId) allows one.
      expect(session.canAddVote(AGENDA_ITEM({ id: 't-x', applicationId: 'app-1' }) as never)).toBe(true);
      // An application TOP with a bound vote is locked.
      cmp.meeting.set({
        ...cmp.meeting()!,
        votes: [{ ...cmp.meeting()!.votes[0], agendaItemId: 't-x' }],
      });
      expect(session.canAddVote(AGENDA_ITEM({ id: 't-x', applicationId: 'app-1' }) as never)).toBe(false);
    });

    it('casts a ballot and records the local choice', async () => {
      const { cmp, http } = await loaded();
      cmp.cast('v-1', 'yes');
      http.expectOne('/api/votes/v-1/ballot').flush(null, { status: 204, statusText: 'No Content' });
      expect(cmp.myChoice('v-1')).toBe('yes');
      expect(cmp.myChoice('v-2')).toBeNull();
      expect(cmp.casting()).toBeNull();
    });

    it('ignores a second cast while one is in flight', async () => {
      const { cmp, http } = await loaded();
      cmp.casting.set('v-1');
      cmp.cast('v-1', 'yes'); // casting → return
      http.verify();
    });

    it('handles a cast error via voteActionFailed', async () => {
      const { cmp, http } = await loaded();
      cmp.cast('v-1', 'yes');
      http.expectOne('/api/votes/v-1/ballot').flush(null, { status: 500, statusText: 'e' });
      http.expectOne('/api/meetings/m-1').flush(MEETING);
      expect(cmp.casting()).toBeNull();
    });

    it('deletes a vote', async () => {
      const { cmp, http } = await loaded();
      cmp.deleteVote('v-1');
      const req = http.expectOne('/api/meetings/m-1/votes/v-1');
      expect(req.request.method).toBe('DELETE');
      req.flush({ ...MEETING, votes: [] });
      expect(cmp.deletingVote()).toBeNull();
      expect(cmp.meeting()?.votes.length).toBe(0);
    });

    it('ignores deleteVote without a meeting or while deleting, and handles errors', async () => {
      const { cmp, http } = await loaded();
      cmp.deletingVote.set('v-1');
      cmp.deleteVote('v-1'); // deletingVote → return
      cmp.deletingVote.set(null);
      cmp.deleteVote('v-1');
      http
        .expectOne('/api/meetings/m-1/votes/v-1')
        .flush(
          { detail: 'the meeting is closed', code: 'meeting_closed' },
          { status: 409, statusText: 'Conflict' },
        );
      expect(cmp.deletingVote()).toBeNull();
      // The refusal reloads the meeting, which may have closed in another tab.
      http.expectOne('/api/meetings/m-1').flush({ ...MEETING, status: 'closed' });
      expect(cmp.meeting()!.status).toBe('closed');
    });
  });

  describe('finalize', () => {
    it('assembles markdown with application refs + bodies and finalizes (async path)', async () => {
      const { cmp, http } = await loaded();
      cmp.agenda.set([
        AGENDA_ITEM({ id: 't-1', applicationId: 'app-1', title: 'Antrag', body: 'Text' }),
        AGENDA_ITEM({ id: 't-2', applicationId: null, title: '', body: '' }),
      ] as never);
      cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' }); // F8: finalize after the close
      cmp.finalize();
      const saveReq = http.expectOne('/api/protocols/p-1');
      expect(saveReq.request.body.markdown).toContain('# Antrag');
      expect(saveReq.request.body.markdown).toContain(':::antrag{#app-1}');
      expect(saveReq.request.body.markdown).toContain('Tagesordnungspunkt'); // empty title fallback
      saveReq.flush(PROTOCOL);
      // Async path: finalize returns rendering, so the poll loop starts.
      jest.useFakeTimers();
      try {
        http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
        expect(cmp.finalizing()).toBe(false);
        // watchRendering polls again after 4s.
        jest.advanceTimersByTime(4000);
        http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
      } finally {
        jest.useRealTimers();
      }
    });

    it('reports a save error before finalize', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' }); // F8: finalize after the close
      cmp.finalize();
      http.expectOne('/api/protocols/p-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.finalizing()).toBe(false);
    });

    it('reports a finalize error with the server detail', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' }); // F8: finalize after the close
      cmp.finalize();
      http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
      http
        .expectOne('/api/protocols/p-1/finalize')
        .flush({ detail: 'LaTeX-Fehler' }, { status: 400, statusText: 'Bad Request' });
      expect(cmp.finalizing()).toBe(false);
    });

    it('reports a finalize error without a detail', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' }); // F8: finalize after the close
      cmp.finalize();
      http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
      http.expectOne('/api/protocols/p-1/finalize').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.finalizing()).toBe(false);
    });

    it('ignores finalize without a protocol / when locked / while saving a TOP', async () => {
      const { cmp, http, fixture } = await loaded();
      const { agenda } = services(fixture);
      cmp.protocol.set(null);
      cmp.finalize(); // no protocol → return
      cmp.protocol.set({ ...PROTOCOL, isFinal: false, isLocked: true } as never);
      cmp.finalize(); // isLocked → return
      cmp.protocol.set({ ...PROTOCOL, isFinal: false, isLocked: false } as never);
      agenda.savingTop.set(true);
      cmp.finalize(); // savingTop → return
      agenda.savingTop.set(false);
      cmp.finalize(); // F8: the meeting is still live → return
      http.verify();
    });
  });

  describe('settings dialog', () => {
    it('names the protokollant from the session page in one PATCH', async () => {
      const { cmp, http } = await loaded();
      cmp.setProtokollant(cmp.meeting()!, 'pr-9');
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.method).toBe('PATCH');
      // Only the protokollant: the date and the time stay with the settings dialog.
      expect(req.request.body).toEqual({ protokollantId: 'pr-9' });
      req.flush({ ...MEETING, protokollantId: 'pr-9', protokollantName: 'Neu' });
      expect(cmp.meeting()!.protokollantId).toBe('pr-9');
    });

    it('keeps the meeting when naming the protokollant fails', async () => {
      const { cmp, http } = await loaded();
      const before = cmp.meeting()!.protokollantId;
      cmp.setProtokollant(cmp.meeting()!, 'pr-9');
      http.expectOne('/api/meetings/m-1').flush(null, { status: 409, statusText: 'e' });
      expect(cmp.meeting()!.protokollantId).toBe(before);
    });

    it('hands the minutes over now and plans the next-item handover (Z3)', async () => {
      const { cmp, http, fixture } = await loaded();
      const toast = fixture.debugElement.injector.get(ToastService);
      const success = jest.spyOn(toast, 'success');
      cmp.handOver(cmp.meeting()!, 'pr-9', 'now');
      const now = http.expectOne('/api/meetings/m-1/protokollant-handover');
      expect(now.request.method).toBe('POST');
      expect(now.request.body).toEqual({ principalId: 'pr-9', mode: 'now' });
      now.flush({ ...MEETING, protokollantId: 'pr-9', protokollantName: 'Neu' });
      expect(cmp.meeting()!.protokollantId).toBe('pr-9');
      expect(success).toHaveBeenLastCalledWith('Protokollführung übergeben.');
      cmp.handOver(cmp.meeting()!, 'pr-2', 'next_item');
      const plan = {
        principalId: 'pr-2',
        name: 'B',
        fromAt: null,
        toAt: null,
        fromAgendaItemId: null,
        toAgendaItemId: null,
        fromPosition: null,
        toPosition: null,
      };
      http
        .expectOne('/api/meetings/m-1/protokollant-handover')
        .flush({ ...MEETING, protokollantId: 'pr-9', plannedHandover: plan });
      expect(cmp.meeting()!.plannedHandover?.principalId).toBe('pr-2');
      expect(success).toHaveBeenLastCalledWith('Übergabe mit dem nächsten TOP geplant.');
    });

    it('reads the meeting again on meeting_state, so a handover reaches the new keeper (Z3)', async () => {
      // Viewer B: a member with protocol.write in the gremium, not the keeper yet.
      const { http, ws, fixture } = await setup({ perms: ['protocol.write'] });
      const cmp = fixture.componentInstance as Cmp;
      http.expectOne('/api/meetings/m-1').flush({
        ...MEETING,
        canManage: false,
        canWrite: false,
        canManageVotes: false,
        canFinalize: false,
        isProtokollant: false,
        protokollantId: 'pr-a',
        protokollantName: 'A',
      });
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      flushDelegationContext(http);
      http.expectNone('/api/meetings/m-1/protocol'); // no write right yet
      expect(cmp.canWrite()).toBe(false);

      // A hands the minutes over to B. The event carries no rights.
      ws.subject.next({ type: 'meeting_state', activeApplicationId: 'app-1', status: 'live' });
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      const plan = {
        principalId: 'pr-c',
        name: 'C',
        fromAt: null,
        toAt: null,
        fromAgendaItemId: null,
        toAgendaItemId: null,
        fromPosition: null,
        toPosition: null,
      };
      http.expectOne('/api/meetings/m-1').flush({
        ...MEETING,
        canManage: false,
        canWrite: true,
        canManageVotes: true,
        canFinalize: false,
        isProtokollant: true,
        protokollantId: 'pr-1',
        protokollantName: 'B',
        plannedHandover: plan,
      });
      expect(cmp.canWrite()).toBe(true);
      expect(cmp.meeting()!.canManageVotes).toBe(true);
      expect(cmp.meeting()!.isProtokollant).toBe(true);
      expect(cmp.meeting()!.protokollantName).toBe('B');
      expect(cmp.meeting()!.plannedHandover?.principalId).toBe('pr-c');
      // B can write now, so the editor loads the protocol.
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      expect(cmp.protocol()?.id).toBe('p-1');
    });

    it('reports a refused handover', async () => {
      const { cmp, http, fixture } = await loaded();
      const error = jest.spyOn(fixture.debugElement.injector.get(ToastService), 'error');
      cmp.handOver(cmp.meeting()!, 'pr-9', 'now');
      http
        .expectOne('/api/meetings/m-1/protokollant-handover')
        .flush(
          { detail: 'x', code: 'protokollant_needs_protocol_write' },
          { status: 422, statusText: 'Unprocessable' },
        );
      expect(error).toHaveBeenLastCalledWith('Diese Person hat im Gremium kein Protokollrecht.');
      cmp.handOver(cmp.meeting()!, 'pr-9', 'next_item');
      http
        .expectOne('/api/meetings/m-1/protokollant-handover')
        .flush({ detail: 'last item', code: 'no_next_item' }, { status: 409, statusText: 'c' });
      expect(error.mock.lastCall?.[0]).toContain('last item');
      cmp.handOver(cmp.meeting()!, 'pr-9', 'now');
      http
        .expectOne('/api/meetings/m-1/protokollant-handover')
        .flush(null, { status: 500, statusText: 'e' });
      expect(error.mock.lastCall?.[0]).toBe('Aktion fehlgeschlagen.');
    });

    it('discards the planned handover', async () => {
      const { cmp, http, fixture } = await loaded();
      const toast = fixture.debugElement.injector.get(ToastService);
      const success = jest.spyOn(toast, 'success');
      const error = jest.spyOn(toast, 'error');
      cmp.cancelHandover(cmp.meeting()!);
      const req = http.expectOne('/api/meetings/m-1/protokollant-handover');
      expect(req.request.method).toBe('DELETE');
      req.flush({ ...MEETING, plannedHandover: null });
      expect(success).toHaveBeenLastCalledWith('Geplante Übergabe verworfen.');
      cmp.cancelHandover(cmp.meeting()!);
      http
        .expectOne('/api/meetings/m-1/protokollant-handover')
        .flush({ code: 'no_planned_handover' }, { status: 404, statusText: 'n' });
      expect(error).toHaveBeenCalled();
    });

  });

  describe('overview gating + filters', () => {
    it('shows the overview for a plain committee member without manage rights', async () => {
      const { fixture } = await setup({
        id: null,
        perms: [],
        meetings: [],
      });
      const cmp = fixture.componentInstance as Cmp;
      // Standard auth has gremien=[], so there is no overview. A signal override
      // would be costly. This test checks the computed logic through the flags.
      expect(cmp.showForbidden()).toBe(true);
      expect(cmp.showOverview()).toBe(false);
    });

    it('shows the overview to a meeting.view_all reader without a gremium', async () => {
      const { fixture } = await setup({ id: null, perms: ['meeting.view_all'], meetings: [] });
      const cmp = fixture.componentInstance as Cmp;
      expect(cmp.showOverview()).toBe(true);
      expect(cmp.showForbidden()).toBe(false);
    });

    it('loads and renders the timeline for a meeting.view_all reader without a gremium', async () => {
      // The page and loadList() share one predicate. Before, loadList() returned early
      // for this reader and the visible overview stayed empty.
      const { http } = await setup({ id: null, perms: ['meeting.view_all'], skipTimelineFlush: true });
      const reqs = http.match((r) => r.url.endsWith('/meetings/timeline') && r.method === 'GET');
      expect(reqs.map((r) => r.request.params.get('direction')).sort()).toEqual(['past', 'upcoming']);
      for (const req of reqs) {
        const past = req.request.params.get('direction') === 'past';
        req.flush({
          items: past
            ? [{ ...MEETING, id: 'p-9', title: 'Fremde Sitzung', status: 'closed' }]
            : [{ ...MEETING, id: 'u-9', title: 'Kommende Sitzung', status: 'planned' }],
          nextCursor: null,
        });
      }
      expect(await screen.findByText('Fremde Sitzung')).toBeInTheDocument();
      expect(screen.getByText('Kommende Sitzung')).toBeInTheDocument();
    });

    it('does not load the timeline for a user without any meeting read right', async () => {
      const { http, fixture } = await setup({ id: null, perms: [], skipTimelineFlush: true });
      expect(http.match((r) => r.url.endsWith('/meetings/timeline'))).toHaveLength(0);
      expect((fixture.componentInstance as Cmp).showForbidden()).toBe(true);
    });

    it('reflects per-meeting flags once a meeting is loaded', async () => {
      const { cmp } = await loaded();
      expect(cmp.canManage()).toBe(true);
      expect(cmp.canWrite()).toBe(true);
      expect(cmp.canManageVotes()).toBe(true);
      expect(cmp.canVote()).toBe(false);
      expect(cmp.isProtokollant()).toBe(false);
    });

    it('uses the global/false fallbacks for per-meeting flags without a meeting', async () => {
      const { fixture } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      expect(cmp.meeting()).toBeNull();
      // canManage falls back to canManageAny (true, since admin).
      expect(cmp.canManage()).toBe(true);
      expect(cmp.canWrite()).toBe(false);
      expect(cmp.canManageVotes()).toBe(false);
      expect(cmp.canVote()).toBe(false);
      expect(cmp.isProtokollant()).toBe(false);
    });

    it('marks a user as follower on the server rights alone, not on the protokollant', async () => {
      const { cmp } = await loaded();
      // A named protokollant leaves the rights of everybody else untouched.
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: 'someone', isProtokollant: false });
      expect(cmp.isFollower()).toBe(false);
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: 'someone', isProtokollant: true });
      expect(cmp.isFollower()).toBe(false);
      // No write and no manage right ⇒ follow view, with or without a protokollant.
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: null, canWrite: false, canManage: false });
      expect(cmp.isFollower()).toBe(true);
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: 'someone', canWrite: false, canManage: false });
      expect(cmp.isFollower()).toBe(true);
      cmp.meeting.set(null);
      expect(cmp.isFollower()).toBe(false);
    });

    it('gives a meeting.view_all reader the full view read-only, never the follow view', async () => {
      const { cmp } = await loaded({ perms: ['meeting.view_all'] });
      cmp.meeting.set({
        ...cmp.meeting()!,
        canWrite: false,
        canManage: false,
        protokollantId: 'someone',
      });
      expect(cmp.isFollower()).toBe(false);
      // A reader still may not type into the minutes.
      expect(cmp.canEditProtocol()).toBe(false);
    });

    it('grants the protocol edit only to the protokollant once one is named', async () => {
      const { cmp } = await loaded();
      // No protokollant yet: everyone with canWrite may take the minutes.
      expect(cmp.canEditProtocol()).toBe(true);
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: 'someone', isProtokollant: false });
      expect(cmp.canEditProtocol()).toBe(false);
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: 'someone', isProtokollant: true });
      expect(cmp.canEditProtocol()).toBe(true);
      cmp.meeting.set({ ...cmp.meeting()!, canWrite: false });
      expect(cmp.canEditProtocol()).toBe(false);
      cmp.meeting.set(null);
      expect(cmp.canEditProtocol()).toBe(false);
    });

  });

  describe('load error fallbacks', () => {
    it('clears attendance and agenda when their loads fail', async () => {
      const { fixture, http } = await setup();
      const cmp = fixture.componentInstance as Cmp;
      http.expectOne('/api/meetings/m-1').flush(MEETING);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      http.expectOne('/api/meetings/m-1/attendance').flush(null, { status: 500, statusText: 'e' });
      http.expectOne('/api/meetings/m-1/agenda').flush(null, { status: 500, statusText: 'e' });
      flushDelegationContext(http);
      expect(cmp.attendance()).toEqual([]);
      expect(cmp.agenda()).toEqual([]);
    });

    it('keeps a still-valid selected TOP after an agenda reload', async () => {
      const { cmp, http, ws } = await loaded();
      cmp.selectedTopId.set('t-1');
      // meeting_state broadcast re-triggers loadAgenda.
      ws.subject.next({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
      http.expectOne('/api/meetings/m-1/agenda').flush([
        { id: 't-1', applicationId: null, title: 'A', body: '', position: 0 },
        { id: 't-2', applicationId: null, title: 'B', body: '', position: 1 },
      ]);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      expect(cmp.selectedTopId()).toBe('t-1'); // unchanged, still valid
    });
  });

  describe('protocol rendering lifecycle', () => {
    it('toasts a failure when a rendering protocol rolls back to draft', async () => {
      const { cmp, ws, http } = await loaded();
      cmp.protocol.set({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
      // meeting_state with a non-final protocol → GET /protocol → applyProtocolUpdate.
      ws.subject.next({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'draft', isFinal: false, isLocked: false });
      expect(cmp.protocol()?.status).toBe('draft');
    });

    it('re-watches when a rendering poll fails', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http } = await loaded();
        cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' }); // F8: finalize after the close
        cmp.finalize();
        http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
        http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
        // The first poll after 4s fails, so watchRendering is rescheduled.
        jest.advanceTimersByTime(4000);
        http.expectOne('/api/meetings/m-1/protocol').flush(null, { status: 500, statusText: 'e' });
        // Second poll attempt after another 4s.
        jest.advanceTimersByTime(4000);
        http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
        expect(cmp.protocol()?.isFinal).toBe(true);
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe('live websocket', () => {
    it('adds a live-opened vote that did not exist yet (follower)', async () => {
      const { cmp, ws, fixture } = await loaded();
      ws.subject.next({
        type: 'vote_opened',
        voteId: 'v-new',
        applicationId: 'app-3',
        agendaItemId: 't-3',
        question: 'Frage?',
        options: ['yes', 'no'],
        closesAt: '2026-06-12T18:00:00Z',
      });
      fixture.detectChanges();
      expect(cmp.meeting()?.votes.some((v) => v.id === 'v-new' && v.status === 'open')).toBe(true);
    });

    it('patches an existing vote on a live vote_opened', async () => {
      const { cmp, ws } = await loaded();
      ws.subject.next({ type: 'vote_opened', voteId: 'v-2', closesAt: 'soon' });
      expect(cmp.meeting()?.votes.find((v) => v.id === 'v-2')?.status).toBe('open');
    });

    it('applies a vote_closed update', async () => {
      const { cmp, ws } = await loaded();
      ws.subject.next({ type: 'vote_closed', voteId: 'v-1', result: 'passed', counts: { yes: 9 }, failedReason: null });
      const v = cmp.meeting()?.votes.find((x) => x.id === 'v-1');
      expect(v?.status).toBe('closed');
      expect(v?.result).toBe('passed');
    });

    it('keeps the secrecy and the open time of a vote that another manager opened', async () => {
      const { cmp, ws } = await loaded();
      ws.subject.next({ type: 'vote_opened', voteId: 'v-2', options: ['yes', 'no'], closesAt: null, secret: true });
      const v = cmp.meeting()?.votes.find((x) => x.id === 'v-2');
      expect(v?.secret).toBe(true);
      expect(v?.openedAt).toEqual(expect.any(String));
    });

    it('sets the end time on a live close and a live cancel', async () => {
      const { cmp, ws } = await loaded();
      ws.subject.next({ type: 'vote_closed', voteId: 'v-1', result: 'passed', counts: { yes: 9 }, failedReason: null });
      expect(cmp.meeting()?.votes.find((x) => x.id === 'v-1')?.closedAt).toEqual(expect.any(String));
      ws.subject.next({ type: 'vote_cancelled', voteId: 'v-2' });
      const cancelled = cmp.meeting()?.votes.find((x) => x.id === 'v-2');
      expect(cancelled?.status).toBe('cancelled');
      expect(cancelled?.closedAt).toEqual(expect.any(String));
    });

    it('sets the open and the end time on an own open, close and cancel', async () => {
      const { cmp, http } = await loaded();
      const find = (id: string) => cmp.meeting()?.votes.find((x) => x.id === id);
      cmp.openVote('v-2');
      http.expectOne('/api/votes/v-2/open').flush(null, { status: 204, statusText: 'No Content' });
      expect(find('v-2')?.status).toBe('open');
      expect(find('v-2')?.openedAt).toEqual(expect.any(String));
      cmp.cancelVote('v-2');
      http.expectOne('/api/votes/v-2/cancel').flush(null, { status: 204, statusText: 'No Content' });
      expect(find('v-2')?.closedAt).toEqual(expect.any(String));
    });

    it('updates the viewer list from a viewers message', async () => {
      const { cmp, ws } = await loaded();
      ws.subject.next({ type: 'viewers', viewers: ['Alice', 'Bob'] });
      expect(cmp.viewers()).toEqual(['Alice', 'Bob']);
    });

    it('refreshes protocol on a meeting_state when writable and not final', async () => {
      const { cmp, ws, http } = await loaded();
      ws.subject.next({ type: 'meeting_state', activeApplicationId: 'app-2', status: 'live' });
      // loadAgenda + assignable + protocol GET.
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
      expect(cmp.protocol()?.isFinal).toBe(true);
    });

    it('keeps the prior status when the meeting_state status is absent', async () => {
      const { cmp, ws, http } = await loaded();
      const before = cmp.meeting()?.status;
      ws.subject.next({ type: 'meeting_state', activeApplicationId: 'app-2' });
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      expect(cmp.meeting()?.status).toBe(before);
      expect(cmp.meeting()?.activeApplicationId).toBe('app-2');
    });

    it('follows the current agenda item from a meeting_state and opens it when nothing is selected', async () => {
      const { cmp, ws, http } = await loaded();
      ws.subject.next({ type: 'meeting_state', activeApplicationId: null, currentAgendaItemId: 't-2', status: 'live' });
      http.expectOne('/api/meetings/m-1/agenda').flush([AGENDA_ITEM(), AGENDA_ITEM({ id: 't-2', position: 1 })]);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      expect(cmp.meeting()?.currentAgendaItemId).toBe('t-2');
      expect(cmp.currentTop()?.id).toBe('t-2');
      expect(cmp.currentTopIndex()).toBe(1);
      expect(cmp.selectedTopId()).toBe('t-2');
    });

    it('keeps the prior current item when the meeting_state omits it', async () => {
      const { cmp, ws, http } = await loaded();
      cmp.meeting.set({ ...MEETING_MODEL, currentAgendaItemId: 't-1' });
      ws.subject.next({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      expect(cmp.meeting()?.currentAgendaItemId).toBe('t-1');
    });

    it('broadcasts the item the room lead opens, once', async () => {
      const { cmp, http } = await loaded();
      cmp.agenda.set([AGENDA_ITEM(), AGENDA_ITEM({ id: 't-2', position: 1 })] as never);
      cmp.jumpTo('t-2');
      expect(cmp.selectedTopId()).toBe('t-2');
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual({ currentAgendaItemId: 't-2' });
      req.flush({ ...MEETING, currentAgendaItemId: 't-2' });
      expect(cmp.meeting()?.currentAgendaItemId).toBe('t-2');
      cmp.jumpTo('t-2');
      http.expectNone('/api/meetings/m-1');
    });

    it('keeps "now" local without vote management, after the close and without a meeting', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...MEETING_MODEL, canManageVotes: false });
      cmp.jumpTo('t-2');
      cmp.meeting.set({ ...MEETING_MODEL, status: 'closed' });
      cmp.jumpTo('t-2');
      cmp.meeting.set(null);
      cmp.jumpTo('t-2');
      http.expectNone('/api/meetings/m-1');
    });

    it('leaves the meeting untouched when the "now" broadcast fails', async () => {
      const { cmp, http } = await loaded();
      cmp.jumpTo('t-2');
      http.expectOne('/api/meetings/m-1').flush({ detail: 'nope' }, { status: 403, statusText: 'Forbidden' });
      expect(cmp.meeting()?.currentAgendaItemId).toBeNull();
    });

    it('navigates back to the list', async () => {
      const { cmp, navigate } = await loaded();
      cmp.goBack();
      expect(navigate).toHaveBeenCalledWith(['/meetings']);
    });

    it('ignores unknown live messages and messages with no meeting', async () => {
      const { cmp, ws } = await loaded();
      ws.subject.next({ type: 'pong' } as unknown as ServerMessage);
      cmp.meeting.set(null);
      ws.subject.next({ type: 'viewers', viewers: ['X'] }); // m null → early return
      expect(cmp.viewers()).toEqual([]);
    });
  });

  // Remaining branches for branch coverage: fallbacks, guards, empty maps, a
  // missing meeting instance, stale search, timeline height and mock mode.
  describe('branch coverage', () => {
    it('returns empty vote lists when no meeting is loaded', async () => {
      const { fixture } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      expect(cmp.meeting()).toBeNull();
      expect(services(fixture).session.votesForTop('t-1')).toEqual([]); // meeting()?.votes ?? []
      expect(cmp.looseVotes()).toEqual([]); // meeting()?.votes ?? []
      expect(cmp.beamerVote()).toBeNull(); // meeting()?.votes ?? []
    });

    it('clears all pending timers (body autosave, render poll) on destroy', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, fixture, http } = await loaded();
        // bodyTimer: an autosave that has not fired yet.
        cmp.onTopBodyChange('t-1', 'X');
        // renderPollTimer: protocol rendering → watchRendering schedules a poll.
        cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' }); // F8: finalize after the close
        cmp.finalize();
        http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
        http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
        fixture.destroy(); // ngOnDestroy → both clearTimeout branches
        jest.advanceTimersByTime(8000); // no timers fire anymore → no requests
        http.verify();
      } finally {
        jest.useRealTimers();
      }
    });

    it('does nothing in refreshProtocol when no meeting is loaded', async () => {
      const { fixture } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      expect(cmp.meeting()).toBeNull();
      // The `if (!m) return` guard of the session service stops any request.
      const http = fixture.debugElement.injector.get(HttpTestingController);
      services(fixture).session.refreshProtocol();
      http.verify();
    });

    it('skips the live channel in mock mode (no WebSocket handshake)', async () => {
      const ws = new FakeWs();
      const view = await render(MeetingsComponent, {
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          { provide: USE_MOCK_API, useValue: true },
          { provide: AuthService, useValue: fakeAuth(['admin', 'protocol.write']) },
          { provide: WsService, useValue: ws },
          { provide: Router, useValue: routerStub() },
          { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ id: 'm-1' })) } },
        ],
      });
      const http = view.fixture.debugElement.injector.get(HttpTestingController);
      // Mock mode: connectLive returns early because useMock is set. No WS channel opens.
      http.expectOne('/api/meetings/m-1').flush(MEETING);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      flushDelegationContext(http);
      expect(ws.closed).toBe(false); // connectMeeting was never called
    });

    it('re-watches a still-rendering protocol, clearing the prior poll timer', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, ws, http } = await loaded();
        // Finalize turns the protocol to rendering, so watchRendering schedules
        // the renderPollTimer.
        cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' }); // F8: finalize after the close
        cmp.finalize();
        http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
        http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
        // A meeting_state broadcast arrives before the 4s poll fires → getProtocol →
        // applyProtocolUpdate → watchRendering AGAIN while the old timer still runs
        // → the clearTimeout branch for renderPollTimer.
        ws.subject.next({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
        http.expectOne('/api/meetings/m-1/agenda').flush([]);
        http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
        // Now the (rescheduled) poll fires → final.
        jest.advanceTimersByTime(4000);
        http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
        expect(cmp.protocol()?.isFinal).toBe(true);
      } finally {
        jest.useRealTimers();
      }
    });

    it('stops a rendering poll when the meeting vanished before it fired', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http } = await loaded();
        cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' }); // F8: finalize after the close
        cmp.finalize();
        http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
        http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
        // The meeting is gone before the poll timer fires, so the poll callback returns.
        cmp.meeting.set(null);
        jest.advanceTimersByTime(4000);
        http.verify(); // no GET /protocol
      } finally {
        jest.useRealTimers();
      }
    });

    it('starts renaming a freetext TOP with a null title (empty draft)', async () => {
      const { cmp } = await loaded();
      cmp.startRename(AGENDA_ITEM({ applicationId: null, title: null }) as never);
      expect(cmp.renamingTopId()).toBe('t-1');
      expect(cmp.renameDraft()).toBe(''); // item.title ?? ''
    });

    it('cancels a rename when the item turns out to be application-bound', async () => {
      const { cmp, http } = await loaded();
      // Set renamingTopId manually to the app TOP id, because startRename rejects it.
      // renameTop then takes the item.applicationId branch of the OR chain. It cancels
      // and sends no request.
      cmp.renamingTopId.set('t-app');
      cmp.renameDraft.set('Neu');
      cmp.renameTop(AGENDA_ITEM({ id: 't-app', applicationId: 'app-1', title: 'X' }) as never);
      expect(cmp.renamingTopId()).toBeNull();
      http.verify();
    });

    it('saves a renamed freetext TOP whose previous title was null (?? fallback)', async () => {
      const { cmp, http } = await loaded();
      // With item.title === null the OR chain reaches `title === (item.title ?? '')`.
      // It evaluates `item.title ?? ''` on the null branch → '' ≠ 'Neu' → save.
      cmp.startRename(AGENDA_ITEM({ id: 't-1', applicationId: null, title: null }) as never);
      cmp.renameDraft.set('Neu');
      cmp.renameTop(AGENDA_ITEM({ id: 't-1', applicationId: null, title: null }) as never);
      const req = http.expectOne('/api/meetings/m-1/agenda/t-1');
      expect(req.request.body).toEqual({ title: 'Neu' });
      req.flush([AGENDA_ITEM({ title: 'Neu' })]);
      expect(cmp.savingAgenda()).toBe(false);
    });

    it('adds a live-opened vote with all optional fields defaulted', async () => {
      const { cmp, ws, fixture } = await loaded();
      // vote_opened WITHOUT applicationId, agendaItemId, question or options starts
      // the `?? null` and `?? []` fallbacks. The wire message stays minimal on purpose,
      // because the optional fields are absent at runtime. That is why the test casts
      // with `as unknown as ServerMessage`. VoteOpenedMsg otherwise requires `options`.
      ws.subject.next({ type: 'vote_opened', voteId: 'v-min', closesAt: null } as unknown as ServerMessage);
      fixture.detectChanges();
      const v = cmp.meeting()?.votes.find((x) => x.id === 'v-min');
      expect(v).toBeDefined();
      expect(v?.applicationId).toBeNull();
      expect(v?.agendaItemId).toBeNull();
      expect(v?.question).toBeNull();
      expect(v?.options).toEqual([]);
    });

    it('does nothing in patchVote once the meeting has been cleared', async () => {
      const { cmp, http } = await loaded();
      // openVote triggers patchVote on success. If the meeting is null by then,
      // the early `if (!m) return` guard applies and no state changes.
      cmp.openVote('v-2');
      cmp.meeting.set(null);
      http.expectOne('/api/votes/v-2/open').flush(null, { status: 204, statusText: 'No Content' });
      expect(cmp.meeting()).toBeNull();
    });
  });

  describe('date, time and DOM ids', () => {
    /** The API sends a SQL `time`, thus `18:00:00`. The seconds are noise on screen. */
    const AT_18: MeetingOutWire = { ...MEETING, startTime: '18:00:00', endTime: '20:30:00' };

    it('prints the detail header time as HH:MM', async () => {
      const { container, http } = await setup();
      http.expectOne('/api/meetings/m-1').flush(AT_18);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      flushDelegationContext(http);
      expect(await screen.findByText('Sitzungssteuerung')).toBeInTheDocument();
      expect(container.textContent).toContain('18:00');
      expect(container.textContent).not.toContain('18:00:00');
    });

  });
});
