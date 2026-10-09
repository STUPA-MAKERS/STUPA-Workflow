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
import { MeetingGuestsService } from './meeting-guests.service';

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


  it('finalizes a protocol held back from the public page', () => {
    const { http, session } = setup();
    session.meeting.set(M({ status: 'closed' }));
    session.protocol.set(PROTOCOL);
    session.finalize({ publicWithheld: true });
    http.expectOne('/api/protocols/p-1').flush(PROTOCOL);
    const req = http.expectOne('/api/protocols/p-1/finalize');
    expect(req.request.body).toEqual({ publicWithheld: true });
    req.flush({ ...PROTOCOL, status: 'rendering' });
  });

  it('holds a final protocol back and publishes it again', () => {
    const { http, session, toasts } = setup();
    session.setPublicWithheld(true); // no protocol yet
    http.verify();
    session.protocol.set({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
    session.setPublicWithheld(true);
    session.setPublicWithheld(false); // ignored while the first one runs
    const req = http.expectOne('/api/protocols/p-1');
    expect(req.request.body).toEqual({ publicWithheld: true });
    expect(session.publicationSaving()).toBe(true);
    req.flush({ ...PROTOCOL, status: 'final', publicWithheld: true, gremiumProtocolsPublic: true });
    expect(session.protocol()?.publicWithheld).toBe(true);
    expect(toasts()).toContain('Das Protokoll ist nicht mehr öffentlich.');

    session.setPublicWithheld(false);
    http.expectOne('/api/protocols/p-1').flush({ ...PROTOCOL, status: 'final', publicWithheld: false });
    expect(toasts()).toContain('Das Protokoll ist jetzt öffentlich.');

    session.setPublicWithheld(true);
    http
      .expectOne('/api/protocols/p-1')
      .flush({ detail: 'Kein Recht' }, { status: 403, statusText: 'Forbidden' });
    expect(session.publicationSaving()).toBe(false);
    expect(toasts().some((t) => t.startsWith('Aktion fehlgeschlagen.'))).toBe(true);
  });

  it('passes the lead events to the guest list and takes the guest counts (#17)', () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        MeetingSessionService,
        MeetingAgendaService,
        MeetingGuestsService,
        { provide: USE_MOCK_API, useValue: true },
        { provide: AuthService, useValue: { can: () => false, isAdmin: () => false } },
        { provide: WsService, useValue: {} },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const session = TestBed.inject(MeetingSessionService);
    const guests = TestBed.inject(MeetingGuestsService);
    const apply = jest.spyOn(guests, 'apply');
    const sync = jest.spyOn(guests, 'sync');
    session.meeting.set(
      M({
        status: 'live',
        votes: [{ id: 'v-1', status: 'open' } as Meeting['votes'][number]],
        publicJoin: false,
        guestsMode: 'vote',
        joinCode: null,
        admittedGuests: 0,
        pendingGuests: 0,
      }),
    );
    TestBed.tick();
    expect(sync).toHaveBeenCalled();
    const g = { id: 'g-1', number: 1, displayName: 'A', status: 'pending', requestedAt: 'x', decidedAt: null, decidedByName: null, admittedAt: null } as const;
    session['onLive']({ type: 'guest_requested', guest: g });
    session['onLive']({ type: 'guest_updated', guest: { ...g, status: 'admitted' } });
    expect(apply).toHaveBeenCalledTimes(2);
    session['onLive']({ type: 'guest_counts', publicJoin: true, guestsMode: 'watch', joinCode: '7KQ4MP', admittedGuests: 3, pendingGuests: 1 });
    expect(session.meeting()).toEqual(
      expect.objectContaining({ publicJoin: true, guestsMode: 'watch', joinCode: '7KQ4MP', admittedGuests: 3, pendingGuests: 1 }),
    );
    // A member receives no code and no requests: the meeting keeps its values.
    session['onLive']({ type: 'guest_counts', admittedGuests: 4 });
    expect(session.meeting()).toEqual(
      expect.objectContaining({ publicJoin: true, guestsMode: 'watch', joinCode: '7KQ4MP', admittedGuests: 4, pendingGuests: 1 }),
    );
    session['onLive']({ type: 'vote_tally', voteId: 'v-1', counts: {}, eligible: 0, quorumMet: true, leading: null, presentMembers: 19, presentGuests: 7 });
    expect(session.meeting()?.votes[0]).toEqual(expect.objectContaining({ presentMembers: 19, presentGuests: 7 }));
    http.match(() => true).forEach((r) => r.flush([]));
  });
  it('reloads the meeting quietly for a lot or a runoff, and only the open one (F2)', () => {
    const { http, session } = setup();
    session.reloadMeeting(); // no meeting
    http.verify();
    session.meeting.set(M({ status: 'live' }));
    session.reloadMeeting();
    http.expectOne('/api/meetings/m-1').flush({ ...M({ status: 'live', title: 'Neu' }), createdAt: 'x' });
    expect(session.meeting()?.title).toBe('Neu');
    session.reloadMeeting();
    // The user opened another meeting meanwhile: the answer is dropped.
    session.meeting.set(M({ id: 'm-2', title: 'Andere' }));
    http.expectOne('/api/meetings/m-1').flush({ ...M({ title: 'Alt' }), createdAt: 'x' });
    expect(session.meeting()?.title).toBe('Andere');
    session.reloadMeeting();
    http.expectOne('/api/meetings/m-2').flush(null, { status: 500, statusText: 'Error' });
    expect(session.meeting()?.title).toBe('Andere');
  });

  it('takes the election of an opened vote, its result and the drawn lot from the live channel (F2)', () => {
    const { session } = setup();
    const election = { seats: 1, candidates: [{ id: 'c1', name: 'Ada', principalId: null }], secret: true };
    session.meeting.set(
      M({
        status: 'live',
        votes: [
          { id: 'v-1', status: 'draft', secret: true, election, openedAt: '2026-01-01T10:00:00Z' },
          { id: 'v-2', status: 'draft', secret: false },
        ] as unknown as Meeting['votes'],
      }),
    );
    const vote = (id: string) => session.meeting()!.votes.find((v) => v.id === id)!;
    session['onLive']({ type: 'vote_opened', voteId: 'v-1', applicationId: null, options: [], closesAt: null, kind: 'election' });
    expect(vote('v-1')).toEqual(
      expect.objectContaining({ status: 'open', kind: 'election', election, round: 1, secret: true, openedAt: '2026-01-01T10:00:00Z' }),
    );
    const other = { ...election, seats: 2 };
    session['onLive']({
      type: 'vote_opened',
      voteId: 'v-2',
      applicationId: null,
      options: [],
      closesAt: null,
      kind: 'election',
      election: other,
      round: 2,
      secret: true,
    });
    expect(vote('v-2')).toEqual(expect.objectContaining({ election: other, round: 2, secret: true }));
    expect(vote('v-2').openedAt).toBeTruthy();
    const result = { counts: { c1: 3 }, abstentions: 0, ballots: 3, elected: ['c1'], runoff: null, lot: null };
    session['onLive']({ type: 'vote_closed', voteId: 'v-1', result: 'elected', counts: { c1: 3 }, electionResult: result });
    expect(vote('v-1')).toEqual(expect.objectContaining({ status: 'closed', result: 'elected', electionResult: result }));
    const drawn = { ...result, elected: ['c1'], lot: { among: ['c1'], seats: 1, drawn: ['c1'] } };
    session['onLive']({ type: 'vote_lot_drawn', voteId: 'v-2', result: 'elected', electionResult: drawn });
    expect(vote('v-2')).toEqual(expect.objectContaining({ result: 'elected', electionResult: drawn }));
  });
});
