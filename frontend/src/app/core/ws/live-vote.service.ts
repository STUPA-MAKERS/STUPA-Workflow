import { Injectable, inject, signal } from '@angular/core';
import type { MeetingChannel } from './ws.service';
import { LIVE_VOTE_SOURCE, type LiveVoteSource } from './live-vote.source';
import type {
  MeetingStateMsg,
  ServerMessage,
  VoteClosedMsg,
  VoteOpenedMsg,
  VoteTallyMsg,
} from './ws-messages';

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed';

/**
 * An open live-vote session. It holds the connection state and the last received frames
 * as signals. It also contains the reconnect and resync logic. On each connect it sends
 * `subscribe`, so the server replays the current state. The UI therefore survives a
 * dropped connection without a loss of state.
 */
export class LiveVoteSession {
  readonly connection = signal<ConnectionState>('connecting');
  readonly meeting = signal<MeetingStateMsg | null>(null);
  readonly openVote = signal<VoteOpenedMsg | null>(null);
  readonly tally = signal<VoteTallyMsg | null>(null);
  readonly result = signal<VoteClosedMsg | null>(null);
  readonly errorCode = signal<string | null>(null);

  private channel: MeetingChannel | null = null;
  private closedByUser = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /** Consecutive failed attempts with no server response. This caps the reconnect storm. */
  private attempts = 0;
  private static readonly MAX_ATTEMPTS = 5;

  constructor(
    private readonly source: LiveVoteSource,
    private readonly meetingId: string,
    private readonly beamer: boolean,
    private readonly reconnectMs: number,
  ) {
    this.connect();
  }

  private connect(): void {
    this.channel = this.source.connectMeeting(this.meetingId, this.beamer);
    this.channel.messages$.subscribe({
      // A received message proves that the server responds, so reset the failed-attempt
      // counter. If not, a late drop counts wrongly toward the reconnect limit of a
      // dead socket.
      next: (m) => {
        this.attempts = 0;
        this.handle(m);
      },
      complete: () => this.onClosed(),
      error: () => this.onClosed(),
    });
    this.connection.set('open');
    // Resync after a connect. Ask the server for the current state.
    this.channel.send({ type: 'subscribe' });
  }

  private handle(m: ServerMessage): void {
    switch (m.type) {
      case 'meeting_state':
        this.meeting.set(m);
        break;
      case 'vote_opened':
        this.openVote.set(m);
        this.tally.set(null);
        this.result.set(null);
        this.errorCode.set(null);
        break;
      case 'vote_tally':
        this.tally.set(m);
        break;
      case 'vote_closed': {
        this.result.set(m);
        // Mirror the final result into the tally, so the bars and counts stay final.
        // The close frame carries no eligible or quorum field.
        const prev = this.tally();
        this.tally.set({
          type: 'vote_tally',
          voteId: m.voteId,
          counts: m.counts,
          eligible: prev?.eligible ?? 0,
          quorumMet: prev?.quorumMet ?? false,
          leading: prev?.leading ?? null,
        });
        break;
      }
      case 'vote_cancelled':
        // A cancellation removes the running vote without a result.
        if (this.openVote()?.voteId === m.voteId) {
          this.openVote.set(null);
          this.tally.set(null);
          this.result.set(null);
        }
        break;
      case 'error':
        this.errorCode.set(m.code);
        break;
    }
  }

  /** Cast a ballot over the live channel. In beamer mode this does nothing. */
  cast(choice: string): void {
    const vote = this.openVote();
    if (this.beamer || !vote) return;
    this.channel?.send({ type: 'cast', voteId: vote.voteId, choice });
  }

  private onClosed(): void {
    if (this.closedByUser) {
      this.connection.set('closed');
      return;
    }
    this.attempts += 1;
    // Give up for good instead of an endless series of "connection refused" errors when
    // the server is unreachable (no backend or no meeting). The UI then shows 'closed'.
    if (this.attempts >= LiveVoteSession.MAX_ATTEMPTS) {
      this.errorCode.set('connection_failed');
      this.connection.set('closed');
      return;
    }
    this.connection.set('reconnecting');
    const delay = Math.min(this.reconnectMs * this.attempts, 15000);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  /** Close the connection for good on component destroy. No reconnect follows. */
  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.channel?.close();
    this.connection.set('closed');
  }
}

/**
 * Factory for a `LiveVoteSession`. It takes the `LiveVoteSource` (the real WebSocket or
 * the mock) from the DI container and passes it to the session.
 */
@Injectable({ providedIn: 'root' })
export class LiveVoteService {
  private readonly source = inject(LIVE_VOTE_SOURCE);

  open(
    meetingId: string,
    opts: { beamer?: boolean; reconnectMs?: number } = {},
  ): LiveVoteSession {
    return new LiveVoteSession(
      this.source,
      meetingId,
      opts.beamer ?? false,
      opts.reconnectMs ?? 1500,
    );
  }
}
