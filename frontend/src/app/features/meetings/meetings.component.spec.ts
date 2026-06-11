import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { render, screen } from '@testing-library/angular';
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

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return {
    can: (p: string) => set.has(p),
    canAny: (...p: string[]) => p.some((x) => set.has(x)),
    gremien: (() => []) as unknown as AuthService['gremien'],
  };
}

async function setup(
  opts: {
    perms?: string[];
    id?: string | null;
    gremien?: { id: string; name: string }[];
    meetings?: MeetingOutWire[];
  } = {},
) {
  const perms = opts.perms ?? ['meeting.manage', 'protocol.write'];
  const id = opts.id === undefined ? 'm-1' : opts.id;
  const ws = new FakeWs();
  const navigate = jest.fn(() => Promise.resolve(true));
  const view = await render(MeetingsComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(perms) },
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
  http
    .match((r) => r.url.endsWith('/meetings/timeline') && r.method === 'GET')
    .forEach((req) => {
      const past = req.request.params.get('direction') === 'past';
      const items = (opts.meetings ?? []).filter((m) => (past ? isPast(m) : !isPast(m)));
      req.flush({ items, nextCursor: null });
    });
  return { ...view, http, ws, navigate };
}

/** Meeting + (Auto-)Protokoll + Anwesenheit + Tagesordnung laden — alle Requests beantworten. */
function flushLoad(http: HttpTestingController): void {
  http.expectOne('/api/meetings/m-1').flush(MEETING);
  http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
  http.expectOne('/api/meetings/m-1/attendance').flush([]);
  http.expectOne('/api/meetings/m-1/agenda').flush([]);
  http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
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
    const { http, navigate } = await setup({
      id: null,
      gremien: [{ id: 'g-1', name: 'StuPa' }],
    });
    // Anlegen erfolgt jetzt über einen Dialog (#27): erst öffnen.
    await userEvent.click(screen.getByRole('button', { name: 'Neue Sitzung' }));
    const input = await screen.findByLabelText('Titel');
    await userEvent.type(input, 'Neue Sitzung');
    // Pflicht-Gremium wählen (#68) — sonst bleibt »Sitzung anlegen« gesperrt.
    await userEvent.selectOptions(screen.getByLabelText(/Gremium/), 'g-1');
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung anlegen' }));
    const req = http.expectOne('/api/meetings');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ title: 'Neue Sitzung', gremiumId: 'g-1', date: null, startTime: null });
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

  it('creates the protocol on demand when none exists yet', async () => {
    const { http } = await setup();
    http.expectOne('/api/meetings/m-1').flush({ ...MEETING, protocolId: null });
    http.expectOne('/api/meetings/m-1/attendance').flush([]);
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
    const createBtn = await screen.findByRole('button', { name: 'Protokoll anlegen' });
    await userEvent.click(createBtn);
    const req = http.expectOne('/api/meetings/m-1/protocol');
    expect(req.request.method).toBe('POST');
    req.flush(PROTOCOL);
    // Ohne TOP zeigt der Editor den Hinweis (kein einzelnes Markdown-Feld mehr).
    expect(await screen.findByText(/Wähle links einen TOP/i)).toBeInTheDocument();
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
    const select = await screen.findByLabelText(/Protokollant/i);
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
});
