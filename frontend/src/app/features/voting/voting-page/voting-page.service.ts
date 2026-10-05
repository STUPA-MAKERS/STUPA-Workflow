import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { Subject } from 'rxjs';
import type { Uuid, VoteStatus } from '@core/api/models';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';

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
 * - `gremiumNames`: the gremium of each loaded row, by vote id. The detail names it in
 *   its bar when the vote has no meeting to name it.
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
  readonly gremiumNames = signal<ReadonlyMap<Uuid, string>>(new Map());
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
