import { DestroyRef, Injectable, NgZone, inject, signal } from '@angular/core';
import { EMPTY, Observable, Subject, filter, fromEvent, interval, merge } from 'rxjs';
import type { Uuid, VoteStatus } from '@core/api/models';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';

/**
 * How often the page reads the votes again while the tab is visible. The socket of a
 * running meeting is faster; the poll catches what has no socket: a poll of a Gremium,
 * a meeting that started after the page loaded, a draft that someone else made.
 */
export const VOTE_POLL_MS = 30_000;

/** The tab is in front (always `true` without a document, a test). */
export function pageVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden';
}

/**
 * One tick every `ms` while the tab is visible, and one at once when the tab comes back
 * to the front. A hidden tab reads nothing.
 *
 * With a zone the timer runs outside Angular and only a tick enters it. A timer inside
 * the zone keeps the app unstable forever, and a stable app is what the service worker
 * waits for before it registers.
 */
export function visibleTicks(zone?: NgZone, ms: number = VOTE_POLL_MS): Observable<void> {
  return new Observable<void>((sub) => {
    const back: Observable<unknown> =
      typeof document === 'undefined' ? EMPTY : fromEvent(document, 'visibilitychange');
    const emit = () => (zone ? zone.run(() => sub.next()) : sub.next());
    const listen = () =>
      merge(interval(ms), back)
        .pipe(filter(() => pageVisible()))
        .subscribe(emit);
    const inner = zone ? zone.runOutsideAngular(listen) : listen();
    return () => inner.unsubscribe();
  });
}

/** A pane changed a vote: a ballot, a delete, or a new state that the socket reported. */
export interface VoteChange {
  id: Uuid;
  kind: 'cast' | 'deleted' | 'updated';
}

/** The vote in the detail pane, as the detail read it last. */
export interface ShownVote {
  id: Uuid;
  meetingId: Uuid | null;
  status: VoteStatus;
}

/**
 * The link between the list pane and the detail pane of the page "Abstimmungen".
 *
 * The list page provides it, so it lives as long as the page, and the routed detail in
 * its outlet finds it. The detail also works without it (a test).
 *
 * - `split`: the list and the detail sit side by side. The detail then is a sheet.
 * - `changes$`: the detail cast a ballot or deleted a vote. The list loads again, so the
 *   row shows "Abgestimmt" or leaves.
 * - `shown`: the vote in the detail with its meeting and status. When a new vote opens
 *   in the meeting of an ended vote in the detail, the list opens the new vote.
 * - `follow(meetingId)`: ONE live-vote channel per meeting for both panes. The list
 *   follows the running meetings (a vote that opens shows at once); the detail follows
 *   the meeting of its vote (the turnout, the close). The service closes every channel
 *   when the page goes away.
 */
@Injectable()
export class VotingPageService {
  private readonly live = inject(LiveVoteService);

  readonly split = signal(false);
  readonly shown = signal<ShownVote | null>(null);

  private readonly changes = new Subject<VoteChange>();
  readonly changes$ = this.changes.asObservable();

  /** The open channels by meeting id. A signal, so the list can watch new ones. */
  readonly sessions = signal<ReadonlyMap<Uuid, LiveVoteSession>>(new Map());

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      for (const session of this.sessions().values()) session.close();
    });
  }

  notify(change: VoteChange): void {
    this.changes.next(change);
  }

  /** The live channel of a meeting. The first call opens it; later calls share it. */
  follow(meetingId: Uuid): LiveVoteSession {
    const known = this.sessions().get(meetingId);
    if (known) return known;
    const session = this.live.open(meetingId);
    this.sessions.update((cur) => new Map(cur).set(meetingId, session));
    return session;
  }
}
