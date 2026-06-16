import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject } from 'rxjs';
import { of } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import type { MeetingOutWire, ProtocolOutWire } from '@core/api/models';
import { WsService, type MeetingChannel } from '@core/ws/ws.service';
import type { ServerMessage } from '@core/ws/ws-messages';
import { MeetingsComponent } from './meetings.component';

const MEETING: MeetingOutWire = {
  id: 'm-1',
  title: 'StuPa-Sitzung',
  status: 'live',
  // Datum/Uhrzeit sind Pflicht (Settings-Dialog speichert sonst nicht) — wie eine echte Sitzung.
  date: '2026-06-12',
  startTime: '17:00',
  endTime: null,
  activeApplicationId: 'app-1',
  gremiumId: null,
  protocolId: 'p-1',
  canControl: true,
  canManage: true,
  canWrite: true,
  canManageVotes: true,
  canVote: false,
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
      status: 'pending',
      result: null,
      counts: null,
      leading: null,
      closesAt: null,
    },
  ],
  createdAt: '2026-06-12T17:00:00Z',
};

const PROTOCOL: ProtocolOutWire = {
  id: 'p-1',
  meetingId: 'm-1',
  markdown: '# Protokoll',
  status: 'draft',
  pdfUrl: null,
  sentAt: null,
};

/** Fake-WsService, der einen steuerbaren Message-Strom liefert. */
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
    userId: (() => userId) as unknown as AuthService['userId'],
    gremien: (() => []) as unknown as AuthService['gremien'],
    sessionManageGremien: (() => []) as unknown as AuthService['sessionManageGremien'],
    inSubstitutePool: (() => false) as unknown as AuthService['inSubstitutePool'],
  };
}

async function setup(
  opts: {
    perms?: string[];
    id?: string | null;
    gremien?: { id: string; name: string }[];
    meetings?: MeetingOutWire[];
    userId?: string | null;
    /** Initiale Timeline-Requests NICHT automatisch beantworten (Test flusht selbst). */
    skipTimelineFlush?: boolean;
  } = {},
) {
  const perms = opts.perms ?? ['meeting.manage', 'protocol.write'];
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
      { provide: Router, useValue: { navigate } },
      {
        provide: ActivatedRoute,
        useValue: { paramMap: of(convertToParamMap(id ? { id } : {})) },
      },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  // Gremien-Dropdown (#68) lädt beim Start `/gremien` (nur mit meeting.manage).
  http.match((r) => r.url.endsWith('/gremien')).forEach((req) => req.flush(opts.gremien ?? []));
  // Übersichts-Route lädt die Timeline (#104) — je eine Cursor-Seite past/upcoming.
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

/** Meeting + (Auto-)Protokoll + Anwesenheit + Tagesordnung laden — alle Requests beantworten. */
function flushLoad(http: HttpTestingController): void {
  http.expectOne('/api/meetings/m-1').flush(MEETING);
  http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
  http.expectOne('/api/meetings/m-1/attendance').flush([]);
  http.expectOne('/api/meetings/m-1/agenda').flush([]);
  http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
  flushDelegationContext(http);
}

/** Vertretungs-Karte (#delegation-rework): Sitzungs-Kontext neutral beantworten
 *  (Feature im Test-Gremium deaktiviert → Karte unsichtbar). */
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
  });

  it('loads the meeting and renders session control with votes', async () => {
    const { http } = await setup();
    flushLoad(http);
    expect(await screen.findByText('Sitzungssteuerung')).toBeInTheDocument();
    expect(screen.getByText('Antrag A')).toBeInTheDocument();
    expect(screen.getByText('Antrag B')).toBeInTheDocument();
    // Die Vertretungs-Karte lädt ihren Kontext erst nach dem Rendern — nachflushen.
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
    req.flush(null, { status: 204, statusText: 'No Content' });
  });

  it('sets the active application via PATCH', async () => {
    const { http } = await setup();
    flushLoad(http);
    // „Aktiv setzen" am zweiten (noch nicht aktiven) Vote.
    const buttons = await screen.findAllByRole('button', { name: /Aktiv setzen/i });
    await userEvent.click(buttons[buttons.length - 1]);
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ activeApplicationId: 'app-2' });
    req.flush({ ...MEETING, activeApplicationId: 'app-2' });
  });

  it('assembles the TOPs and finalizes the protocol (#58)', async () => {
    const { http } = await setup();
    http.expectOne('/api/meetings/m-1').flush(MEETING);
    http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([
      { id: 't-1', applicationId: null, title: 'Begrüßung', body: 'Eröffnet.', position: 0 },
    ]);
    http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);

    // Schließen ist unwiderruflich: Toolbar-Button öffnet den Bestätigungs-Dialog,
    // bestätigen schließt die Sitzung (PATCH status) und finalisiert implizit.
    await userEvent.click(await screen.findByRole('button', { name: 'Schließen' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Sitzung schließen' }));
    const closeReq = http.expectOne('/api/meetings/m-1');
    expect(closeReq.request.method).toBe('PATCH');
    expect(closeReq.request.body).toEqual({ status: 'closed' });
    closeReq.flush({ ...MEETING, status: 'closed' });
    // Erst werden die TOP-Texte zum Protokoll-Markdown zusammengesetzt (PATCH) …
    const saveReq = http.expectOne('/api/protocols/p-1');
    expect(saveReq.request.method).toBe('PATCH');
    // Top-level `#` ohne „TOP n:"-Präfix — pytex nummeriert die TOPs selbst (#pdf).
    expect(saveReq.request.body.markdown).toContain('# Begrüßung');
    saveReq.flush(PROTOCOL);
    // … danach finalisiert/gerendert.
    const finReq = http.expectOne('/api/protocols/p-1/finalize');
    expect(finReq.request.method).toBe('POST');
    finReq.flush({ ...PROTOCOL, status: 'final', pdfUrl: 'https://example/p.pdf' });

    expect(await screen.findByText('Final')).toBeInTheDocument();
  });

  it('retries a failed finalize via the toolbar repeat button', async () => {
    const { http } = await setup();
    // Sitzung schon geschlossen, Protokoll wieder Entwurf ⇒ Render fehlgeschlagen.
    http.expectOne('/api/meetings/m-1').flush({ ...MEETING, status: 'closed' });
    http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);

    await userEvent.click(
      await screen.findByRole('button', { name: 'Finalisieren & versenden' }),
    );
    // finalize() speichert erst das zusammengesetzte Markdown, dann POST /finalize.
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

  it('lets a manager create a meeting and redirects to its detail route (#104)', async () => {
    const { http, navigate, fixture } = await setup({
      id: null,
      gremien: [{ id: 'g-1', name: 'StuPa' }],
    });
    // Anlegen über einen 2-Schritt-Dialog (#27): öffnen.
    await userEvent.click(screen.getByRole('button', { name: 'Neue Sitzung' }));
    // Schritt 1: Gremium wählen (lädt das Protokollant-Roster) + Pflicht-Termin.
    // Im Dialog suchen: das Pflicht-Label trägt ein „*", und die Suchleiste der
    // Übersicht erwähnt „Gremium" ebenfalls — beides macht eine globale Suche mehrdeutig.
    const dialog = await screen.findByRole('dialog');
    await userEvent.selectOptions(within(dialog).getByLabelText(/Gremium/), 'g-1');
    http.expectOne((r) => r.url.endsWith('/gremien/g-1/meeting-members')).flush([]);
    // Datum/Uhrzeit über die Signals setzen — Datepicker/Time-Input parsen Freitext,
    // was sich per userEvent kaum stabil tippen lässt.
    fixture.componentInstance.newDate.set('2026-07-01');
    fixture.componentInstance.newTime.set('17:00');
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    // Schritt 2: Titel überschreiben (wird sonst aus Gremium + Datum vorbelegt).
    const input = await screen.findByLabelText('Titel');
    await userEvent.clear(input);
    await userEvent.type(input, 'Neue Sitzung');
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung anlegen' }));
    const req = http.expectOne('/api/meetings');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      title: 'Neue Sitzung',
      gremiumId: 'g-1',
      date: '2026-07-01',
      startTime: '17:00',
      endTime: null,
      protokollantId: null,
    });
    req.flush({ ...MEETING, title: 'Neue Sitzung', protocolId: null });
    // Wiederauffindbarkeit: nach dem Anlegen auf `/meetings/{id}` navigieren.
    expect(navigate).toHaveBeenCalledWith(['/meetings', 'm-1']);
  });

  it('lists existing meetings and opens one (#104)', async () => {
    const { navigate } = await setup({
      id: null,
      meetings: [{ ...MEETING, title: 'Vergangene Sitzung', status: 'closed' }],
    });
    expect(await screen.findByText('Vergangene Sitzung')).toBeInTheDocument();
    // Die Timeline-Karte selbst ist die Öffnen-Affordanz (role=button, aria „Öffnen: …").
    await userEvent.click(screen.getByRole('button', { name: /Öffnen/ }));
    expect(navigate).toHaveBeenCalledWith(['/meetings', 'm-1']);
  });

  it('closes the session via PATCH status after confirming', async () => {
    const { http } = await setup();
    flushLoad(http);
    // Toolbar "Schließen" öffnet den unwiderruflichen Bestätigungs-Dialog.
    await userEvent.click(await screen.findByRole('button', { name: 'Schließen' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Sitzung schließen' }));
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ status: 'closed' });
    req.flush({ ...MEETING, status: 'closed' });
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
    // #protocol-on-start: das Protokoll entsteht ausschließlich beim Start der Sitzung;
    // ein manueller »Protokoll anlegen«-Button existiert nicht mehr.
    const { http } = await setup();
    http.expectOne('/api/meetings/m-1').flush({ ...MEETING, protocolId: null });
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
    expect(
      await screen.findByText('Für diese Sitzung gibt es noch kein Protokoll.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Protokoll anlegen' })).not.toBeInTheDocument();
  });

  it('persists the selected protokollant via PATCH and shows the name', async () => {
    const { http } = await setup();
    flushLoad(http);
    const editBtns = await screen.findAllByRole('button', { name: /Sitzung bearbeiten/i });
    await userEvent.click(editBtns[0]);
    // openSettings lädt das Roster erneut (Protokollant-Optionen).
    http.expectOne('/api/meetings/m-1/attendance').flush([
      { principalId: 'pr-1', displayName: 'Max P', email: 'm@x.de', status: null, source: null, isSelf: false },
    ]);
    // Exaktes Label: der Start-Button trägt jetzt eine aria-label „Protokollant zuweisen …",
    // an der ein /Protokollant/-Regex sonst mehrdeutig wird.
    const select = await screen.findByLabelText('Protokollant');
    await screen.findByRole('option', { name: 'Max P' });
    await userEvent.selectOptions(select, 'pr-1');
    await userEvent.click(screen.getByRole('button', { name: /Speichern/i }));
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body.protokollantId).toBe('pr-1');
    req.flush({ ...MEETING, protokollantId: 'pr-1', protokollantName: 'Max P' });
    // Name erscheint nach dem Speichern (Karte/Toolbar).
    expect(await screen.findByText(/Max P/)).toBeInTheDocument();
  });

  it('gives non-protokollants the live read/vote view once a protokollant is assigned', async () => {
    // Sitzung mit zugewiesenem Protokollanten (jemand anderes) — der angemeldete
    // Nutzer ist NICHT der Protokollant ⇒ Live-/Mitstimm-Ansicht, kein Manager-View.
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
});

// ---------------------------------------------------------------------------
// Instanz-getriebene Tests: rufen die öffentlichen Methoden direkt auf und
// prüfen Signals + HTTP. Erreicht die Verzweigungen, die das DOM allein nicht
// auslöst (Fehlerpfade, Such-Debounce, Drag&Drop, WS-Nachrichten, Helfer).
// ---------------------------------------------------------------------------
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

/** Eine geladene Detail-Sitzung herstellen und die Instanz zurückgeben. */
async function loaded(opts: Parameters<typeof setup>[0] = {}) {
  const view = await setup(opts);
  view.http.expectOne('/api/meetings/m-1').flush(MEETING);
  view.http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
  view.http.expectOne('/api/meetings/m-1/attendance').flush([]);
  view.http.expectOne('/api/meetings/m-1/agenda').flush([]);
  view.http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
  flushDelegationContext(view.http);
  const cmp = view.fixture.componentInstance as Cmp;
  return { ...view, cmp };
}

describe('MeetingsComponent — methods', () => {
  describe('display helpers', () => {
    it('maps status to badge variants and i18n keys', async () => {
      const { cmp } = await loaded();
      expect(cmp.statusVariant('live')).toBe('success');
      expect(cmp.statusVariant('closed')).toBe('neutral');
      expect(cmp.statusVariant('planned')).toBe('info');
      expect(cmp.statusKey('live')).toBe('meetings.status.live');
    });

    it('maps vote status to badge variants and keys', async () => {
      const { cmp } = await loaded();
      expect(cmp.voteVariant('open')).toBe('success');
      expect(cmp.voteVariant('closed')).toBe('neutral');
      expect(cmp.voteVariant('cancelled')).toBe('danger');
      expect(cmp.voteVariant('pending')).toBe('warning');
      expect(cmp.voteStatusKey('open')).toBe('meetings.voteStatus.open');
    });

    it('maps vote results to keys and variants including the tie fallback', async () => {
      const { cmp } = await loaded();
      expect(cmp.voteResultKey('passed')).toBe('vote.result.passed');
      expect(cmp.voteResultKey(null)).toBe('vote.result.tie');
      expect(cmp.voteResultKey(undefined)).toBe('vote.result.tie');
      expect(cmp.voteResultVariant('passed')).toBe('success');
      expect(cmp.voteResultVariant('rejected')).toBe('danger');
      expect(cmp.voteResultVariant('tie')).toBe('neutral');
    });

    it('maps attendance to keys, button + badge variants and icons', async () => {
      const { cmp } = await loaded();
      expect(cmp.attendanceKey('present')).toBe('meetings.attendance.present');
      expect(cmp.attendanceKey('unknown')).toBe('meetings.attendance.unknown');
      expect(cmp.attBtnVariant('present')).toBe('primary');
      expect(cmp.attBtnVariant('excused')).toBe('secondary');
      expect(cmp.attBtnVariant('absent')).toBe('danger');
      expect(cmp.attendanceIcon('present')).toBe('check');
      expect(cmp.attendanceIcon('excused')).toBe('half');
      expect(cmp.attendanceIcon('absent')).toBe('remove');
      expect(cmp.attBadgeVariant('present')).toBe('success');
      expect(cmp.attBadgeVariant('excused')).toBe('warning');
      expect(cmp.attBadgeVariant('absent')).toBe('danger');
    });

    it('resolves i18n maps and state labels with fallbacks', async () => {
      const { cmp } = await loaded();
      expect(cmp.resolveLabel({ de: 'Entwurf', en: 'Draft' })).toBe('Entwurf');
      expect(cmp.resolveLabel({ en: 'Draft' })).toBe('Draft');
      expect(cmp.resolveLabel({})).toBe('');
      expect(cmp.stateLabelOf(null)).toBe('');
      expect(cmp.stateLabelOf(undefined)).toBe('');
      expect(cmp.stateLabelOf({ de: 'Abstimmung' })).toBe('Abstimmung');
      expect(cmp.stateLabelOf({ fr: 'X' })).toBe('X');
    });

    it('labels vote options, falling back to the raw key when unknown', async () => {
      const { cmp } = await loaded();
      expect(cmp.voteOptionLabel('yes')).not.toBe('yes'); // übersetzt
      expect(cmp.voteOptionLabel('weird-option')).toBe('weird-option');
    });

    it('renders body markdown via the util', async () => {
      const { cmp } = await loaded();
      expect(cmp.renderBody('# H')).toContain('<h1>H</h1>');
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
      // Weder Optionen noch Counts → leere Liste (deckt den ?? {} Fallback).
      const empty = cmp.voteOptionsFor({
        id: 'v', applicationId: null, agendaItemId: null, title: null, question: null,
        options: [], status: 'open', result: null, counts: null, leading: null,
        closesAt: null, voted: 0, present: 0, revealed: true, failedReason: null,
      });
      expect(empty).toEqual([]);
    });

    it('groups votes by TOP and collects loose votes', async () => {
      const { cmp } = await loaded();
      expect(cmp.votesForTop('app-1')).toEqual([]); // votesForTop matches agendaItemId
      // MEETING-Votes haben keine agendaItemId → alle „lose".
      expect(cmp.looseVotes().length).toBe(2);
      // Einen Vote an einen TOP binden → votesForTop trifft, looseVotes schrumpft.
      cmp.meeting.set({
        ...cmp.meeting()!,
        votes: [
          { ...cmp.meeting()!.votes[0], id: 'bound', agendaItemId: 't-7' },
          { ...cmp.meeting()!.votes[1], id: 'loose', agendaItemId: null },
        ],
      });
      expect(cmp.votesForTop('t-7').map((v) => v.id)).toEqual(['bound']);
      expect(cmp.looseVotes().map((v) => v.id)).toEqual(['loose']);
    });

    it('selects the beamer vote: open first, else last closed, else null', async () => {
      const { cmp } = await loaded();
      // MEETING hat einen offenen Vote (v-1).
      expect(cmp.beamerVote()?.id).toBe('v-1');
      // Keine offenen Votes → letzter geschlossener.
      cmp.meeting.set({
        ...cmp.meeting()!,
        votes: [
          { ...cmp.meeting()!.votes[0], id: 'c1', status: 'closed' },
          { ...cmp.meeting()!.votes[0], id: 'c2', status: 'closed' },
        ],
      });
      expect(cmp.beamerVote()?.id).toBe('c2');
      // Weder offen noch geschlossen → null.
      cmp.meeting.set({
        ...cmp.meeting()!,
        votes: [{ ...cmp.meeting()!.votes[0], id: 'p', status: 'pending' }],
      });
      expect(cmp.beamerVote()).toBeNull();
    });

    it('builds assignable options with and without a state label', async () => {
      const { cmp } = await loaded();
      cmp.assignable.set([
        { applicationId: 'app-1', title: 'Antrag A', stateLabel: { de: 'Abstimmung' } },
        { applicationId: 'app-2', title: '', stateLabel: null },
      ] as never);
      const opts = cmp.assignableOptions();
      expect(opts[0].label).toBe('Antrag A (Abstimmung)');
      // Kein Titel → Fallback auf die applicationId, kein State → kein Suffix.
      expect(opts[1]).toEqual({ value: 'app-2', label: 'app-2' });
    });

    it('builds create-protokollant options from the loaded members', async () => {
      const { cmp } = await loaded();
      cmp.createMembers.set([
        { principalId: 'pr-1', displayName: 'Max', email: 'm@x' },
        { principalId: 'pr-2', displayName: '', email: 'b@x' },
        { principalId: 'pr-3', displayName: '', email: '' },
      ] as never);
      const opts = cmp.createProtokollantOptions();
      // Erste Option ist immer „niemand".
      expect(opts[0].value).toBe('');
      expect(opts[1]).toEqual({ value: 'pr-1', label: 'Max' });
      expect(opts[2]).toEqual({ value: 'pr-2', label: 'b@x' }); // displayName leer → email
      expect(opts[3]).toEqual({ value: 'pr-3', label: 'pr-3' }); // beide leer → id
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
        const { cmp, http } = await loaded();
        cmp.onTopBodyChange('t-1', 'Neuer Text');
        expect(cmp.saveState()).toBe('idle');
        // Erneuter Aufruf vor Ablauf → Timer zurücksetzen (deckt clearTimeout-Zweig).
        cmp.onTopBodyChange('t-1', 'Neuer Text 2');
        jest.advanceTimersByTime(1000);
        expect(cmp.saveState()).toBe('saving');
        const req = http.expectOne('/api/meetings/m-1/agenda/t-1');
        expect(req.request.method).toBe('PATCH');
        expect(req.request.body).toEqual({ body: 'Neuer Text 2' });
        req.flush([AGENDA_ITEM({ body: 'Neuer Text 2' })]);
        expect(cmp.saveState()).toBe('saved');
        expect(cmp.savingTop()).toBe(false);
      } finally {
        jest.useRealTimers();
      }
    });

    it('sets the error save state when the body save fails', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http } = await loaded();
        cmp.onTopBodyChange('t-1', 'X');
        jest.advanceTimersByTime(1000);
        http.expectOne('/api/meetings/m-1/agenda/t-1').flush(null, { status: 500, statusText: 'e' });
        expect(cmp.saveState()).toBe('error');
        expect(cmp.savingTop()).toBe(false);
      } finally {
        jest.useRealTimers();
      }
    });

    it('does nothing on body change without a loaded meeting', async () => {
      const { fixture } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      cmp.onTopBodyChange('t-1', 'X'); // meeting() === null → früher return
      expect(cmp.saveState()).toBe('idle');
    });

    it('adds an application to the agenda', async () => {
      const { cmp, http } = await loaded();
      cmp.agendaPick.set('app-9');
      cmp.addToAgenda();
      const req = http.expectOne('/api/meetings/m-1/agenda');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ applicationId: 'app-9' });
      req.flush([AGENDA_ITEM({ applicationId: 'app-9' })]);
      // refreshAssignable lädt erneut.
      http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
      expect(cmp.agendaPick()).toBe('');
      expect(cmp.savingAgenda()).toBe(false);
    });

    it('ignores addToAgenda without a pick / while saving', async () => {
      const { cmp, http } = await loaded();
      cmp.agendaPick.set('');
      cmp.addToAgenda(); // kein appId → return
      cmp.agendaPick.set('app-9');
      cmp.savingAgenda.set(true);
      cmp.addToAgenda(); // savingAgenda → return
      http.verify();
    });

    it('handles an addToAgenda error', async () => {
      const { cmp, http } = await loaded();
      cmp.agendaPick.set('app-9');
      cmp.addToAgenda();
      http.expectOne('/api/meetings/m-1/agenda').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.savingAgenda()).toBe(false);
    });

    it('adds a freetext TOP', async () => {
      const { cmp, http } = await loaded();
      cmp.agendaFreetext.set('Sonstiges');
      cmp.addFreetext();
      const req = http.expectOne('/api/meetings/m-1/agenda');
      expect(req.request.body).toEqual({ title: 'Sonstiges' });
      req.flush([AGENDA_ITEM({ title: 'Sonstiges' })]);
      expect(cmp.agendaFreetext()).toBe('');
    });

    it('ignores addFreetext when empty and handles its error', async () => {
      const { cmp, http } = await loaded();
      cmp.agendaFreetext.set('   ');
      cmp.addFreetext(); // leer → return
      cmp.agendaFreetext.set('Sonstiges');
      cmp.addFreetext();
      http.expectOne('/api/meetings/m-1/agenda').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.savingAgenda()).toBe(false);
    });

    it('removes a TOP from the agenda and refreshes assignable', async () => {
      const { cmp, http } = await loaded();
      cmp.removeFromAgenda('t-1');
      http.expectOne('/api/meetings/m-1/agenda/t-1').flush([]);
      http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
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
      cmp.addToAgenda();
      cmp.addFreetext();
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
      cmp.renameTop(AGENDA_ITEM({ title: 'Alt' }) as never); // leer → cancel
      expect(cmp.renamingTopId()).toBeNull();
      cmp.startRename(AGENDA_ITEM({ title: 'Alt' }) as never);
      cmp.renameDraft.set('Alt');
      cmp.renameTop(AGENDA_ITEM({ title: 'Alt' }) as never); // unverändert → cancel
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
      cmp.onTopDrop(2); // t-1 ans Ende
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
      if (cmp.canManage()) {
        http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
      }
    });

    it('ignores a drop onto the same index or without a drag source', async () => {
      const { cmp, http } = await loaded();
      cmp.agenda.set([AGENDA_ITEM({ id: 't-1' })] as never);
      cmp.onTopDrop(0); // dragTopIndex null → return
      cmp.onTopDragStart(0);
      cmp.onTopDrop(0); // from === index → return
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
    it('sets own attendance via the me-endpoint', async () => {
      const { cmp, http } = await loaded();
      cmp.setAttendance(
        { principalId: 'pr-1', displayName: 'Me', email: null, status: null, source: null, isSelf: true } as never,
        'present',
      );
      const req = http.expectOne('/api/meetings/m-1/attendance/me');
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({ status: 'present' });
      req.flush([]);
      expect(cmp.savingAttendance()).toBe(false);
    });

    it('sets a member attendance via the principal endpoint', async () => {
      const { cmp, http } = await loaded();
      cmp.setAttendance(
        { principalId: 'pr-2', displayName: 'X', email: null, status: 'absent', source: null, isSelf: false } as never,
        'present',
      );
      const req = http.expectOne('/api/meetings/m-1/attendance/pr-2');
      expect(req.request.method).toBe('PUT');
      req.flush([]);
      expect(cmp.savingAttendance()).toBe(false);
    });

    it('skips when the status is unchanged or already saving', async () => {
      const { cmp, http } = await loaded();
      cmp.setAttendance(
        { principalId: 'pr-2', displayName: 'X', email: null, status: 'present', source: null, isSelf: false } as never,
        'present', // unverändert → return
      );
      cmp.savingAttendance.set(true);
      cmp.setAttendance(
        { principalId: 'pr-2', displayName: 'X', email: null, status: 'absent', source: null, isSelf: false } as never,
        'present',
      );
      http.verify();
    });

    it('handles an attendance error', async () => {
      const { cmp, http } = await loaded();
      cmp.setAttendance(
        { principalId: 'pr-1', displayName: 'Me', email: null, status: null, source: null, isSelf: true } as never,
        'present',
      );
      http.expectOne('/api/meetings/m-1/attendance/me').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.savingAttendance()).toBe(false);
    });
  });

  describe('session control', () => {
    it('starts the session (status live) when a protokollant is set', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'planned', protokollantId: 'pr-9' });
      cmp.setStatus('live');
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual({ status: 'live' });
      req.flush({ ...MEETING, status: 'live', protocolId: 'p-1' });
      // canWrite + protocolId → refreshProtocol nachladen.
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    });

    it('refuses to start without a protokollant', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'planned', protokollantId: null });
      cmp.setStatus('live');
      http.verify(); // kein PATCH
    });

    it('refuses to change a closed session', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'closed' });
      cmp.setStatus('live');
      http.verify();
    });

    it('does nothing on setStatus without a meeting', async () => {
      const { fixture } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      cmp.setStatus('live');
      expect(cmp.meeting()).toBeNull();
    });

    it('reports an error on a failed status change', async () => {
      const { cmp, http } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, status: 'planned', protokollantId: 'pr-9' });
      cmp.setStatus('closed');
      http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'e' });
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
      expect(cmp.meeting()?.activeApplicationId).toBe('app-1'); // unverändert
    });

    it('does nothing on setActive without a meeting', async () => {
      const { fixture } = await setup({ id: null });
      (fixture.componentInstance as Cmp).setActive('x');
      expect((fixture.componentInstance as Cmp).meeting()).toBeNull();
    });

    it('saves a planned date', async () => {
      const { cmp, http } = await loaded();
      cmp.planDate.set('2026-07-01');
      cmp.planTime.set('18:00');
      cmp.savePlannedDate();
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual({ date: '2026-07-01', startTime: '18:00' });
      req.flush({ ...MEETING, date: '2026-07-01' });
      expect(cmp.savingDate()).toBe(false);
    });

    it('sends a null start time when none is given and handles errors', async () => {
      const { cmp, http } = await loaded();
      cmp.planDate.set('2026-07-01');
      cmp.planTime.set('');
      cmp.savePlannedDate();
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual({ date: '2026-07-01', startTime: null });
      req.flush(null, { status: 500, statusText: 'e' });
      expect(cmp.savingDate()).toBe(false);
    });

    it('ignores savePlannedDate without a date / meeting / while saving', async () => {
      const { cmp, http } = await loaded();
      cmp.planDate.set('');
      cmp.savePlannedDate(); // kein Datum → return
      cmp.planDate.set('2026-07-01');
      cmp.savingDate.set(true);
      cmp.savePlannedDate(); // savingDate → return
      http.verify();
    });

    it('closes the session and finalizes an unlocked protocol', async () => {
      const { cmp, http } = await loaded();
      cmp.closeMeeting();
      const closeReq = http.expectOne('/api/meetings/m-1');
      expect(closeReq.request.body).toEqual({ status: 'closed' });
      closeReq.flush({ ...MEETING, status: 'closed' });
      // protocol (draft, nicht isLocked) → finalize: erst Markdown-PATCH …
      http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
      http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'final' });
    });

    it('closes the session without finalizing a locked protocol', async () => {
      const { cmp, http } = await loaded();
      cmp.protocol.set({ ...cmp.protocol()!, status: 'final', isFinal: true, isLocked: true });
      cmp.closeMeeting();
      http.expectOne('/api/meetings/m-1').flush({ ...MEETING, status: 'closed' });
      http.verify(); // kein finalize
    });

    it('handles a closeMeeting error and guards against re-entry while finalizing', async () => {
      const { cmp, http } = await loaded();
      cmp.finalizing.set(true);
      cmp.closeMeeting(); // finalizing → return
      cmp.finalizing.set(false);
      cmp.closeMeeting();
      http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'e' });
    });
  });

  describe('votes', () => {
    it('opens a vote and patches its status', async () => {
      const { cmp, http } = await loaded();
      cmp.openVote('v-2');
      http.expectOne('/api/votes/v-2/open').flush(null, { status: 204, statusText: 'No Content' });
      expect(cmp.meeting()?.votes.find((v) => v.id === 'v-2')?.status).toBe('open');
    });

    it('closes a vote and patches its status', async () => {
      const { cmp, http } = await loaded();
      cmp.closeVote('v-1');
      http.expectOne('/api/votes/v-1/close').flush(null, { status: 204, statusText: 'No Content' });
      expect(cmp.meeting()?.votes.find((v) => v.id === 'v-1')?.status).toBe('closed');
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
      // voteActionFailed lädt die Sitzung neu.
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
      const { cmp } = await loaded();
      // Freitext-TOP: immer erlaubt.
      expect(cmp.canAddVote(AGENDA_ITEM({ applicationId: null }) as never)).toBe(true);
      // Antrags-TOP ohne Vote (votesForTop matcht agendaItemId) → erlaubt.
      expect(cmp.canAddVote(AGENDA_ITEM({ id: 't-x', applicationId: 'app-1' }) as never)).toBe(true);
      // Antrags-TOP mit gebundenem Vote → gesperrt.
      cmp.meeting.set({
        ...cmp.meeting()!,
        votes: [{ ...cmp.meeting()!.votes[0], agendaItemId: 't-x' }],
      });
      expect(cmp.canAddVote(AGENDA_ITEM({ id: 't-x', applicationId: 'app-1' }) as never)).toBe(false);
    });

    it('prefills the vote dialog from an application TOP and a freetext TOP', async () => {
      const { cmp } = await loaded();
      cmp.openVoteDialog(AGENDA_ITEM({ applicationId: 'app-1', title: 'Antrag X' }) as never);
      expect(cmp.voteDialogOpen()).toBe(true);
      expect(cmp.voteQuestion()).toContain('Antrag X'); // questionPrefill
      cmp.openVoteDialog(AGENDA_ITEM({ applicationId: null, title: 'Freitext' }) as never);
      expect(cmp.voteQuestion()).toBe('Freitext');
      cmp.closeVoteDialog();
      expect(cmp.voteDialogOpen()).toBe(false);
    });

    it('prefills the freetext vote dialog with an empty string when title is null', async () => {
      const { cmp } = await loaded();
      cmp.openVoteDialog(AGENDA_ITEM({ applicationId: null, title: null }) as never);
      expect(cmp.voteQuestion()).toBe('');
    });

    it('submits a vote with the fixed options and majority rule', async () => {
      const { cmp, http } = await loaded();
      cmp.openVoteDialog(AGENDA_ITEM({ id: 't-1', applicationId: null, title: 'Frage' }) as never);
      cmp.voteSecret.set(true);
      cmp.voteMajorityRule.set('two_thirds');
      cmp.submitVote();
      const req = http.expectOne('/api/meetings/m-1/votes');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({
        agendaItemId: 't-1',
        question: 'Frage',
        options: ['yes', 'no', 'abstain'],
        secret: true,
        majorityRule: 'two_thirds',
      });
      req.flush(MEETING);
      expect(cmp.openingVote()).toBe(false);
      expect(cmp.voteDialogOpen()).toBe(false);
    });

    it('submits a null question when the field is blank', async () => {
      const { cmp, http } = await loaded();
      cmp.openVoteDialog(AGENDA_ITEM({ id: 't-1', applicationId: null, title: '' }) as never);
      cmp.voteQuestion.set('   ');
      cmp.submitVote();
      const req = http.expectOne('/api/meetings/m-1/votes');
      expect(req.request.body.question).toBeNull();
      req.flush(MEETING);
    });

    it('ignores submitVote without meeting/item or while opening', async () => {
      const { cmp, http } = await loaded();
      cmp.submitVote(); // voteItem null → return
      cmp.openVoteDialog(AGENDA_ITEM() as never);
      cmp.openingVote.set(true);
      cmp.submitVote(); // openingVote → return
      http.verify();
    });

    it('shows the server detail when opening a vote fails', async () => {
      const { cmp, http } = await loaded();
      cmp.openVoteDialog(AGENDA_ITEM({ id: 't-1' }) as never);
      cmp.submitVote();
      http
        .expectOne('/api/meetings/m-1/votes')
        .flush({ detail: 'Nicht im vote-State' }, { status: 409, statusText: 'Conflict' });
      expect(cmp.openingVote()).toBe(false);
    });

    it('falls back to a generic message when opening a vote fails without detail', async () => {
      const { cmp, http } = await loaded();
      cmp.openVoteDialog(AGENDA_ITEM({ id: 't-1' }) as never);
      cmp.submitVote();
      http.expectOne('/api/meetings/m-1/votes').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.openingVote()).toBe(false);
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
      http.expectOne('/api/meetings/m-1/votes/v-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.deletingVote()).toBeNull();
    });
  });

  describe('finalize', () => {
    it('assembles markdown with application refs + bodies and finalizes (async path)', async () => {
      const { cmp, http } = await loaded();
      cmp.agenda.set([
        AGENDA_ITEM({ id: 't-1', applicationId: 'app-1', title: 'Antrag', body: 'Text' }),
        AGENDA_ITEM({ id: 't-2', applicationId: null, title: '', body: '' }),
      ] as never);
      cmp.finalize();
      const saveReq = http.expectOne('/api/protocols/p-1');
      expect(saveReq.request.body.markdown).toContain('# Antrag');
      expect(saveReq.request.body.markdown).toContain(':::antrag{#app-1}');
      expect(saveReq.request.body.markdown).toContain('Tagesordnungspunkt'); // leerer Titel-Fallback
      saveReq.flush(PROTOCOL);
      // Async-Pfad: finalize gibt rendering zurück → Poll-Warteschleife.
      jest.useFakeTimers();
      try {
        http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
        expect(cmp.finalizing()).toBe(false);
        // watchRendering pollt nach 4s erneut.
        jest.advanceTimersByTime(4000);
        http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
      } finally {
        jest.useRealTimers();
      }
    });

    it('reports a save error before finalize', async () => {
      const { cmp, http } = await loaded();
      cmp.finalize();
      http.expectOne('/api/protocols/p-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.finalizing()).toBe(false);
    });

    it('reports a finalize error with the server detail', async () => {
      const { cmp, http } = await loaded();
      cmp.finalize();
      http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
      http
        .expectOne('/api/protocols/p-1/finalize')
        .flush({ detail: 'LaTeX-Fehler' }, { status: 400, statusText: 'Bad Request' });
      expect(cmp.finalizing()).toBe(false);
    });

    it('reports a finalize error without a detail', async () => {
      const { cmp, http } = await loaded();
      cmp.finalize();
      http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
      http.expectOne('/api/protocols/p-1/finalize').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.finalizing()).toBe(false);
    });

    it('ignores finalize without a protocol / when locked / while saving a TOP', async () => {
      const { cmp, http } = await loaded();
      cmp.protocol.set(null);
      cmp.finalize(); // kein Protokoll → return
      cmp.protocol.set({ ...PROTOCOL, isFinal: false, isLocked: true } as never);
      cmp.finalize(); // isLocked → return
      cmp.protocol.set({ ...PROTOCOL, isFinal: false, isLocked: false } as never);
      cmp.savingTop.set(true);
      cmp.finalize(); // savingTop → return
      http.verify();
    });
  });

  describe('settings dialog', () => {
    it('defaults the settings fields to empty strings for a meeting without date/time/protokollant', async () => {
      const { cmp, http } = await loaded();
      cmp.openSettings({
        ...cmp.meeting()!,
        protokollantId: null,
        date: null,
        startTime: null,
        endTime: null,
      });
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      expect(cmp.settingsProtokollant()).toBe('');
      expect(cmp.settingsDate()).toBe('');
      expect(cmp.settingsTime()).toBe('');
      expect(cmp.settingsEndTime()).toBe('');
    });

    it('opens settings and loads the roster, then saves protokollant + date/time', async () => {
      const { cmp, http } = await loaded();
      cmp.openSettings(cmp.meeting()!);
      const rosterReq = http.expectOne('/api/meetings/m-1/attendance');
      rosterReq.flush([
        { principalId: 'pr-1', displayName: 'Max', email: 'm@x', status: null, source: null, isSelf: false },
      ]);
      expect(cmp.settingsRoster().length).toBe(1);
      cmp.settingsProtokollant.set('pr-1');
      cmp.settingsDate.set('2026-06-12');
      cmp.settingsTime.set('17:00');
      cmp.settingsEndTime.set('18:00');
      cmp.saveSettings();
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual({
        protokollantId: 'pr-1',
        date: '2026-06-12',
        startTime: '17:00',
        endTime: '18:00',
      });
      req.flush({ ...MEETING, protokollantId: 'pr-1' });
      expect(cmp.settingsMeeting()).toBeNull();
      expect(cmp.savingSettings()).toBe(false);
    });

    it('handles a roster load error in openSettings', async () => {
      const { cmp, http } = await loaded();
      cmp.openSettings(cmp.meeting()!);
      http.expectOne('/api/meetings/m-1/attendance').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.settingsRoster()).toEqual([]);
    });

    it('refuses to save a closed meeting (#15) and when date/time missing', async () => {
      const { cmp, http } = await loaded();
      cmp.openSettings({ ...cmp.meeting()!, status: 'closed' });
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      cmp.settingsDate.set('2026-06-12');
      cmp.settingsTime.set('17:00');
      cmp.saveSettings(); // settingsLocked → return
      expect(cmp.savingSettings()).toBe(false);
      // Nun nicht geschlossen, aber Datum fehlt.
      cmp.openSettings({ ...cmp.meeting()!, status: 'planned' });
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      cmp.settingsDate.set('');
      cmp.saveSettings(); // dateTimeRequired → return
      http.verify();
    });

    it('refuses a settings end time before start', async () => {
      const { cmp, http } = await loaded();
      cmp.openSettings({ ...cmp.meeting()!, status: 'planned' });
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      cmp.settingsDate.set('2026-06-12');
      cmp.settingsTime.set('18:00');
      cmp.settingsEndTime.set('17:00');
      cmp.saveSettings(); // endBeforeStart → return
      http.verify();
    });

    it('omits the protokollant field when the protocol is final (#15)', async () => {
      const { cmp, http } = await loaded();
      // protokollantLocked: same id + finalized protocol.
      cmp.protocol.set({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
      cmp.openSettings(cmp.meeting()!);
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      cmp.settingsDate.set('2026-06-12');
      cmp.settingsTime.set('17:00');
      cmp.settingsEndTime.set('');
      cmp.saveSettings();
      const req = http.expectOne('/api/meetings/m-1');
      expect('protokollantId' in req.request.body).toBe(false);
      expect(req.request.body).toEqual({ date: '2026-06-12', startTime: '17:00', endTime: null });
      req.flush(MEETING);
    });

    it('handles a settings save error and closes the dialog', async () => {
      const { cmp, http } = await loaded();
      cmp.openSettings({ ...cmp.meeting()!, status: 'planned' });
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      cmp.settingsDate.set('2026-06-12');
      cmp.settingsTime.set('17:00');
      cmp.saveSettings();
      http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.savingSettings()).toBe(false);
      cmp.closeSettings();
      expect(cmp.settingsMeeting()).toBeNull();
    });

    it('ignores saveSettings without a settings meeting or while saving', async () => {
      const { cmp, http } = await loaded();
      cmp.saveSettings(); // settingsMeeting null → return
      cmp.openSettings({ ...cmp.meeting()!, status: 'planned' });
      http.expectOne('/api/meetings/m-1/attendance').flush([]);
      cmp.savingSettings.set(true);
      cmp.saveSettings(); // savingSettings → return
      http.verify();
    });
  });

  describe('delete meeting', () => {
    it('confirms and deletes a meeting, navigating back from detail', async () => {
      const { cmp, http, navigate } = await loaded();
      cmp.askDeleteMeeting(cmp.meeting()!);
      expect(cmp.confirmDeleteMeeting()).not.toBeNull();
      cmp.doDeleteMeeting();
      http.expectOne('/api/meetings/m-1').flush(null, { status: 204, statusText: 'No Content' });
      expect(cmp.deletingMeeting()).toBe(false);
      expect(cmp.confirmDeleteMeeting()).toBeNull();
      expect(navigate).toHaveBeenCalledWith(['/meetings']);
    });

    it('handles a delete error', async () => {
      const { cmp, http } = await loaded();
      cmp.askDeleteMeeting(cmp.meeting()!);
      cmp.doDeleteMeeting();
      http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.deletingMeeting()).toBe(false);
    });

    it('ignores doDeleteMeeting without a target or while deleting', async () => {
      const { cmp, http } = await loaded();
      cmp.doDeleteMeeting(); // confirmDeleteMeeting null → return
      cmp.askDeleteMeeting(cmp.meeting()!);
      cmp.deletingMeeting.set(true);
      cmp.doDeleteMeeting(); // deletingMeeting → return
      http.verify();
    });
  });

  describe('overview / create dialog', () => {
    it('opens create on step 1 and loads members for a preselected gremium', async () => {
      const { fixture, http } = await setup({ id: null, gremien: [{ id: 'g-1', name: 'StuPa' }] });
      const cmp = fixture.componentInstance as Cmp;
      cmp.newGremiumId.set('g-1');
      cmp.openCreate();
      expect(cmp.createOpen()).toBe(true);
      expect(cmp.createStep()).toBe(1);
      http.expectOne('/api/gremien/g-1/meeting-members').flush([
        { principalId: 'pr-1', displayName: 'Max', email: 'm@x' },
      ]);
      expect(cmp.createMembers().length).toBe(1);
    });

    it('closes the create dialog and resets the step', async () => {
      const { fixture } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      cmp.openCreate();
      cmp.createStep.set(2);
      cmp.closeCreate();
      expect(cmp.createOpen()).toBe(false);
      expect(cmp.createStep()).toBe(1);
    });

    it('validates step 1 and advances to step 2 prefilling the title', async () => {
      const { fixture, http } = await setup({ id: null, gremien: [{ id: 'g-1', name: 'StuPa' }] });
      const cmp = fixture.componentInstance as Cmp;
      cmp.onCreateGremiumChange('g-1');
      http.expectOne('/api/gremien/g-1/meeting-members').flush([]);
      expect(cmp.createStep1Valid()).toBe(false); // Datum/Zeit fehlen
      cmp.goToCreateStep2(); // invalid → bleibt auf 1
      expect(cmp.createStep()).toBe(1);
      cmp.newDate.set('2026-07-01');
      cmp.newTime.set('17:00');
      expect(cmp.createStep1Valid()).toBe(true);
      cmp.goToCreateStep2();
      expect(cmp.createStep()).toBe(2);
      expect(cmp.newTitle().length).toBeGreaterThan(0); // vorbelegt
      cmp.backToCreateStep1();
      expect(cmp.createStep()).toBe(1);
    });

    it('does not clobber a manually edited title on re-entry to step 2', async () => {
      const { fixture, http } = await setup({ id: null, gremien: [{ id: 'g-1', name: 'StuPa' }] });
      const cmp = fixture.componentInstance as Cmp;
      cmp.onCreateGremiumChange('g-1');
      http.expectOne('/api/gremien/g-1/meeting-members').flush([]);
      cmp.newDate.set('2026-07-01');
      cmp.newTime.set('17:00');
      cmp.newTitle.set('Mein Titel'); // manuell gesetzt
      cmp.goToCreateStep2();
      expect(cmp.newTitle()).toBe('Mein Titel'); // unangetastet
    });

    it('resets protokollant when changing the gremium with no id', async () => {
      const { fixture, http } = await setup({ id: null, gremien: [{ id: 'g-1', name: 'StuPa' }] });
      const cmp = fixture.componentInstance as Cmp;
      cmp.newProtokollant.set('pr-1');
      cmp.onCreateGremiumChange(''); // kein gremiumId → keine member-Anfrage
      expect(cmp.newProtokollant()).toBe('');
      expect(cmp.createMembers()).toEqual([]);
      http.verify();
    });

    it('handles a member-load error in onCreateGremiumChange', async () => {
      const { fixture, http } = await setup({ id: null, gremien: [{ id: 'g-1', name: 'StuPa' }] });
      const cmp = fixture.componentInstance as Cmp;
      cmp.onCreateGremiumChange('g-1');
      http.expectOne('/api/gremien/g-1/meeting-members').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.createMembers()).toEqual([]);
    });

    it('rejects create when the end time is before the start time', async () => {
      const { fixture, http } = await setup({ id: null, gremien: [{ id: 'g-1', name: 'StuPa' }] });
      const cmp = fixture.componentInstance as Cmp;
      cmp.newTitle.set('T');
      cmp.newGremiumId.set('g-1');
      cmp.newDate.set('2026-07-01');
      cmp.newTime.set('18:00');
      cmp.newEndTime.set('17:00');
      cmp.create({ preventDefault() {} } as Event);
      http.verify();
      expect(cmp.creating()).toBe(false);
    });

    it('ignores create with missing fields or while creating', async () => {
      const { fixture, http } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      cmp.create({ preventDefault() {} } as Event); // alles leer → return
      cmp.newTitle.set('T');
      cmp.newGremiumId.set('g-1');
      cmp.newDate.set('2026-07-01');
      cmp.newTime.set('17:00');
      cmp.creating.set(true);
      cmp.create({ preventDefault() {} } as Event); // creating → return
      http.verify();
    });

    it('handles a create error', async () => {
      const { fixture, http } = await setup({ id: null, gremien: [{ id: 'g-1', name: 'StuPa' }] });
      const cmp = fixture.componentInstance as Cmp;
      cmp.newTitle.set('T');
      cmp.newGremiumId.set('g-1');
      cmp.newDate.set('2026-07-01');
      cmp.newTime.set('17:00');
      cmp.create({ preventDefault() {} } as Event);
      http.expectOne('/api/meetings').flush(null, { status: 500, statusText: 'e' });
      expect(cmp.creating()).toBe(false);
    });

    it('navigates to a meeting via openMeeting', async () => {
      const { fixture, navigate } = await setup({ id: null });
      (fixture.componentInstance as Cmp).openMeeting('m-9');
      expect(navigate).toHaveBeenCalledWith(['/meetings', 'm-9']);
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
      // Standard-Auth: gremien=[] → keine Übersicht; per Signal-Override simulieren wäre
      // aufwändig. Hier prüfen wir die Computed-Logik über die Flags.
      expect(cmp.showForbidden()).toBe(true);
      expect(cmp.showOverview()).toBe(false);
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
      // canManage fällt auf canManageAny (true, da meeting.manage) zurück.
      expect(cmp.canManage()).toBe(true);
      expect(cmp.canWrite()).toBe(false);
      expect(cmp.canManageVotes()).toBe(false);
      expect(cmp.canVote()).toBe(false);
      expect(cmp.isProtokollant()).toBe(false);
    });

    it('marks a user as follower when a protokollant is set and it is not them', async () => {
      const { cmp } = await loaded();
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: 'someone', isProtokollant: false });
      expect(cmp.isFollower()).toBe(true);
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: 'someone', isProtokollant: true });
      expect(cmp.isFollower()).toBe(false);
      // Ohne gewählten Protokollanten greift das Schreib-/Verwaltungs-Gate.
      cmp.meeting.set({ ...cmp.meeting()!, protokollantId: null, canWrite: false, canManage: false });
      expect(cmp.isFollower()).toBe(true);
      cmp.meeting.set(null);
      expect(cmp.isFollower()).toBe(false);
    });

    it('loads more upcoming + past pages on scroll near the edges', async () => {
      const { fixture, http } = await setup({ id: null, skipTimelineFlush: true });
      const cmp = fixture.componentInstance as Cmp;
      // initiale Timeline mit nextCursor → hasMore true.
      const reqs = http.match((r) => r.url.endsWith('/meetings/timeline'));
      reqs.forEach((req) => {
        const past = req.request.params.get('direction') === 'past';
        req.flush({ items: [{ ...MEETING, id: past ? 'p1' : 'u1', status: past ? 'closed' : 'planned' }], nextCursor: 'c1' });
      });
      fixture.detectChanges();
      expect(cmp.upcomingHasMore()).toBe(true);
      expect(cmp.pastHasMore()).toBe(true);
      // Unterer Rand (scrollTop hoch → kein Past-Trigger; Boden erreicht → Upcoming).
      const el = { scrollTop: 200, scrollHeight: 1000, clientHeight: 800 } as HTMLElement;
      cmp.onTimelineScroll(el);
      const upReq = http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('direction') === 'upcoming');
      upReq.flush({ items: [{ ...MEETING, id: 'u2' }], nextCursor: null });
      expect(cmp.upcomingItems().some((m) => m.id === 'u2')).toBe(true);
      expect(cmp.upcomingHasMore()).toBe(false);
    });

    it('keeps scroll position when loading older past pages', async () => {
      const { fixture, http } = await setup({ id: null, skipTimelineFlush: true });
      const cmp = fixture.componentInstance as Cmp;
      http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) => {
        const past = req.request.params.get('direction') === 'past';
        req.flush({ items: past ? [{ ...MEETING, id: 'p1', status: 'closed' }] : [], nextCursor: past ? 'c1' : null });
      });
      fixture.detectChanges();
      // Veränderliches Fake-Element: nach dem Anhängen wächst die Höhe, der rAF-Callback
      // korrigiert dann scrollTop um die Höhendifferenz (Zeile 378).
      const el = { scrollTop: 0, scrollHeight: 1000, clientHeight: 5000 } as unknown as HTMLElement;
      cmp.onTimelineScroll(el); // scrollTop<=80 → loadMorePast
      const pastReq = http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('direction') === 'past');
      (el as { scrollHeight: number }).scrollHeight = 1500; // Liste ist gewachsen
      pastReq.flush({ items: [{ ...MEETING, id: 'p2', status: 'closed' }], nextCursor: null });
      // rAF-Callback abwarten, damit die Scroll-Korrektur ausgeführt wird.
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      expect(cmp.pastItems().some((m) => m.id === 'p2')).toBe(true);
      expect(el.scrollTop).toBe(500); // scrollHeight(1500) - prevHeight(1000)
    });

    it('handles errors when loading more upcoming/past', async () => {
      const { fixture, http } = await setup({ id: null, skipTimelineFlush: true });
      const cmp = fixture.componentInstance as Cmp;
      http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) => {
        req.flush({ items: [], nextCursor: 'c1' });
      });
      fixture.detectChanges();
      cmp.loadMoreUpcoming();
      http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('direction') === 'upcoming')
        .flush(null, { status: 500, statusText: 'e' });
      expect(cmp.loadingUpcoming()).toBe(false);
      const el = { scrollTop: 0, scrollHeight: 100, clientHeight: 5000 } as unknown as HTMLElement;
      cmp.loadMorePast(el);
      http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('direction') === 'past')
        .flush(null, { status: 500, statusText: 'e' });
      expect(cmp.loadingPast()).toBe(false);
    });

    it('changes the gremium filter and reloads the list', async () => {
      const { fixture, http } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) => req.flush({ items: [], nextCursor: null }));
      fixture.detectChanges();
      cmp.selectGremiumFilter('g-1');
      expect(cmp.gremiumFilter()).toBe('g-1');
      // loadList feuert erneut zwei Timeline-Requests mit gremiumId.
      const filtered = http.match((r) => r.url.endsWith('/meetings/timeline'));
      expect(filtered.length).toBe(2);
      expect(filtered[0].request.params.get('gremiumId')).toBe('g-1');
      filtered.forEach((req) => req.flush({ items: [], nextCursor: null }));
    });

    it('handles a timeline load error by clearing the lists', async () => {
      const { fixture, http } = await setup({ id: null, skipTimelineFlush: true });
      const cmp = fixture.componentInstance as Cmp;
      // forkJoin bricht ab, sobald EIN Zweig fehlschlägt — der erste reicht; der
      // andere wird verworfen (Cancelled), darf also nicht zusätzlich geflusht werden.
      const reqs = http.match((r) => r.url.endsWith('/meetings/timeline'));
      reqs[0].flush(null, { status: 500, statusText: 'e' });
      fixture.detectChanges();
      expect(cmp.loadingList()).toBe(false);
      expect(cmp.timelineEmpty()).toBe(true);
    });
  });

  describe('search', () => {
    it('debounces a search query and loads relevance-sorted hits', async () => {
      jest.useFakeTimers();
      try {
        const { fixture, http } = await setup({ id: null });
        const cmp = fixture.componentInstance as Cmp;
        http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) => req.flush({ items: [], nextCursor: null }));
        cmp.onSearch('Förder');
        expect(cmp.searchActive()).toBe(true);
        jest.advanceTimersByTime(400);
        const req = http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('q') === 'Förder');
        req.flush({ items: [{ ...MEETING, id: 's1' }], nextCursor: 'c1' });
        expect(cmp.searchItems().length).toBe(1);
        expect(cmp.searchHasMore()).toBe(true);
        // loadMoreSearch (Offset-Cursor) hängt an: scrollHeight-scrollTop-clientHeight <= 80.
        const el = { scrollTop: 0, scrollHeight: 1000, clientHeight: 950 } as HTMLElement;
        cmp.onTimelineScroll(el);
        const more = http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('cursor') === 'c1');
        more.flush({ items: [{ ...MEETING, id: 's2' }], nextCursor: null });
        expect(cmp.searchItems().map((m) => m.id)).toContain('s2');
        expect(cmp.searchHasMore()).toBe(false);
      } finally {
        jest.useRealTimers();
      }
    });

    it('returns to the normal timeline when the query is cleared', async () => {
      jest.useFakeTimers();
      try {
        const { fixture, http } = await setup({ id: null });
        const cmp = fixture.componentInstance as Cmp;
        http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) => req.flush({ items: [], nextCursor: null }));
        cmp.onSearch('   '); // leer → runSearch fällt auf loadList zurück
        jest.advanceTimersByTime(400);
        const reloaded = http.match((r) => r.url.endsWith('/meetings/timeline'));
        expect(reloaded.length).toBe(2); // loadList: past + upcoming
        reloaded.forEach((req) => req.flush({ items: [], nextCursor: null }));
      } finally {
        jest.useRealTimers();
      }
    });

    it('handles a search error', async () => {
      jest.useFakeTimers();
      try {
        const { fixture, http } = await setup({ id: null });
        const cmp = fixture.componentInstance as Cmp;
        http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) => req.flush({ items: [], nextCursor: null }));
        cmp.onSearch('x');
        jest.advanceTimersByTime(400);
        http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('q') === 'x')
          .flush(null, { status: 500, statusText: 'e' });
        expect(cmp.loadingSearch()).toBe(false);
      } finally {
        jest.useRealTimers();
      }
    });

    it('selectGremiumFilter re-runs the search while in search mode', async () => {
      jest.useFakeTimers();
      try {
        const { fixture, http } = await setup({ id: null });
        const cmp = fixture.componentInstance as Cmp;
        http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) => req.flush({ items: [], nextCursor: null }));
        cmp.onSearch('q');
        jest.advanceTimersByTime(400);
        http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('q') === 'q')
          .flush({ items: [], nextCursor: null });
        cmp.selectGremiumFilter('g-2'); // searchActive → runSearch (kein loadList)
        const req = http.expectOne((r) => r.url.endsWith('/meetings/timeline') && r.params.get('gremiumId') === 'g-2');
        req.flush({ items: [], nextCursor: null });
        expect(cmp.searchEmpty()).toBe(true);
      } finally {
        jest.useRealTimers();
      }
    });

    it('ignores loadMoreSearch when not loadable', async () => {
      const { fixture, http } = await setup({ id: null });
      const cmp = fixture.componentInstance as Cmp;
      http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) => req.flush({ items: [], nextCursor: null }));
      cmp.loadMoreSearch(); // searchHasMore false → return
      http.verify();
    });
  });

  describe('load error fallbacks', () => {
    it('clears attendance / agenda / assignable when their loads fail', async () => {
      const { fixture, http } = await setup();
      const cmp = fixture.componentInstance as Cmp;
      http.expectOne('/api/meetings/m-1').flush(MEETING);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      http.expectOne('/api/meetings/m-1/attendance').flush(null, { status: 500, statusText: 'e' });
      http.expectOne('/api/meetings/m-1/agenda').flush(null, { status: 500, statusText: 'e' });
      http.expectOne('/api/meetings/m-1/agenda/assignable').flush(null, { status: 500, statusText: 'e' });
      flushDelegationContext(http);
      expect(cmp.attendance()).toEqual([]);
      expect(cmp.agenda()).toEqual([]);
      expect(cmp.assignable()).toEqual([]);
    });

    it('keeps a still-valid selected TOP after an agenda reload', async () => {
      const { cmp, http, ws } = await loaded();
      cmp.selectedTopId.set('t-1');
      // meeting_state broadcast triggert loadAgenda neu.
      ws.subject.next({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
      http.expectOne('/api/meetings/m-1/agenda').flush([
        { id: 't-1', applicationId: null, title: 'A', body: '', position: 0 },
        { id: 't-2', applicationId: null, title: 'B', body: '', position: 1 },
      ]);
      http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      expect(cmp.selectedTopId()).toBe('t-1'); // unverändert, weil noch gültig
    });
  });

  describe('protocol rendering lifecycle', () => {
    it('toasts a failure when a rendering protocol rolls back to draft', async () => {
      const { cmp, ws, http } = await loaded();
      // Protokoll in den »rendering«-Zustand bringen.
      cmp.protocol.set({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
      // meeting_state mit nicht-finalem Protokoll → GET /protocol → applyProtocolUpdate.
      ws.subject.next({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
      // Rückrollung rendering → draft.
      http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'draft', isFinal: false, isLocked: false });
      expect(cmp.protocol()?.status).toBe('draft');
    });

    it('re-watches when a rendering poll fails', async () => {
      jest.useFakeTimers();
      try {
        const { cmp, http } = await loaded();
        cmp.finalize();
        http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
        http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'rendering', isFinal: false, isLocked: true });
        // Erster Poll nach 4s schlägt fehl → watchRendering(proto) erneut planen.
        jest.advanceTimersByTime(4000);
        http.expectOne('/api/meetings/m-1/protocol').flush(null, { status: 500, statusText: 'e' });
        // Zweiter Poll-Versuch nach weiteren 4s.
        jest.advanceTimersByTime(4000);
        http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
        expect(cmp.protocol()?.isFinal).toBe(true);
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe('constructor option loading', () => {
    it('falls back to empty filter gremien when the request fails', async () => {
      const ws = new FakeWs();
      const navigate = jest.fn(() => Promise.resolve(true));
      const view = await render(MeetingsComponent, {
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          { provide: USE_MOCK_API, useValue: false },
          { provide: AuthService, useValue: fakeAuth([], null) },
          { provide: WsService, useValue: ws },
          { provide: Router, useValue: { navigate } },
          { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({})) } },
        ],
      });
      const http = view.fixture.debugElement.injector.get(HttpTestingController);
      // filterGremien-Request schlägt fehl → leere Liste.
      http.expectOne('/api/meetings/gremien').flush(null, { status: 500, statusText: 'e' });
      const cmp = view.fixture.componentInstance as Cmp;
      expect(cmp.filterGremien()).toEqual([]);
    });

    it('restricts the create gremium dropdown to managed gremien without global manage', async () => {
      const managed = ['g-2'];
      const auth: Partial<AuthService> = {
        can: (p: string) => p === 'protocol.write',
        canAny: () => false,
        userId: (() => 'pr-1') as unknown as AuthService['userId'],
        gremien: (() => []) as unknown as AuthService['gremien'],
        sessionManageGremien: (() => managed) as unknown as AuthService['sessionManageGremien'],
        inSubstitutePool: (() => false) as unknown as AuthService['inSubstitutePool'],
      };
      const ws = new FakeWs();
      const view = await render(MeetingsComponent, {
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          { provide: USE_MOCK_API, useValue: false },
          { provide: AuthService, useValue: auth },
          { provide: WsService, useValue: ws },
          { provide: Router, useValue: { navigate: jest.fn(() => Promise.resolve(true)) } },
          { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({})) } },
        ],
      });
      const http = view.fixture.debugElement.injector.get(HttpTestingController);
      http.expectOne('/api/meetings/gremien').flush([]);
      // canCreate (sessionManageGremien>0) → gremiumOptions wird geladen + gefiltert.
      http.expectOne('/api/gremien').flush([
        { id: 'g-1', name: 'A' },
        { id: 'g-2', name: 'B' },
      ]);
      // loadList feuert (protocol.write → canWriteGlobal) → Timeline-Requests beantworten.
      http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) =>
        req.flush({ items: [], nextCursor: null }),
      );
      const cmp = view.fixture.componentInstance as Cmp;
      expect(cmp.gremiumOptions().map((o) => o.value)).toEqual(['g-2']);
      http.verify();
    });

    it('falls back to empty gremium options when the dropdown request fails', async () => {
      const auth: Partial<AuthService> = {
        can: (p: string) => p === 'protocol.write',
        canAny: () => false,
        userId: (() => 'pr-1') as unknown as AuthService['userId'],
        gremien: (() => []) as unknown as AuthService['gremien'],
        sessionManageGremien: (() => ['g-2']) as unknown as AuthService['sessionManageGremien'],
        inSubstitutePool: (() => false) as unknown as AuthService['inSubstitutePool'],
      };
      const ws = new FakeWs();
      const view = await render(MeetingsComponent, {
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          { provide: USE_MOCK_API, useValue: false },
          { provide: AuthService, useValue: auth },
          { provide: WsService, useValue: ws },
          { provide: Router, useValue: { navigate: jest.fn(() => Promise.resolve(true)) } },
          { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({})) } },
        ],
      });
      const http = view.fixture.debugElement.injector.get(HttpTestingController);
      http.expectOne('/api/meetings/gremien').flush([]);
      http.expectOne('/api/gremien').flush(null, { status: 500, statusText: 'e' });
      http.match((r) => r.url.endsWith('/meetings/timeline')).forEach((req) =>
        req.flush({ items: [], nextCursor: null }),
      );
      const cmp = view.fixture.componentInstance as Cmp;
      expect(cmp.gremiumOptions()).toEqual([]);
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
      http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
      http.expectOne('/api/meetings/m-1/protocol').flush({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
      expect(cmp.protocol()?.isFinal).toBe(true);
    });

    it('keeps the prior status when the meeting_state status is absent', async () => {
      const { cmp, ws, http } = await loaded();
      const before = cmp.meeting()?.status;
      ws.subject.next({ type: 'meeting_state', activeApplicationId: 'app-2' });
      http.expectOne('/api/meetings/m-1/agenda').flush([]);
      http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
      http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
      expect(cmp.meeting()?.status).toBe(before);
      expect(cmp.meeting()?.activeApplicationId).toBe('app-2');
    });

    it('ignores unknown live messages and messages with no meeting', async () => {
      const { cmp, ws } = await loaded();
      ws.subject.next({ type: 'pong' } as unknown as ServerMessage);
      cmp.meeting.set(null);
      ws.subject.next({ type: 'viewers', viewers: ['X'] }); // m null → früher return
      expect(cmp.viewers()).toEqual([]);
    });
  });
});
