import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Meeting, Protocol } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { EMPTY } from 'rxjs';
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
    session.startMeeting();
    session.meeting.set(M({ status: 'live' }));
    session.startMeeting();
    session.meeting.set(M({ protokollantId: null }));
    session.startMeeting();
    http.verify();
    expect(toasts()).toContain('Bitte zuerst die Protokollführung zuweisen, dann die Sitzung starten.');
  });

  /**
   * The early open sends no PATCH, and the page reads the meeting again for a fresh window. When
   * the dialog confirms, the PATCH carries confirmEarly and the question closes.
   */
  it('refuses an open before the window and asks before an early open', () => {
    const { http, session, toasts } = setup();
    const at = (min: number): string => new Date(Date.now() + min * 60_000).toISOString();
    session.meeting.set(M({ opensAt: at(60), confirmUntil: at(110) }));
    session.startMeeting();
    http.expectOne({ method: 'GET', url: '/api/meetings/m-1' }).flush({ id: 'm-1', title: 'x', status: 'planned', opensAt: at(60), votes: [], createdAt: 'x' });
    http.verify();
    expect(toasts()).toContain('Die Sitzung lässt sich noch nicht eröffnen.');
    expect(session.earlyOpenAsk()).toBe(false);

    session.meeting.set(M({ opensAt: at(-20), confirmUntil: at(30) }));
    session.startMeeting();
    http.verify();
    expect(session.earlyOpenAsk()).toBe(true);
    session.startMeeting(true);
    expect(session.earlyOpenAsk()).toBe(false);
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.body).toEqual({ status: 'live', confirmEarly: true });
    req.flush({ id: 'm-1', title: 'x', status: 'live', protocolId: null, votes: [], createdAt: 'x' });
    expect(session.meeting()?.status).toBe('live');
  });

  /** The toast shows the German text, not the English server detail. */
  it('asks when the server still finds the open early, and maps a too-early refusal', () => {
    const { http, session, toasts } = setup();
    session.meeting.set(M());
    session.startMeeting();
    http
      .expectOne('/api/meetings/m-1')
      .flush({ code: 'early_open_unconfirmed', detail: 'early' }, { status: 409, statusText: 'Conflict' });
    expect(session.earlyOpenAsk()).toBe(true);

    session.startMeeting(true);
    http
      .expectOne('/api/meetings/m-1')
      .flush({ code: 'meeting_too_early', detail: 'too early' }, { status: 409, statusText: 'Conflict' });
    http.expectOne('/api/meetings/m-1').flush({ id: 'm-1', title: 'x', status: 'planned', votes: [], createdAt: 'x' });
    expect(session.earlyOpenAsk()).toBe(false);
    expect(toasts()).toContain('Die Sitzung lässt sich noch nicht eröffnen.');
    expect(toasts().some((t) => t.includes('too early'))).toBe(false);
  });

  it('finalizes only a closed meeting, and the close is no part of it', () => {
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

  /** A second publish while the first one runs is ignored. */
  it('holds a final protocol back and publishes it again', () => {
    const { http, session, toasts } = setup();
    session.setPublicWithheld(true);
    http.verify();
    session.protocol.set({ ...PROTOCOL, status: 'final', isFinal: true, isLocked: true });
    session.setPublicWithheld(true);
    session.setPublicWithheld(false);
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

  /** A member receives no code and no requests, so the meeting keeps its values. */
  it('passes the lead events to the guest list and takes the guest counts', () => {
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
    session['onLive']({ type: 'guest_counts', admittedGuests: 4 });
    expect(session.meeting()).toEqual(
      expect.objectContaining({ publicJoin: true, guestsMode: 'watch', joinCode: '7KQ4MP', admittedGuests: 4, pendingGuests: 1 }),
    );
    session['onLive']({ type: 'vote_tally', voteId: 'v-1', counts: {}, eligible: 0, quorumMet: true, leading: null, presentMembers: 19, presentGuests: 7 });
    expect(session.meeting()?.votes[0]).toEqual(expect.objectContaining({ presentMembers: 19, presentGuests: 7 }));
    http.match(() => true).forEach((r) => r.flush([]));
  });
  /** When the user opens another meeting meanwhile, the answer is dropped. */
  it('reloads the meeting quietly for a lot or a runoff, and only the open one', () => {
    const { http, session } = setup();
    session.reloadMeeting();
    http.verify();
    session.meeting.set(M({ status: 'live' }));
    session.reloadMeeting();
    http.expectOne('/api/meetings/m-1').flush({ ...M({ status: 'live', title: 'Neu' }), createdAt: 'x' });
    expect(session.meeting()?.title).toBe('Neu');
    session.reloadMeeting();
    session.meeting.set(M({ id: 'm-2', title: 'Andere' }));
    http.expectOne('/api/meetings/m-1').flush({ ...M({ title: 'Alt' }), createdAt: 'x' });
    expect(session.meeting()?.title).toBe('Andere');
    session.reloadMeeting();
    http.expectOne('/api/meetings/m-2').flush(null, { status: 500, statusText: 'Error' });
    expect(session.meeting()?.title).toBe('Andere');
  });

  it('takes the election of an opened vote, its result and the drawn lot from the live channel', () => {
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
  /**
   * Without a move the look at another item stays. When the protokollant moves the room, the own
   * selection stays.
   */
  it('moves a viewer to the item of the room, but not the protokollant', () => {
    const { http, session } = setup();
    const agenda = TestBed.inject(MeetingAgendaService);
    const rows = [{ id: 't-1' }, { id: 't-2' }, { id: 't-3' }] as never;
    const flushReads = () =>
      http.match(() => true).forEach((r) => r.flush(r.request.url.endsWith('/agenda') ? rows : { ...M({ status: 'live' }), createdAt: 'x' }));
    session.meeting.set(M({ status: 'live', currentAgendaItemId: 't-1', isProtokollant: false }));
    agenda.agenda.set(rows);
    agenda.selectedTopId.set('t-3');
    session['onLive']({ type: 'meeting_state', status: 'live', activeApplicationId: null, currentAgendaItemId: 't-2' });
    expect(agenda.selectedTopId()).toBe('t-2');
    flushReads();
    session.meeting.set(M({ status: 'live', currentAgendaItemId: 't-2', isProtokollant: false }));
    agenda.selectedTopId.set('t-3');
    session['onLive']({ type: 'meeting_state', status: 'live', activeApplicationId: null, currentAgendaItemId: 't-2' });
    expect(agenda.selectedTopId()).toBe('t-3');
    flushReads();
    session.meeting.set(M({ status: 'live', currentAgendaItemId: 't-2', isProtokollant: true }));
    agenda.selectedTopId.set('t-1');
    session['onLive']({ type: 'meeting_state', status: 'live', activeApplicationId: null, currentAgendaItemId: 't-3' });
    expect(agenda.selectedTopId()).toBe('t-1');
    flushReads();
  });

  /**
   * The vote opens while the read of the meeting runs. The second read is after the event and is
   * taken.
   */
  it('does not let a read that predates a vote event undo it', () => {
    const { http, session } = setup();
    const open = { id: 'v-1', status: 'open', agendaItemId: 't-1' } as Meeting['votes'][number];
    session.meeting.set(M({ status: 'live', currentAgendaItemId: 't-1' }));
    session['onLive']({ type: 'meeting_state', status: 'live', activeApplicationId: null, currentAgendaItemId: 't-1' });
    session['onLive']({ type: 'vote_opened', voteId: 'v-1', applicationId: null, agendaItemId: 't-1', options: [], closesAt: null });
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    http.expectOne('/api/meetings/m-1').flush({ ...M({ status: 'live', votes: [] }), createdAt: 'x' });
    expect(session.meeting()?.votes.map((v) => v.id)).toEqual(['v-1']);
    http.expectOne('/api/meetings/m-1').flush({ ...M({ status: 'live', title: 'Neu', votes: [open] }), createdAt: 'x' });
    expect(session.meeting()?.title).toBe('Neu');
    expect(session.meeting()?.votes).toEqual([expect.objectContaining(open)]);
    http.verify();
  });

  it('keeps the votes of the events when every read is older', () => {
    const { http, session } = setup();
    session.meeting.set(M({ status: 'live', votes: [{ id: 'v-1', status: 'open' } as Meeting['votes'][number]] }));
    session['onLive']({ type: 'meeting_state', status: 'live', activeApplicationId: null });
    http.expectOne('/api/meetings/m-1/agenda').flush([]);
    for (let i = 0; i < 3; i++) {
      session['onLive']({ type: 'vote_tally', voteId: 'v-1', counts: { yes: i + 1 }, eligible: 5, quorumMet: true, leading: 'yes', cast: i + 1 });
      http.expectOne('/api/meetings/m-1').flush({ ...M({ status: 'live', title: `Lesung ${i}`, votes: [] }), createdAt: 'x' });
    }
    expect(session.meeting()?.title).toBe('Lesung 2');
    expect(session.meeting()?.votes[0]).toEqual(expect.objectContaining({ id: 'v-1', voted: 3 }));
    http.verify();
  });
});

describe('MeetingSessionService live body draft', () => {
  type Sent = { type: string; agendaItemId?: string; body?: string; seq?: number };
  function live(over: Partial<Meeting> = {}) {
    const ctx = setup();
    const sent: Sent[] = [];
    ctx.session['channel'] = {
      messages$: EMPTY,
      send: (msg: Sent) => sent.push(msg),
      close: () => undefined,
    } as never;
    ctx.session.meeting.set(M({ status: 'live', isProtokollant: true, ...over }));
    return { ...ctx, sent };
  }

  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  /** After a pause the next change goes out at once. */
  it('sends at most one draft per 300 ms, and the last text always goes out', () => {
    const { session, sent } = live();
    session.sendBodyDraft('t-1', 'a');
    expect(sent).toEqual([{ type: 'body_draft', agendaItemId: 't-1', body: 'a', seq: expect.any(Number) }]);
    const first = sent[0].seq!;
    jest.advanceTimersByTime(100);
    session.sendBodyDraft('t-1', 'ab');
    jest.advanceTimersByTime(100);
    session.sendBodyDraft('t-1', 'abc');
    expect(sent).toHaveLength(1);
    jest.advanceTimersByTime(100);
    expect(sent).toHaveLength(2);
    expect(sent[1]).toEqual({ type: 'body_draft', agendaItemId: 't-1', body: 'abc', seq: first + 1 });
    jest.advanceTimersByTime(1000);
    session.sendBodyDraft('t-1', 'abcd');
    expect(sent.map((s) => s.body)).toEqual(['a', 'abc', 'abcd']);
    expect(sent[2].seq).toBe(first + 2);
  });

  it('sends the waiting text of an item before the text of the next item', () => {
    const { session, sent } = live();
    session.sendBodyDraft('t-1', 'a');
    session.sendBodyDraft('t-1', 'ab');
    session.sendBodyDraft('t-2', 'x');
    expect(sent.map((s) => [s.agendaItemId, s.body])).toEqual([['t-1', 'a'], ['t-1', 'ab']]);
    jest.advanceTimersByTime(300);
    expect(sent.map((s) => [s.agendaItemId, s.body])).toEqual([['t-1', 'a'], ['t-1', 'ab'], ['t-2', 'x']]);
  });

  it('sends only as the protokollant of a live meeting with a channel', () => {
    const { session, sent } = live();
    for (const over of [{ isProtokollant: false }, { status: 'planned' as const }, { status: 'closed' as const }]) {
      session.meeting.set(M({ status: 'live', isProtokollant: true, ...over }));
      session.sendBodyDraft('t-1', 'a');
    }
    session.meeting.set(M({ status: 'live', isProtokollant: true }));
    session['channel'] = null;
    session.sendBodyDraft('t-1', 'a');
    session.meeting.set(null);
    session.sendBodyDraft('t-1', 'a');
    expect(sent).toEqual([]);
  });

  /**
   * When nothing waits, a flush sends nothing. A new channel (another meeting) drops a waiting
   * draft too.
   */
  it('drops the waiting draft when the page goes away', () => {
    const { session, sent } = live();
    session.sendBodyDraft('t-1', 'a');
    session.sendBodyDraft('t-1', 'ab');
    session.ngOnDestroy();
    jest.advanceTimersByTime(1000);
    session['flushDraft']();
    expect(sent.map((s) => s.body)).toEqual(['a']);
    session.sendBodyDraft('t-1', 'b');
    session.sendBodyDraft('t-1', 'bc');
    session['connectLive']('m-1');
    jest.advanceTimersByTime(1000);
    expect(sent.map((s) => s.body)).toEqual(['a', 'b']);
  });

  const draft = (seq: number, body: string, agendaItemId = 't-1') =>
    ({ type: 'body_draft', agendaItemId, body, seq }) as const;

  /**
   * The sequence counts per item. A meeting state reads the agenda again: the read wins, and a new
   * sequence starts.
   */
  it('shows the draft to a viewer and drops an older frame', () => {
    const { http, session } = setup();
    const agenda = TestBed.inject(MeetingAgendaService);
    session.meeting.set(M({ status: 'live', canWrite: false, isProtokollant: false }));
    agenda.agenda.set([{ id: 't-1', body: 'alt' }, { id: 't-2', body: 'B' }] as never);
    session['onLive'](draft(5, 'neu'));
    expect(agenda.agenda().map((a) => a.body)).toEqual(['neu', 'B']);
    session['onLive'](draft(4, 'älter'));
    expect(agenda.agenda()[0].body).toBe('neu');
    session['onLive'](draft(5, 'gleich'));
    session['onLive'](draft(7, 'neuer'));
    expect(agenda.agenda()[0].body).toBe('neuer');
    session['onLive'](draft(1, 'B2', 't-2'));
    expect(agenda.agenda()[1].body).toBe('B2');
    session['onLive']({ type: 'meeting_state', status: 'live', activeApplicationId: null });
    http.expectOne('/api/meetings/m-1/agenda').flush([{ id: 't-1', body: 'gespeichert' }, { id: 't-2', body: 'B' }]);
    expect(agenda.agenda()[0].body).toBe('gespeichert');
    session['onLive'](draft(1, 'neue Sitzung'));
    expect(agenda.agenda()[0].body).toBe('neue Sitzung');
    http.match(() => true).forEach((r) => r.flush({ ...M({ status: 'live' }), createdAt: 'x' }));
  });

  /** A writer of a live meeting without a protokollant edits the text itself. */
  it('never applies a draft on the client of the protokollant or in an editable editor', () => {
    const { session } = setup();
    const agenda = TestBed.inject(MeetingAgendaService);
    agenda.agenda.set([{ id: 't-1', body: 'eigen' }] as never);
    session.meeting.set(M({ status: 'live', isProtokollant: true }));
    session['onLive'](draft(1, 'fremd'));
    session.meeting.set(M({ status: 'live', protokollantId: null, canWrite: true, isProtokollant: false }));
    session['onLive'](draft(2, 'fremd'));
    expect(agenda.agenda()[0].body).toBe('eigen');
  });
});
