import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
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
  };
}

async function setup(opts: { perms?: string[]; id?: string | null } = {}) {
  const perms = opts.perms ?? ['meeting.manage', 'protocol.write'];
  const id = opts.id === undefined ? 'm-1' : opts.id;
  const ws = new FakeWs();
  const view = await render(MeetingsComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(perms) },
      { provide: WsService, useValue: ws },
      {
        provide: ActivatedRoute,
        useValue: { paramMap: of(convertToParamMap(id ? { id } : {})) },
      },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  return { ...view, http, ws };
}

/** Meeting + (Auto-)Protokoll laden — beide Requests beantworten. */
function flushLoad(http: HttpTestingController): void {
  http.expectOne('/api/meetings/m-1').flush(MEETING);
  http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
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

  it('updates the live preview as the markdown changes', async () => {
    const { http, fixture } = await setup();
    flushLoad(http);
    const textarea = (await screen.findByLabelText('Markdown')) as HTMLTextAreaElement;
    await userEvent.clear(textarea);
    await userEvent.type(textarea, '## Hallo');
    fixture.detectChanges();
    const preview = document.querySelector('.mtg__preview');
    expect(preview?.querySelector('h2')?.textContent).toBe('Hallo');
  });

  it('saves the protocol and then finalizes it', async () => {
    const { http } = await setup();
    flushLoad(http);
    const textarea = (await screen.findByLabelText('Markdown')) as HTMLTextAreaElement;
    await userEvent.type(textarea, ' geändert');

    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    const saveReq = http.expectOne('/api/protocols/p-1');
    expect(saveReq.request.method).toBe('PATCH');
    saveReq.flush({ ...PROTOCOL, markdown: '# Protokoll geändert' });

    await userEvent.click(screen.getByRole('button', { name: /Finalisieren/i }));
    const finReq = http.expectOne('/api/protocols/p-1/finalize');
    expect(finReq.request.method).toBe('POST');
    finReq.flush({
      ...PROTOCOL,
      status: 'final',
      pdfUrl: 'https://example/p.pdf',
      sentAt: '2026-06-12T19:00:00Z',
    });

    expect(await screen.findByText('Final')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /PDF/i })).toHaveAttribute(
      'href',
      'https://example/p.pdf',
    );
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

  it('lets a manager create a meeting when none is loaded', async () => {
    const { http } = await setup({ id: null });
    const input = await screen.findByLabelText('Titel');
    await userEvent.type(input, 'Neue Sitzung');
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung anlegen' }));
    const req = http.expectOne('/api/meetings');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ title: 'Neue Sitzung' });
    req.flush({ ...MEETING, title: 'Neue Sitzung', protocolId: null });
    expect(await screen.findByText('Sitzungssteuerung')).toBeInTheDocument();
  });

  it('closes the session via PATCH status', async () => {
    const { http } = await setup();
    flushLoad(http);
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
    const createBtn = await screen.findByRole('button', { name: 'Protokoll anlegen' });
    await userEvent.click(createBtn);
    const req = http.expectOne('/api/meetings/m-1/protocol');
    expect(req.request.method).toBe('POST');
    req.flush(PROTOCOL);
    expect(await screen.findByLabelText('Markdown')).toBeInTheDocument();
  });

  it('inserts an application snippet at the cursor', async () => {
    const { http } = await setup();
    flushLoad(http);
    const textarea = (await screen.findByLabelText('Markdown')) as HTMLTextAreaElement;
    const before = textarea.value;
    await userEvent.click(screen.getAllByRole('button', { name: /\+ Antrag/i })[0]);
    expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value.length).toBeGreaterThan(
      before.length,
    );
    expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toContain(':::antrag');
  });
});
