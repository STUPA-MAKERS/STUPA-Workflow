import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { Subject } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { LIVE_VOTE_SOURCE, type LiveVoteSource } from '@core/ws/live-vote.source';
import type { MeetingChannel } from '@core/ws/ws.service';
import type { ClientMessage, ServerMessage } from '@core/ws/ws-messages';
import { BeamerComponent } from './beamer.component';

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

async function setup(withId = true) {
  const source = new FakeSource();
  const r = await render(BeamerComponent, {
    providers: [
      { provide: LIVE_VOTE_SOURCE, useValue: source },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { paramMap: convertToParamMap(withId ? { id: 'm1' } : {}) },
        },
      },
    ],
  });
  return { ...r, source, channel: source.channels[0] };
}

const OPEN: ServerMessage = {
  type: 'vote_opened',
  voteId: 'v1',
  applicationId: 'a1',
  options: ['yes', 'no', 'abstain'],
  closesAt: null,
};

describe('BeamerComponent', () => {
  it('opens the read-only beamer stream', async () => {
    const { source } = await setup();
    expect(source.lastBeamer).toBe(true);
  });

  it('shows a waiting state before a vote is opened', async () => {
    await setup();
    expect(screen.getByText(/noch keine Abstimmung/i)).toBeInTheDocument();
  });

  it('renders big live bars, vote count and quorum indicator', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.next(OPEN);
    channel.subject.next({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 5, no: 2, abstain: 1 },
      eligible: 12,
      quorumMet: true,
      leading: 'yes',
    });
    detectChanges();
    expect(screen.getAllByRole('progressbar').length).toBe(3);
    expect(screen.getByText('8 von 12 Stimmen')).toBeInTheDocument();
    expect(screen.getByText(/Quorum:\s*erreicht/)).toBeInTheDocument();
  });

  it('shows the final result when the vote closes', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.next(OPEN);
    channel.subject.next({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 8, no: 2, abstain: 0 },
      eligible: 12,
      quorumMet: true,
      leading: 'yes',
    });
    channel.subject.next({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: { yes: 9, no: 2, abstain: 1 } });
    detectChanges();
    expect(screen.getByText('Endergebnis')).toBeInTheDocument();
    expect(screen.getByText('Angenommen')).toBeInTheDocument();
    expect(screen.getByText('12 von 12 Stimmen')).toBeInTheDocument();
  });

  it('never sends cast frames (read-only)', async () => {
    const { channel } = await setup();
    expect(channel.sent.every((m) => m.type !== 'cast')).toBe(true);
  });

  it('subscribes for resync on open', async () => {
    const { channel } = await setup();
    expect(channel.sent).toContainEqual({ type: 'subscribe' });
  });

  it('falls back to the demo meeting id when the route has none', async () => {
    const { source } = await setup(false);
    expect(source.lastMeetingId).toBe('demo');
  });

  it('reports zero cast count and a tie result key before any tally arrives', async () => {
    const { fixture } = await setup();
    // Kein Tally → castCount() ist 0; kein Ergebnis → resultKey() fällt auf tie.
    expect(fixture.componentInstance.castCount()).toBe(0);
    expect(fixture.componentInstance.resultKey()).toBe('vote.result.tie');
  });

  it('shows a rejected result when the vote fails', async () => {
    const { channel, detectChanges } = await setup();
    channel.subject.next(OPEN);
    channel.subject.next({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 1, no: 5, abstain: 0 },
      eligible: 12,
      quorumMet: false,
      leading: 'no',
    });
    channel.subject.next({ type: 'vote_closed', voteId: 'v1', result: 'rejected', counts: { yes: 1, no: 5, abstain: 0 } });
    detectChanges();
    expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
    expect(screen.getByText(/Quorum:\s*nicht erreicht/)).toBeInTheDocument();
  });

  it('closes the live session on destroy (no reconnect)', async () => {
    const { fixture, channel } = await setup();
    const close = jest.spyOn(channel, 'close');
    fixture.destroy();
    expect(close).toHaveBeenCalled();
  });
});
