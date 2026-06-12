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
 * Eine offene Live-Vote-Sitzung: hält den Verbindungs-State und die zuletzt
 * empfangenen Frames als Signals und kapselt die Reconnect-/Resync-Logik
 * (api.md §4 »Resilienz«). Beim (Wieder-)Verbinden wird `subscribe` gesendet,
 * damit der Server den aktuellen State nachliefert — so überlebt die UI einen
 * Verbindungsabbruch ohne State-Verlust.
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
  /** Fehlversuche in Folge ohne Server-Antwort. Begrenzt den Reconnect-Sturm. */
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
      // Eine empfangene Nachricht beweist, dass der Server wirklich antwortet →
      // Fehlversuch-Zähler zurücksetzen (sonst zählt ein später Abbruch fälschlich
      // zum Reconnect-Limit eines toten Sockets).
      next: (m) => {
        this.attempts = 0;
        this.handle(m);
      },
      complete: () => this.onClosed(),
      error: () => this.onClosed(),
    });
    this.connection.set('open');
    // Resync nach (Re-)Connect: aktuellen State anfordern (api.md §4).
    this.channel.send({ type: 'subscribe' });
  }

  private handle(m: ServerMessage): void {
    switch (m.type) {
      case 'meeting_state':
        this.meeting.set(m);
        break;
      case 'vote_opened':
        // Neue Abstimmung → alte Tally/Ergebnis/Fehler verwerfen.
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
        // Endstand in die Tally spiegeln, damit Balken/Counts final stehen
        // bleiben (Close-Frame trägt keine eligible/quorum-Felder).
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
        // Abbruch (#12): laufende Abstimmung verschwindet ohne Ergebnis.
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

  /** Stimme über den Live-Kanal abgeben (im Beamer-Modus No-op). */
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
    // Endgültig aufgeben statt endlos „Connection refused“ zu spammen, wenn der
    // Server nicht erreichbar ist (kein Backend/kein Meeting). UI zeigt 'closed'.
    if (this.attempts >= LiveVoteSession.MAX_ATTEMPTS) {
      this.errorCode.set('connection_failed');
      this.connection.set('closed');
      return;
    }
    this.connection.set('reconnecting');
    const delay = Math.min(this.reconnectMs * this.attempts, 15000);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  /** Verbindung endgültig schließen (Component-Destroy) — kein Reconnect mehr. */
  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.channel?.close();
    this.connection.set('closed');
  }
}

/**
 * Factory für `LiveVoteSession`s. Holt die `LiveVoteSource` (echte WS oder
 * Mock) aus dem DI-Container und reicht sie an die Sitzung durch.
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
