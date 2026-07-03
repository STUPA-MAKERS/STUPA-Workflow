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
 * An open live-vote session: holds the connection state and the latest received
 * frames as signals and encapsulates the reconnect/resync logic. On
 * (re)connecting it sends `subscribe` so the server replays the current state —
 * this lets the UI survive a dropped connection without state loss.
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
  /** Consecutive failed attempts with no server response. Caps the reconnect storm. */
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
      // A received message proves the server is actually responding → reset the
      // failed-attempt counter (otherwise a late drop would wrongly count toward
      // the reconnect limit of a dead socket).
      next: (m) => {
        this.attempts = 0;
        this.handle(m);
      },
      complete: () => this.onClosed(),
      error: () => this.onClosed(),
    });
    this.connection.set('open');
    // Resync after (re)connect: request the current state.
    this.channel.send({ type: 'subscribe' });
  }

  private handle(m: ServerMessage): void {
    switch (m.type) {
      case 'meeting_state':
        this.meeting.set(m);
        break;
      case 'vote_opened':
        // New vote → discard the old tally/result/error.
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
        // Mirror the final result into the tally so bars/counts stay final (the
        // close frame carries no eligible/quorum fields).
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
        // Cancellation: the running vote disappears without a result.
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

  /** Cast a ballot over the live channel (no-op in beamer mode). */
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
    // Give up for good instead of endlessly spamming "connection refused" when
    // the server is unreachable (no backend/no meeting). The UI shows 'closed'.
    if (this.attempts >= LiveVoteSession.MAX_ATTEMPTS) {
      this.errorCode.set('connection_failed');
      this.connection.set('closed');
      return;
    }
    this.connection.set('reconnecting');
    const delay = Math.min(this.reconnectMs * this.attempts, 15000);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  /** Close the connection for good (component destroy) — no more reconnects. */
  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.channel?.close();
    this.connection.set('closed');
  }
}

/**
 * Factory for `LiveVoteSession`s. Pulls the `LiveVoteSource` (real WS or mock)
 * from the DI container and passes it to the session.
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
