import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';
import type { LiveVoteSource } from './live-vote.source';
import type { MeetingChannel } from './ws.service';
import type { MeetingStateMsg, ServerMessage, VoteOpenedMsg, VoteTallyMsg } from './ws-messages';

/**
 * In-Memory-Live-Vote-Quelle für den Mock-/Harness-Betrieb (T-32, solange das
 * WS-Backend T-16 fehlt). Spielt eine laufende Abstimmung nach: `subscribe`
 * liefert den aktuellen State (Reconnect-Resync), ein Timer lässt Stimmen
 * eintrudeln, und `cast`-Frames erhöhen die gewählte Option live.
 *
 * **Kein** Protokoll erfunden: gesendet werden ausschließlich die in
 * `ws-messages.ts` (= api.md §4) definierten Frames. Im Beamer-Modus werden
 * `cast`-Frames ignoriert (read-only).
 */
@Injectable({ providedIn: 'root' })
export class MockLiveVoteSource implements LiveVoteSource {
  /** Intervall der simulierten eingehenden Stimmen (ms). */
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

    const emitTally = (): void => subject.next({ ...tally, counts: { ...tally.counts } });

    const bump = (choice: string): void => {
      if (!vote.options.includes(choice)) return;
      const cast = Object.values(tally.counts).reduce((a, b) => a + b, 0);
      if (cast >= tally.eligible) return; // nicht über die Stimmberechtigten hinaus
      tally.counts[choice] = (tally.counts[choice] ?? 0) + 1;
      recompute();
      emitTally();
    };

    // Simuliert eintrudelnde Stimmen, bis alle Berechtigten votiert haben.
    // Stoppt dann den Timer, damit kein Dauer-Macrotask die Zone wachhält
    // (sonst stabilisiert Angular nie → Screenshots/SSR hängen).
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

    return {
      messages$: subject.asObservable(),
      send: (msg) => {
        if (msg.type === 'subscribe') {
          subject.next(meeting);
          subject.next(vote);
          emitTally();
        } else if (msg.type === 'cast' && !beamer) {
          bump(msg.choice);
        }
      },
      close: () => {
        clearInterval(timer);
        subject.complete();
      },
    };
  }
}
