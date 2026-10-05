import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import type { Meeting, MeetingPage, Vote } from '@core/api/models';
import { LIVE_VOTE_SOURCE, type LiveVoteSource } from '@core/ws/live-vote.source';
import type { MeetingChannel } from '@core/ws/ws.service';
import type { ClientMessage, ServerMessage } from '@core/ws/ws-messages';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../testing/meeting-fixtures';
import { RailStatusService } from '../../layout/rail-status.service';
import { LiveVoteComponent } from './live-vote.component';

class FakeChannel implements MeetingChannel {
  readonly subject = new Subject<ServerMessage>();
  readonly messages$ = this.subject.asObservable();
  readonly sent: ClientMessage[] = [];
  send(msg: ClientMessage): void {
    this.sent.push(msg);
  }
  close(): void {
    this.subject.complete();
  }
}
class FakeSource implements LiveVoteSource {
  readonly channels: FakeChannel[] = [];
  readonly ids: string[] = [];
  connectMeeting(id: string): MeetingChannel {
    this.ids.push(id);
    const ch = new FakeChannel();
    this.channels.push(ch);
    return ch;
  }
}

function vote(overrides: Partial<Vote> = {}): Vote {
  return {
    id: 'v1',
    applicationId: 'a1',
    meetingId: 'm1',
    agendaItemId: 'ag3',
    question: 'Soll der Antrag gefördert werden?',
    eligibleGroup: 'g1',
    config: { options: ['yes', 'no', 'abstain'], majorityRule: 'simple' },
    status: 'open',
    opensAt: null,
    closesAt: null,
    result: null,
    secret: false,
    tally: { counts: {}, eligible: 12, voted: 4, present: 12, revealed: false, quorumMet: false, leading: null },
    canCast: true,
    myBallot: { cast: false, choice: null },
    ...overrides,
  };
}

function meeting(overrides: Partial<Meeting> = {}): Meeting {
  return {
    id: 'm1',
    title: '34. Sitzung',
    status: 'live',
    gremiumId: 'g1',
    canVote: true,
    votes: [],
    ...overrides,
  } as Meeting;
}

const NO_DELEGATION: VoteDelegationStatus = {
  blocked: false,
  delegatedToName: null,
  exercising: false,
  delegatedByName: null,
};

async function setup(opts: {
  routeId?: string | null;
  meeting?: Meeting | 'error';
  votes?: Vote[];
  castError?: unknown;
  delegation?: VoteDelegationStatus;
  delegationError?: boolean;
  pages?: MeetingPage[] | 'error';
  sessionManage?: boolean;
} = {}) {
  const source = new FakeSource();
  const votes = [...(opts.votes ?? [vote()])];
  const getVote = jest.fn(() => of(votes.length > 1 ? (votes.shift() as Vote) : votes[0]));
  const getMeeting = jest.fn((id: string) =>
    opts.meeting === 'error'
      ? throwError(() => ({ status: 403 }))
      : of(opts.meeting ?? meeting({ id })),
  );
  const listAgenda = jest.fn(() =>
    of([
      { id: 'ag1', position: 0 },
      { id: 'ag3', position: 2 },
      { id: 'ag2', position: 1 },
    ]),
  );
  const castBallot = opts.castError
    ? jest.fn(() => throwError(() => opts.castError))
    : jest.fn(() => of({ status: 'cast' as const }));
  const pages = opts.pages ?? [];
  const listMeetingsTimeline = jest.fn((o: { cursor?: string | null }) =>
    pages === 'error'
      ? throwError(() => ({ status: 500 }))
      : of(pages[o.cursor ? Number(o.cursor) : 0] ?? { items: [], nextCursor: null }),
  );
  const voteStatus = opts.delegationError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of(opts.delegation ?? NO_DELEGATION));
  const toast = { success: jest.fn(), error: jest.fn() };
  const railStatus = { refresh: jest.fn() };
  const auth = {
    canInGremium: jest.fn(() => opts.sessionManage ?? false),
    canInAnyGremium: jest.fn(() => opts.sessionManage ?? false),
  };
  const routeId = opts.routeId === undefined ? 'm1' : opts.routeId;
  const r = await render(LiveVoteComponent, {
    providers: [
      provideRouter([
        { path: 'meetings', children: [] },
        { path: 'meetings/:id', children: [] },
        { path: 'voting/meeting/:id', children: [] },
        { path: 'voting/beamer/:id', children: [] },
        { path: 'applications/:id', children: [] },
      ]),
      { provide: LIVE_VOTE_SOURCE, useValue: source },
      {
        provide: ApiClient,
        useValue: { getVote, getMeeting, listAgenda, castBallot, listMeetingsTimeline },
      },
      { provide: DelegationsApiService, useValue: { voteStatus } },
      { provide: ToastService, useValue: toast },
      { provide: RailStatusService, useValue: railStatus },
      { provide: AuthService, useValue: auth },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { paramMap: convertToParamMap(routeId ? { id: routeId } : {}) },
        },
      },
    ],
  });
  const channel = () => source.channels[source.channels.length - 1];
  const emit = (msg: ServerMessage) => {
    channel().subject.next(msg);
    r.fixture.detectChanges();
  };
  return {
    ...r,
    source,
    channel,
    emit,
    getVote,
    getMeeting,
    castBallot,
    voteStatus,
    listMeetingsTimeline,
    toast,
    railStatus,
    auth,
  };
}

const OPENED: ServerMessage = {
  type: 'vote_opened',
  voteId: 'v1',
  applicationId: 'a1',
  options: ['yes', 'no', 'abstain'],
  closesAt: null,
};

const own = () => within(screen.getByRole('group', { name: 'Deine Stimme' }));
const confirmButton = () => screen.getByRole('button', { name: /abgeben/ });

describe('LiveVoteComponent', () => {
  it('follows the meeting of the route and waits for a vote', async () => {
    const { source, getMeeting } = await setup();
    expect(source.ids).toEqual(['m1']);
    expect(getMeeting).toHaveBeenCalledWith('m1', { quiet: true });
    expect(screen.getByRole('heading', { level: 1, name: 'Abstimmungen' })).toBeInTheDocument();
    expect(screen.getByText('34. Sitzung')).toBeInTheDocument();
    expect(screen.getByText(/Warte auf die Freischaltung/)).toBeInTheDocument();
  });

  it('shows a vote that opens, with its meeting line and the ballot', async () => {
    const { emit, getVote, voteStatus } = await setup();
    emit(OPENED);
    expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
    expect(voteStatus).toHaveBeenCalledWith('v1');
    expect(screen.getByRole('heading', { level: 2, name: 'Soll der Antrag gefördert werden?' })).toBeInTheDocument();
    expect(screen.getByText('34. Sitzung · TOP 3')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Deine Stimme' })).toBeInTheDocument();
  });

  it('asks for the vote once when the socket repeats it', async () => {
    const { emit, getVote } = await setup();
    emit(OPENED);
    emit({ ...OPENED });
    expect(getVote).toHaveBeenCalledTimes(1);
  });

  it('casts over REST, not over the socket, and reloads the vote', async () => {
    const { emit, castBallot, channel, getVote, railStatus } = await setup();
    emit(OPENED);
    await userEvent.click(own().getByRole('button', { name: 'Ja' }));
    await userEvent.click(confirmButton());
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', false);
    expect(channel().sent.some((m) => m.type === 'cast')).toBe(false);
    expect(screen.getByText('Danke! Deine Stimme: Ja')).toBeInTheDocument();
    expect(railStatus.refresh).toHaveBeenCalled();
    expect(getVote).toHaveBeenCalledTimes(2);
  });

  it('grows the turnout with each tally frame and shows no interim tally', async () => {
    const { emit } = await setup();
    emit(OPENED);
    emit({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 5 },
      eligible: 12,
      quorumMet: true,
      leading: 'yes',
      cast: 9,
      present: 12,
      revealed: false,
    });
    expect(screen.getByText('9 von 12 Anwesenden haben abgestimmt')).toBeInTheDocument();
    expect(screen.getByText(/Zwischenstand sichtbar/)).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: /Ergebnis/ })).not.toBeInTheDocument();
  });

  it('shows the counts once the server reveals them', async () => {
    const { emit } = await setup();
    emit(OPENED);
    emit({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 10, no: 2 },
      eligible: 12,
      quorumMet: true,
      leading: 'yes',
      cast: 12,
      present: 12,
      revealed: true,
    });
    expect(screen.getByRole('list', { name: 'Ergebnis, 12 Stimmen' })).toBeInTheDocument();
  });

  it('keeps the REST turnout for a tally frame without the progress fields', async () => {
    const { emit } = await setup();
    emit(OPENED);
    emit({ type: 'vote_tally', voteId: 'v1', counts: {}, eligible: 12, quorumMet: false, leading: null });
    expect(screen.getByText('4 von 12 Anwesenden haben abgestimmt')).toBeInTheDocument();
  });

  it('ignores a tally frame of another vote', async () => {
    const { emit } = await setup();
    emit(OPENED);
    emit({ type: 'vote_tally', voteId: 'v9', counts: {}, eligible: 12, quorumMet: false, leading: null, cast: 11 });
    expect(screen.getByText('4 von 12 Anwesenden haben abgestimmt')).toBeInTheDocument();
  });

  it('reloads on the close and shows the result; a tie is Abgelehnt', async () => {
    const closed = vote({
      status: 'closed',
      result: 'tie',
      tally: { counts: { yes: 5, no: 5, abstain: 2 }, eligible: 12, voted: 12, present: 0, revealed: true, quorumMet: true, leading: null },
    });
    const { emit, getVote } = await setup({ votes: [vote(), closed] });
    emit(OPENED);
    emit({ type: 'vote_closed', voteId: 'v1', result: 'tie', counts: { yes: 5, no: 5, abstain: 2 } });
    expect(getVote).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /abgeben/ })).not.toBeInTheDocument();
    // A late repeat of the close asks no more.
    emit({ type: 'vote_closed', voteId: 'v1', result: 'tie', counts: {} });
    expect(getVote).toHaveBeenCalledTimes(2);
  });

  it('waits again when the vote is cancelled', async () => {
    const { emit } = await setup();
    emit(OPENED);
    emit({ type: 'vote_cancelled', voteId: 'v1' });
    expect(screen.getByText(/Warte auf die Freischaltung/)).toBeInTheDocument();
  });

  it('shows the next vote that opens', async () => {
    const second = vote({ id: 'v2', question: 'Zweite Frage?' });
    const { emit, getVote } = await setup({ votes: [vote(), second] });
    emit(OPENED);
    emit({ ...OPENED, voteId: 'v2' });
    expect(getVote).toHaveBeenLastCalledWith('v2', { quiet: true });
    expect(screen.getByRole('heading', { name: 'Zweite Frage?' })).toBeInTheDocument();
  });

  it('hides the own row when the meeting says canVote: false', async () => {
    const { emit } = await setup({ meeting: meeting({ canVote: false }) });
    emit(OPENED);
    expect(screen.getByText('Du bist nicht stimmberechtigt.')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Deine Stimme' })).not.toBeInTheDocument();
  });

  it('hides the own row on a not_eligible frame', async () => {
    const { emit } = await setup();
    emit(OPENED);
    emit({ type: 'error', code: 'not_eligible' });
    expect(screen.getByText('Du bist nicht stimmberechtigt.')).toBeInTheDocument();
  });

  it('hides the own row without canCast', async () => {
    const { emit } = await setup({ votes: [vote({ canCast: false })] });
    emit(OPENED);
    expect(screen.queryByRole('group', { name: 'Deine Stimme' })).not.toBeInTheDocument();
  });

  it('keeps the ballot when the meeting cannot load (the server still gates)', async () => {
    const { emit } = await setup({ meeting: 'error' });
    emit(OPENED);
    expect(screen.getByRole('group', { name: 'Deine Stimme' })).toBeInTheDocument();
  });

  it('explains a handed-over voting right', async () => {
    const { emit } = await setup({
      delegation: { ...NO_DELEGATION, blocked: true, delegatedToName: 'Mara Keller' },
    });
    emit(OPENED);
    expect(screen.getByText(/an Mara Keller übertragen/)).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Deine Stimme' })).not.toBeInTheDocument();
  });

  it('names an unknown delegate and an unknown represented member with a placeholder', async () => {
    const { emit } = await setup({ delegation: { ...NO_DELEGATION, blocked: true } });
    emit(OPENED);
    expect(screen.getByText(/an \? übertragen/)).toBeInTheDocument();
  });

  it('adds the represented row and casts it with asDelegation', async () => {
    const { emit, castBallot } = await setup({
      delegation: { ...NO_DELEGATION, exercising: true, delegatedByName: 'Jonas Weber' },
    });
    emit(OPENED);
    const proxy = within(screen.getByRole('group', { name: 'Als Vertretung für Jonas Weber' }));
    await userEvent.click(proxy.getByRole('button', { name: 'Nein' }));
    await userEvent.click(confirmButton());
    expect(castBallot).toHaveBeenCalledWith('v1', 'no', true);
  });

  it('names an unknown represented member with a placeholder', async () => {
    const { emit } = await setup({ delegation: { ...NO_DELEGATION, exercising: true } });
    emit(OPENED);
    expect(screen.getByRole('group', { name: 'Als Vertretung für ?' })).toBeInTheDocument();
  });

  it('restores the represented lock from representedCast', async () => {
    const { emit } = await setup({
      votes: [vote({ representedCast: true })],
      delegation: { ...NO_DELEGATION, exercising: true, delegatedByName: 'Jonas Weber' },
    });
    emit(OPENED);
    expect(screen.getByText('Für Jonas Weber abgegeben.')).toBeInTheDocument();
  });

  it('keeps the page when the delegation lookup fails', async () => {
    const { emit } = await setup({ delegationError: true });
    emit(OPENED);
    expect(screen.getByRole('group', { name: 'Deine Stimme' })).toBeInTheDocument();
  });

  it('locks the ballot on a 409 already_voted', async () => {
    const { emit, toast } = await setup({
      castError: { status: 409, error: { code: 'already_voted' } },
    });
    emit(OPENED);
    await userEvent.click(own().getByRole('button', { name: 'Ja' }));
    await userEvent.click(confirmButton());
    expect(toast.error).toHaveBeenCalledWith('Du hast bereits abgestimmt.');
    expect(screen.getByText('Danke! Deine Stimme ist abgegeben.')).toBeInTheDocument();
  });

  it.each([
    [{ status: 409, error: { code: 'vote_not_open' } }, 'Die Abstimmung ist nicht mehr offen.'],
    [{ status: 403 }, 'Du bist für diese Abstimmung nicht stimmberechtigt.'],
    [{ status: 500, error: { detail: 'Kaputt' } }, 'Kaputt'],
    [{ status: 500 }, 'Stimme konnte nicht gezählt werden.'],
  ])('reports a refused cast %j', async (castError, message) => {
    const { emit, toast } = await setup({ castError });
    emit(OPENED);
    await userEvent.click(own().getByRole('button', { name: 'Ja' }));
    await userEvent.click(confirmButton());
    expect(toast.error).toHaveBeenCalledWith(message);
  });

  it('shows a reconnecting line when the socket drops', async () => {
    const { channel, fixture } = await setup();
    channel().subject.complete();
    fixture.detectChanges();
    expect(screen.getByText(/Verbindung verloren/)).toBeInTheDocument();
  });

  it('falls back to the open vote of the meeting once the socket gave up', async () => {
    const { fixture, getVote } = await setup({
      meeting: meeting({ votes: [{ id: 'v1', status: 'open' } as Meeting['votes'][number]] }),
    });
    fixture.componentInstance.session()?.close();
    fixture.detectChanges();
    expect(screen.getByText('Verbindung geschlossen.')).toBeInTheDocument();
    expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
  });

  it('keeps waiting when the vote cannot load', async () => {
    const { emit, getVote } = await setup();
    getVote.mockReturnValue(throwError(() => ({ status: 500 })));
    emit(OPENED);
    expect(screen.getByText(/Warte auf die Freischaltung/)).toBeInTheDocument();
  });

  it('shows the counts of a tally frame when neither side names the reveal', async () => {
    const t = vote().tally;
    const { emit } = await setup({ votes: [vote({ tally: { ...t, revealed: undefined } })] });
    emit(OPENED);
    emit({ type: 'vote_tally', voteId: 'v1', counts: { yes: 1 }, eligible: 12, quorumMet: false, leading: 'yes' });
    expect(screen.getByRole('list', { name: 'Ergebnis, 1 Stimmen' })).toBeInTheDocument();
  });

  it('sends no ballot and reloads nothing before a vote is shown', async () => {
    const { fixture, castBallot, getVote } = await setup();
    const cmp = fixture.componentInstance;
    cmp.caster('yes', false).subscribe();
    expect(castBallot).toHaveBeenCalledWith('', 'yes', false);
    cmp.onCastDone();
    expect(getVote).not.toHaveBeenCalled();
  });

  it('closes the live session on destroy', async () => {
    const { fixture } = await setup();
    const session = fixture.componentInstance.session();
    fixture.destroy();
    expect(session?.connection()).toBe('closed');
  });

  describe('beamer', () => {
    it('links the beamer for a person who runs the meeting', async () => {
      const { fixture, auth } = await setup({ sessionManage: true });
      const navigate = jest.spyOn(fixture.debugElement.injector.get(Router), 'navigate');
      expect(auth.canInGremium).toHaveBeenCalledWith('g1', 'session.manage');
      await userEvent.click(screen.getByRole('button', { name: 'Beamer-Ansicht' }));
      expect(navigate).toHaveBeenCalledWith(['/voting/beamer', 'm1']);
    });

    it('checks any gremium for a meeting without one', async () => {
      const { auth } = await setup({ sessionManage: true, meeting: meeting({ gremiumId: null }) });
      expect(auth.canInAnyGremium).toHaveBeenCalledWith('session.manage');
    });

    it('offers no beamer to a member, and goBeamer does nothing', async () => {
      const { fixture } = await setup();
      const navigate = jest.spyOn(fixture.debugElement.injector.get(Router), 'navigate');
      expect(screen.queryByRole('button', { name: 'Beamer-Ansicht' })).not.toBeInTheDocument();
      fixture.componentInstance.goBeamer();
      expect(navigate).not.toHaveBeenCalled();
    });
  });

  describe('/voting without a meeting', () => {
    const live = (id: string, canVote = true) => meeting({ id, title: `Sitzung ${id}`, canVote, gremiumName: 'StuPa' });

    it('says so when no meeting runs', async () => {
      const { source } = await setup({ routeId: null, pages: [{ items: [meeting({ status: 'planned' })], nextCursor: null }] });
      expect(source.ids).toEqual([]);
      expect(screen.getByText('Gerade läuft keine Abstimmung.')).toBeInTheDocument();
    });

    it('says so when the timeline fails', async () => {
      await setup({ routeId: null, pages: 'error' });
      expect(screen.getByText('Gerade läuft keine Abstimmung.')).toBeInTheDocument();
    });

    it('follows the one running meeting, also on a later page', async () => {
      const { source, listMeetingsTimeline } = await setup({
        routeId: null,
        pages: [
          { items: [meeting({ status: 'planned' })], nextCursor: '1' },
          { items: [live('m7')], nextCursor: null },
        ],
      });
      expect(listMeetingsTimeline).toHaveBeenCalledTimes(2);
      expect(source.ids).toEqual(['m7']);
    });

    it('picks the one running meeting where the person may vote', async () => {
      const { source } = await setup({
        routeId: null,
        pages: [{ items: [live('m7', false), live('m8')], nextCursor: null }],
      });
      expect(source.ids).toEqual(['m8']);
    });

    it('lists several running meetings', async () => {
      const { source } = await setup({
        routeId: null,
        pages: [{ items: [live('m7'), live('m8'), { ...live('m9'), gremiumName: null }], nextCursor: null }],
      });
      expect(source.ids).toEqual([]);
      const nav = screen.getByRole('navigation', { name: 'Laufende Sitzungen' });
      expect(within(nav).getByRole('link', { name: /Sitzung m7/ })).toHaveAttribute('href', '/voting/meeting/m7');
      expect(within(nav).getAllByRole('link')).toHaveLength(3);
    });

    it('shows the search while it runs', async () => {
      const { fixture } = await setup({ routeId: null, pages: [] });
      fixture.componentInstance.mode.set('resolving');
      fixture.detectChanges();
      expect(screen.getByText('Suche laufende Sitzungen …')).toBeInTheDocument();
    });
  });

  describe('phone (board Telefon-Abstimmen)', () => {
    let restore: () => void;
    beforeEach(() => (restore = matchMediaQueries(MEDIA.phone)));
    afterEach(() => restore());

    it('shows the phone header with the way back to the meeting', async () => {
      const { emit } = await setup();
      emit(OPENED);
      expect(screen.getByRole('link', { name: 'Zurück' })).toHaveAttribute('href', '/meetings/m1');
      expect(screen.getByText('TOP 3 · 34. Sitzung')).toBeInTheDocument();
      expect(document.querySelector('app-ballot')).toHaveClass('ballot--phone');
    });

    it('names the meeting before the vote opens', async () => {
      await setup();
      expect(screen.getAllByText('34. Sitzung').length).toBeGreaterThan(0);
    });

    it('leads back to the meetings when the meeting is not readable', async () => {
      await setup({ meeting: 'error' });
      expect(screen.getByRole('link', { name: 'Zurück' })).toHaveAttribute('href', '/meetings');
    });

    it('names only the meeting when the item is unknown', async () => {
      const { emit } = await setup({ votes: [vote({ agendaItemId: null })] });
      emit(OPENED);
      expect(screen.getAllByText('34. Sitzung').length).toBeGreaterThan(0);
    });
  });
});
