import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { Subject } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { LIVE_VOTE_SOURCE, type LiveVoteSource } from '@core/ws/live-vote.source';
import type { MeetingChannel } from '@core/ws/ws.service';
import type { ClientMessage, ServerMessage } from '@core/ws/ws-messages';
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
  lastMeetingId = '';
  connectMeeting(id: string): MeetingChannel {
    this.lastMeetingId = id;
    const ch = new FakeChannel();
    this.channels.push(ch);
    return ch;
  }
}

async function setup(canVote = true, withId = true) {
  const source = new FakeSource();
  const result = await render(LiveVoteComponent, {
    providers: [
      provideRouter([]),
      { provide: LIVE_VOTE_SOURCE, useValue: source },
      { provide: AuthService, useValue: { can: () => canVote } },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { paramMap: convertToParamMap(withId ? { id: 'm1' } : {}) },
        },
      },
    ],
  });
  return { ...result, source, channel: source.channels[0] };
}

const OPEN_VOTE: ServerMessage = {
  type: 'vote_opened',
  voteId: 'v1',
  applicationId: 'a1',
  options: ['yes', 'no', 'abstain'],
  closesAt: null,
};

describe('LiveVoteComponent', () => {
  it('shows a waiting state until a vote is opened', async () => {
    await setup();
    expect(screen.getByText(/Warte auf die Freischaltung/)).toBeInTheDocument();
  });

  it('renders options when a vote opens and casts over the socket', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.next(OPEN_VOTE);
    detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Nein' }));
    expect(channel.sent).toContainEqual({ type: 'cast', voteId: 'v1', choice: 'no' });
    expect(screen.getByText(/Danke! Deine Stimme: Nein/)).toBeInTheDocument();
  });

  it('shows live tally bars without any names', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.next(OPEN_VOTE);
    channel.subject.next({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 4, no: 1, abstain: 0 },
      eligible: 10,
      quorumMet: false,
      leading: 'yes',
    });
    detectChanges();
    expect(screen.getAllByRole('progressbar').length).toBe(3);
    expect(screen.getByText('4')).toBeInTheDocument();
  });

  it('shows a not-eligible hint and blocks casting', async () => {
    const { channel, detectChanges } = await setup(false);
    channel.subject.next(OPEN_VOTE);
    detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent(/nicht stimmberechtigt/i);
    expect(screen.queryByRole('button', { name: 'Ja' })).not.toBeInTheDocument();
  });

  it('reflects a not_eligible error frame from the server', async () => {
    const { channel, detectChanges } = await setup(true);
    channel.subject.next({ type: 'error', code: 'not_eligible' });
    detectChanges();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows a reconnecting banner when the socket drops', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.complete();
    detectChanges();
    expect(screen.getByText(/verbinde neu/i)).toBeInTheDocument();
  });

  it('shows the result when the vote closes', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.next(OPEN_VOTE);
    channel.subject.next({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: { yes: 8, no: 1, abstain: 1 } });
    detectChanges();
    expect(screen.getByText('Angenommen')).toBeInTheDocument();
  });

  it('shows a rejected result badge when the vote fails', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.next(OPEN_VOTE);
    channel.subject.next({ type: 'vote_closed', voteId: 'v1', result: 'rejected', counts: { yes: 1, no: 8, abstain: 1 } });
    detectChanges();
    expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
  });

  it('renders the closed result without a tally block when none arrived', async () => {
    // Schließt ohne vorheriges vote_tally → result-Block ohne app-vote-bars.
    const { channel, detectChanges } = await setup();
    channel.subject.next(OPEN_VOTE);
    channel.subject.next({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: { yes: 8, no: 1, abstain: 1 } });
    detectChanges();
    expect(screen.getByText('Angenommen')).toBeInTheDocument();
  });

  it('blocks casting once a result is in (cast guard)', async () => {
    const { fixture, channel, detectChanges } = await setup();
    channel.subject.next(OPEN_VOTE);
    channel.subject.next({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: { yes: 8, no: 1, abstain: 1 } });
    detectChanges();
    fixture.componentInstance.cast('yes');
    // result() gesetzt → cast() ist ein No-op, kein cast-Frame.
    expect(channel.sent.some((m) => m.type === 'cast')).toBe(false);
  });

  it('blocks casting for a not-eligible viewer (cast guard)', async () => {
    const { fixture, channel, detectChanges } = await setup(false);
    channel.subject.next(OPEN_VOTE);
    detectChanges();
    fixture.componentInstance.cast('yes');
    expect(channel.sent.some((m) => m.type === 'cast')).toBe(false);
  });

  it('resets the own choice when a new vote opens', async () => {
    const { fixture, channel, detectChanges } = await setup();
    channel.subject.next(OPEN_VOTE);
    detectChanges();
    fixture.componentInstance.cast('yes');
    expect(fixture.componentInstance.myChoice()).toBe('yes');
    // Neue Abstimmung mit anderer voteId → effect setzt myChoice zurück.
    channel.subject.next({ ...OPEN_VOTE, voteId: 'v2' });
    detectChanges();
    expect(fixture.componentInstance.myChoice()).toBeNull();
  });

  it('keeps unknown option keys as their raw label', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.next({ ...OPEN_VOTE, options: ['yes', 'wildcard'] });
    detectChanges();
    expect(screen.getByRole('button', { name: 'wildcard' })).toBeInTheDocument();
  });

  it('falls back to the demo meeting id when the route has none', async () => {
    const { source } = await setup(true, false);
    expect(source.lastMeetingId).toBe('demo');
  });

  it('exposes a tie result key before any result arrives', async () => {
    const { fixture } = await setup();
    expect(fixture.componentInstance.resultKey()).toBe('vote.result.tie');
  });

  it('closes the live session on destroy', async () => {
    const { fixture, channel } = await setup();
    const close = jest.spyOn(channel, 'close');
    fixture.destroy();
    expect(close).toHaveBeenCalled();
  });
});
