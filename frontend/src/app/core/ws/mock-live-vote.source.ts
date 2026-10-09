import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';
import type { LiveVoteSource } from './live-vote.source';
import type { MeetingChannel } from './ws.service';
import type { MeetingStateMsg, ServerMessage, VoteOpenedMsg, VoteTallyMsg } from './ws-messages';

/**
 * In-memory live-vote source for mock and harness operation. It simulates a running
 * vote. `subscribe` returns the current state for a reconnect resync. A timer lets
 * ballots trickle in, and a `cast` frame raises the chosen option live.
 *
 * This source invents no protocol. It sends only the frames that `ws-messages.ts`
 * defines. In beamer mode it ignores a `cast` frame, because that stream is read-only.
 */
@Injectable({ providedIn: 'root' })
export class MockLiveVoteSource implements LiveVoteSource {
  /** Interval between the simulated incoming ballots, in milliseconds. */
  tickMs = 2500;

  connectMeeting(_meetingId: string, beamer = false): MeetingChannel {
    const subject = new Subject<ServerMessage>();

    const meeting: MeetingStateMsg = {
      type: 'meeting_state',
      activeApplicationId: 'app-demo',
      status: 'live',
    };
    const vote: VoteOpenedMsg = {
      type: 'vote_opened',
      voteId: 'vote-demo',
      applicationId: 'app-demo',
      options: ['yes', 'no', 'abstain'],
      closesAt: null,
    };
    const tally: VoteTallyMsg = {
      type: 'vote_tally',
      voteId: 'vote-demo',
      counts: { yes: 5, no: 2, abstain: 1 },
      eligible: 12,
      quorumMet: true,
      leading: 'yes',
    };

    const recompute = (): void => {
      let leading: string | null = null;
      let max = -1;
      for (const [opt, n] of Object.entries(tally.counts)) {
        if (n > max) {
          max = n;
          leading = opt;
        }
      }
      const cast = Object.values(tally.counts).reduce((a, b) => a + b, 0);
      tally.leading = leading;
      tally.quorumMet = cast * 2 >= tally.eligible;
    };

    // Like the server: the turnout is always visible, the counts only once every present
    // member voted.
    const emitTally = (): void => {
      const cast = Object.values(tally.counts).reduce((a, b) => a + b, 0);
      const revealed = cast >= tally.eligible;
      subject.next({
        ...tally,
        counts: revealed ? { ...tally.counts } : {},
        leading: revealed ? tally.leading : null,
        cast,
        present: tally.eligible,
        revealed,
      });
    };

    const bump = (choice: string): void => {
      if (!vote.options.includes(choice)) return;
      const cast = Object.values(tally.counts).reduce((a, b) => a + b, 0);
      if (cast >= tally.eligible) return; // do not go above the eligible voter count
      tally.counts[choice] = (tally.counts[choice] ?? 0) + 1;
      recompute();
      emitTally();
    };

    // Simulate ballots that trickle in until all eligible voters have voted. The timer
    // then stops, so no perpetual macrotask keeps the zone awake. If not, Angular never
    // stabilizes and screenshots or SSR hang.
    const rotation = vote.options;
    let i = 0;
    const timer = setInterval(() => {
      const cast = Object.values(tally.counts).reduce((a, b) => a + b, 0);
      if (cast >= tally.eligible) {
        clearInterval(timer);
        return;
      }
      bump(rotation[i++ % rotation.length]);
    }, this.tickMs);

    // Dev hook for screenshots and manual checks: push any frame into the channel, for
    // example a `vote_closed`. Mock mode only, so it never reaches a real backend.
    (globalThis as { __stupaMockLive?: { push(msg: ServerMessage): void } }).__stupaMockLive = {
      push: (msg) => subject.next(msg),
    };

    return {
      messages$: subject.asObservable(),
      send: (msg) => {
        if (msg.type === 'subscribe') {
          subject.next(meeting);
          subject.next({ ...vote, replay: true });
          emitTally();
        } else if (msg.type === 'cast' && !beamer) {
          // An election ballot (F2) is a list; the mock counts its first pick.
          const choice = typeof msg.choice === 'string' ? msg.choice : (msg.choice[0] ?? 'abstain');
          bump(choice);
        }
      },
      close: () => {
        clearInterval(timer);
        subject.complete();
      },
    };
  }
}
