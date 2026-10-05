import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { fireEvent, render, screen } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import type { AgendaItem, Meeting, MeetingVote, Vote } from '@core/api/models';
import { ThemeService } from '@core/theme/theme.service';
import { LIVE_VOTE_SOURCE, type LiveVoteSource } from '@core/ws/live-vote.source';
import type { MeetingChannel } from '@core/ws/ws.service';
import type { ClientMessage, ServerMessage } from '@core/ws/ws-messages';
import { BEAMER_IDLE_MS, BeamerComponent } from './beamer.component';

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
  lastBeamer = false;
  lastMeetingId = '';
  connectMeeting(id: string, beamer = false): MeetingChannel {
    this.lastBeamer = beamer;
    this.lastMeetingId = id;
    const ch = new FakeChannel();
    this.channels.push(ch);
    return ch;
  }
}

const AGENDA: AgendaItem[] = [
  { id: 'ag-2', applicationId: null, title: 'Haushalt', position: 1 },
  { id: 'ag-1', applicationId: null, title: 'Begrüßung', position: 0 },
  { id: 'ag-3', applicationId: null, title: null, position: 2 },
];

function meeting(over: Partial<Meeting> = {}): Meeting {
  return {
    id: 'm1',
    title: '34. Sitzung',
    currentAgendaItemId: 'ag-2',
    votes: [] as MeetingVote[],
    ...over,
  } as Meeting;
}

function vote(over: Partial<Vote> = {}): Vote {
  return {
    id: 'v1',
    applicationId: null,
    meetingId: 'm1',
    agendaItemId: 'ag-2',
    question: 'Wird der Haushalt beschlossen?',
    eligibleGroup: 'g1',
    config: { options: ['yes', 'no', 'abstain'], majorityRule: 'simple', quorum: { type: 'count', value: 12 } },
    status: 'open',
    opensAt: null,
    closesAt: null,
    result: null,
    secret: false,
    tally: { counts: {}, eligible: 19, voted: 4, present: 19, revealed: false, quorumMet: false, leading: null },
    ...over,
  };
}

const OPEN: ServerMessage = {
  type: 'vote_opened',
  voteId: 'v1',
  applicationId: null,
  options: ['yes', 'no', 'abstain'],
  closesAt: null,
};

async function setup(
  opts: { id?: string | null; meeting?: Meeting; votes?: Vote[]; from?: string } = {},
) {
  const source = new FakeSource();
  const votes = [...(opts.votes ?? [vote()])];
  const api = {
    getMeeting: jest.fn(() => of(opts.meeting ?? meeting())),
    listAgenda: jest.fn(() => of(AGENDA)),
    getVote: jest.fn((id: string) => {
      const next = votes.length > 1 ? votes.shift()! : votes[0];
      return next ? of({ ...next, id }) : throwError(() => new Error('gone'));
    }),
  };
  const id = opts.id === undefined ? 'm1' : opts.id;
  const view = await render(BeamerComponent, {
    providers: [
      provideRouter([]),
      { provide: LIVE_VOTE_SOURCE, useValue: source },
      { provide: ApiClient, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: {
            paramMap: convertToParamMap(id ? { id } : {}),
            queryParamMap: convertToParamMap(opts.from ? { from: opts.from } : {}),
          },
        },
      },
    ],
  });
  const channel = source.channels[0];
  const push = (msg: ServerMessage) => {
    channel.subject.next(msg);
    view.fixture.detectChanges();
  };
  return { ...view, source, channel, api, push };
}

describe('BeamerComponent', () => {
  afterEach(() => localStorage.clear());

  it('follows the read-only beamer stream and turns the page dark while it shows', async () => {
    const { source, fixture } = await setup();
    const theme = fixture.debugElement.injector.get(ThemeService);
    expect(source.lastBeamer).toBe(true);
    expect(source.lastMeetingId).toBe('m1');
    expect(theme.resolved()).toBe('dark');
    fixture.destroy();
    expect(theme.resolved()).toBe('light');
  });

  it('keeps a theme that the person chose', async () => {
    localStorage.setItem('ap.theme', 'light');
    const { fixture } = await setup();
    expect(fixture.debugElement.injector.get(ThemeService).resolved()).toBe('light');
  });

  it('shows the item of the room while no vote runs', async () => {
    const { api } = await setup();
    expect(api.getMeeting).toHaveBeenCalledWith('m1', { quiet: true });
    expect(screen.getByRole('heading', { name: 'TOP 2 · Haushalt' })).toBeInTheDocument();
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
    expect(screen.getByText('34. Sitzung')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Beamer-Ansicht verlassen' })).toHaveAttribute('href', '/meetings/m1');
  });

  it('names an item without a title, and shows no item that is not on the agenda', async () => {
    const { push } = await setup();
    push({ type: 'meeting_state', activeApplicationId: null, currentAgendaItemId: 'ag-3', status: 'live' });
    expect(screen.getByRole('heading', { name: 'TOP 3 · Unbenannter TOP' })).toBeInTheDocument();
    push({ type: 'meeting_state', activeApplicationId: null, currentAgendaItemId: 'ag-x', status: 'live' });
    expect(screen.queryByText('Jetzt')).toBeNull();
  });

  it('goes back to the voting overview without a meeting', async () => {
    const { source } = await setup({ id: null });
    expect(source.lastMeetingId).toBe('demo');
    expect(screen.getByRole('link', { name: 'Beamer-Ansicht verlassen' })).toHaveAttribute('href', '/voting');
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
  });

  it('reads the meeting again on a new state of the room, but not on the first one', async () => {
    const { push, api } = await setup();
    push({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
    push({ type: 'meeting_state', activeApplicationId: null, currentAgendaItemId: 'ag-1', status: 'live' });
    expect(api.getMeeting).toHaveBeenCalledTimes(2);
    expect(api.listAgenda).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('heading', { name: 'TOP 1 · Begrüßung' })).toBeInTheDocument();
  });

  it('shows the turnout of an open vote and no tally while the counts are hidden', async () => {
    const { push, api, container } = await setup();
    push(OPEN);
    expect(api.getVote).toHaveBeenCalledWith('v1', { quiet: true });
    expect(screen.getByRole('heading', { name: 'Wird der Haushalt beschlossen?' })).toBeInTheDocument();
    expect(container.querySelector('.bm__big')?.textContent?.trim()).toBe('4');
    expect(container.querySelector('.bm__warn')?.textContent?.trim()).toBe('Quorum 12 · noch nicht erreicht');
    // The turnout grows with each ballot; the counts stay hidden.
    push({ type: 'vote_tally', voteId: 'v1', counts: {}, eligible: 19, cast: 14, present: 19, revealed: false, quorumMet: true, leading: null });
    expect(container.querySelector('.bm__big')?.textContent?.trim()).toBe('14');
    expect(container.querySelector('.bm__warn')).toBeNull();
    expect(container.querySelector('app-vote-bars')).toBeNull();
    // A frame of another vote changes nothing.
    push({ type: 'vote_tally', voteId: 'other', counts: {}, eligible: 19, cast: 1, present: 19, revealed: false, quorumMet: true, leading: null });
    expect(container.querySelector('.bm__big')?.textContent?.trim()).toBe('4');
  });

  it('shows the counts once every present member voted', async () => {
    const { push } = await setup();
    push(OPEN);
    push({ type: 'vote_tally', voteId: 'v1', counts: { yes: 15, no: 2, abstain: 2 }, eligible: 19, cast: 19, present: 19, revealed: true, quorumMet: true, leading: 'yes' });
    expect(screen.getByRole('img', { name: 'Ja: 15 Stimmen, 79 %' })).toBeInTheDocument();
  });

  it('shows the counts of a read that revealed them', async () => {
    const { push } = await setup({
      votes: [vote({ tally: { counts: { yes: 2, no: 1, abstain: 0 }, eligible: 3, voted: 3, present: 3, revealed: true, quorumMet: true, leading: 'yes' } })],
    });
    push(OPEN);
    expect(screen.getByRole('img', { name: 'Ja: 2 Stimmen, 67 %' })).toBeInTheDocument();
  });

  it('shows the result of the close frame, then the result of the read', async () => {
    const closed = vote({
      status: 'closed',
      result: 'passed',
      tally: { counts: { yes: 15, no: 3, abstain: 2 }, eligible: 20, voted: 21, present: 0, revealed: true, quorumMet: true, leading: 'yes' },
    });
    const { push, api, container } = await setup({ votes: [vote(), vote(), closed] });
    push(OPEN);
    push({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: { yes: 15, no: 3, abstain: 2 } });
    expect(api.getVote).toHaveBeenCalledTimes(2);
    // The second read still says open (the server was slow): the frame stands in.
    expect(container.querySelector('.bm__result')?.textContent).toContain('Angenommen');
    expect(screen.getByText('Einfache Mehrheit · Quorum erreicht · 20 Stimmen')).toBeInTheDocument();
  });

  it('shows the read result after the close', async () => {
    const closed = vote({
      status: 'closed',
      result: 'tie',
      tally: { counts: { yes: 9, no: 9, abstain: 2 }, eligible: 20, voted: 20, present: 0, revealed: true, quorumMet: true, leading: null },
    });
    const { push, container } = await setup({ votes: [vote(), closed] });
    push(OPEN);
    push({ type: 'vote_closed', voteId: 'v1', result: 'tie', counts: { yes: 9, no: 9, abstain: 2 }, failedReason: null });
    expect(container.querySelector('.bm__result')?.textContent).toContain('Abgelehnt');
    expect(screen.getByText('Einfache Mehrheit nicht erreicht · Quorum erreicht · 20 Stimmen')).toBeInTheDocument();
  });

  it('takes the reason of the close frame', async () => {
    const { push } = await setup();
    push(OPEN);
    push({ type: 'vote_closed', voteId: 'v1', result: 'rejected', counts: { yes: 1 }, failedReason: 'quorum' });
    expect(screen.getByText('Einfache Mehrheit · Quorum nicht erreicht · 1 Stimme')).toBeInTheDocument();
  });

  it('ignores a read that arrives after the read of a newer vote', async () => {
    const { push, api, fixture } = await setup();
    const reads: { id: string; read: Subject<Vote> }[] = [];
    api.getVote.mockImplementation((id: string) => {
      const read = new Subject<Vote>();
      reads.push({ id, read });
      return read;
    });
    push(OPEN);
    // The room closes v1 and opens v2 at once.
    push({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: { yes: 3 } });
    push({ ...OPEN, voteId: 'v2' } as ServerMessage);
    const answer = (id: string, v: Vote) =>
      reads.filter((r) => r.id === id).forEach((r) => r.read.next(v));
    // The read of v2 comes first, the reads of v1 after it.
    answer('v2', vote({ id: 'v2', question: 'Wird der Nachtrag beschlossen?' }));
    answer('v1', vote({ id: 'v1' }));
    fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'Wird der Nachtrag beschlossen?' })).toBeInTheDocument();
  });

  it('goes idle when the vote is cancelled', async () => {
    const { push } = await setup();
    push(OPEN);
    expect(screen.getByRole('heading', { name: 'Wird der Haushalt beschlossen?' })).toBeInTheDocument();
    push({ type: 'vote_cancelled', voteId: 'v1' });
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
  });

  it('shows the last result of the current item from the meeting read', async () => {
    const row = { id: 'c1', agendaItemId: 'ag-2', status: 'closed' } as MeetingVote;
    const closed = vote({
      status: 'closed',
      result: 'rejected',
      question: '',
      tally: { counts: { yes: 1, no: 4, abstain: 0 }, eligible: 5, quorumMet: true, leading: 'no', failedReason: 'majority' },
    });
    const { container, push } = await setup({ meeting: meeting({ votes: [row] }), votes: [closed] });
    expect(container.querySelector('.bm__result')?.textContent).toContain('Abgelehnt');
    // The question falls back to the placeholder; the turnout to the sum of the counts.
    expect(screen.getByRole('heading', { level: 1, name: 'Beschlussfrage' })).toBeInTheDocument();
    expect(screen.getByText('Einfache Mehrheit nicht erreicht · Quorum erreicht · 5 Stimmen')).toBeInTheDocument();
    // The room moves on: the result goes.
    push({ type: 'meeting_state', activeApplicationId: null, currentAgendaItemId: 'ag-1', status: 'live' });
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
  });

  it('shows no cancelled vote', async () => {
    const { push } = await setup({ votes: [vote({ status: 'cancelled' })] });
    push(OPEN);
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
  });

  it('survives a failed read', async () => {
    const { push, api } = await setup({ votes: [] });
    push(OPEN);
    expect(api.getVote).toHaveBeenCalled();
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
  });

  describe('leaving', () => {
    const exitLink = () => screen.getByRole('link', { name: 'Beamer-Ansicht verlassen' });
    const setFullscreen = (el: Element | null, exit: () => Promise<void>) => {
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: el });
      Object.defineProperty(document, 'exitFullscreen', { configurable: true, value: exit });
    };

    afterEach(() => {
      jest.useRealTimers();
      setFullscreen(null, () => Promise.resolve());
    });

    it('goes back to the page that opened the beamer', async () => {
      await setup({ from: '/meetings?sel=m1' });
      expect(exitLink()).toHaveAttribute('href', '/meetings?sel=m1');
    });

    it('ignores an origin that is not an app path', async () => {
      await setup({ from: '//evil.example/x' });
      expect(exitLink()).toHaveAttribute('href', '/meetings/m1');
    });

    it('leaves on Escape, for the origin page', async () => {
      const { fixture } = await setup({ from: '/voting/v1' });
      const router = fixture.debugElement.injector.get(Router);
      const navigate = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(router.serializeUrl(navigate.mock.calls[0][0] as never)).toBe('/voting/v1');
    });

    it('ends a fullscreen mode when it leaves', async () => {
      const exit = jest.fn(() => Promise.reject(new Error('not allowed')));
      setFullscreen(document.body, exit);
      const { fixture } = await setup();
      jest.spyOn(fixture.debugElement.injector.get(Router), 'navigateByUrl').mockResolvedValue(true);
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(exit).toHaveBeenCalledTimes(1);
    });

    it('does not call exitFullscreen outside a fullscreen mode', async () => {
      const exit = jest.fn(() => Promise.resolve());
      setFullscreen(null, exit);
      const { fixture } = await setup();
      jest.spyOn(fixture.debugElement.injector.get(Router), 'navigateByUrl').mockResolvedValue(true);
      fireEvent.click(exitLink());
      expect(exit).not.toHaveBeenCalled();
    });

    it('shows the exit control on a pointer movement and hides it when the pointer rests', async () => {
      const { fixture } = await setup();
      jest.useFakeTimers();
      expect(exitLink()).not.toHaveClass('beamer__exit--shown');
      fireEvent.pointerMove(document);
      fixture.detectChanges();
      expect(exitLink()).toHaveClass('beamer__exit--shown');
      jest.advanceTimersByTime(BEAMER_IDLE_MS - 100);
      fireEvent.pointerMove(document);
      jest.advanceTimersByTime(BEAMER_IDLE_MS - 100);
      fixture.detectChanges();
      expect(exitLink()).toHaveClass('beamer__exit--shown');
      jest.advanceTimersByTime(200);
      fixture.detectChanges();
      expect(exitLink()).not.toHaveClass('beamer__exit--shown');
      fireEvent.pointerMove(document);
      fixture.destroy();
    });
  });
});
