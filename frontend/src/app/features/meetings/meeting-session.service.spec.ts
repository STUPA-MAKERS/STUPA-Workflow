import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Meeting, Protocol } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { MeetingAgendaService } from './meeting-agenda.service';
import { MeetingSessionService } from './meeting-session.service';

const M = (over: Partial<Meeting> = {}): Meeting =>
  ({
    id: 'm-1',
    title: '35. Sitzung',
    status: 'planned',
    protokollantId: 'p-1',
    protocolId: null,
    canWrite: true,
    votes: [],
    ...over,
  }) as Meeting;
const PROTOCOL = { id: 'p-1', meetingId: 'm-1', markdown: '', status: 'draft', isFinal: false, isLocked: false } as Protocol;

function setup() {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      MeetingSessionService,
      MeetingAgendaService,
      { provide: USE_MOCK_API, useValue: true },
      { provide: AuthService, useValue: { can: () => false, isAdmin: () => false } },
      { provide: WsService, useValue: {} },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const session = TestBed.inject(MeetingSessionService);
  const toasts = () => TestBed.inject(ToastService).toasts().map((t) => t.message);
  return { http, session, toasts };
}

describe('MeetingSessionService', () => {
  it('starts a planned meeting and reads the protocol that the start created', () => {
    const { http, session } = setup();
    session.meeting.set(M());
    session.startMeeting();
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.body).toEqual({ status: 'live' });
    req.flush({ id: 'm-1', title: 'x', status: 'live', protocolId: 'p-1', canWrite: true, votes: [], createdAt: 'x' });
    http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
    expect(session.meeting()?.status).toBe('live');
  });

  it('starts only a planned meeting with a minute-taker', () => {
    const { http, session, toasts } = setup();
    session.startMeeting(); // no meeting
    session.meeting.set(M({ status: 'live' }));
    session.startMeeting();
    session.meeting.set(M({ protokollantId: null }));
    session.startMeeting();
    http.verify();
    expect(toasts()).toContain('Bitte zuerst einen Protokollanten zuweisen, dann die Sitzung starten.');
  });

  it('finalizes only a closed meeting, and the close is no part of it (O13)', () => {
    const { http, session } = setup();
    session.meeting.set(M({ status: 'live' }));
    session.protocol.set(PROTOCOL);
    session.finalize();
    http.verify();
    session.meeting.set(M({ status: 'closed' }));
    session.finalize();
    http.expectOne('/api/protocols/p-1').flush({ ...PROTOCOL, markdown: '' });
    http.expectOne('/api/protocols/p-1/finalize').flush({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
    expect(session.protocol()?.isFinal).toBe(true);
  });

});
