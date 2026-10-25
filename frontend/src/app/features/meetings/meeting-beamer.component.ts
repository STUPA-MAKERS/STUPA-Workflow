import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import type {
  ElectionConfig,
  ElectionResult,
  MajorityRule,
  PollConfig,
  PollResult,
  QrMatrix,
  Quorum,
  VoteResult,
} from '@core/api/models';
import { QrCodeComponent, formatJoinCode } from '@shared/ui/qr-code/qr-code.component';
import { IconComponent, SegBarComponent, StatusTextComponent } from '@stupa-makers/ui-kit';
import { VoteBarsComponent } from '../voting/vote-bars.component';
import { ElectionResultComponent } from '../voting/election-result/election-result.component';
import { electionCaption, electionResultLine, electionStatus } from '../voting/election.util';
import { PollResultComponent } from '../voting/poll-result/poll-result.component';
import { pollCaption } from '../voting/poll.util';
import {
  guestComposition,
  majorityLabel,
  quorumLabel,
  secrecyLabel,
  voteRulesParts,
} from './meetings-display.util';

/** The vote that the beamer shows, as the page assembles it from the server data. */
export interface BeamerVote {
  question: string;
  options: readonly string[];
  status: 'open' | 'closed';
  majorityRule: MajorityRule;
  secret: boolean;
  quorum: Quorum | null;
  quorumMet: boolean;
  /** The ballots cast so far. */
  voted: number;
  /** The present members: the base of the turnout. */
  present: number;
  /** The counts per option. `null` while the server hides them. */
  counts: Readonly<Record<string, number>> | null;
  result: VoteResult | null;
  failedReason: 'quorum' | 'majority' | null;
  /** Admitted guests vote too: no quorum, the majority of the cast votes. */
  guestsVote?: boolean;
  /** The present members and the admitted guests, for "19 Mitglieder + 7 Gäste anwesend". */
  presentMembers?: number | null;
  presentGuests?: number | null;
  /** A personnel election: the candidates, the stored result and the round. */
  election?: ElectionConfig | null;
  electionResult?: ElectionResult | null;
  round?: number;
  /** A poll: the mode, the options and the stored counts. */
  poll?: PollConfig | null;
  pollResult?: PollResult | null;
}

/** The join code of a public meeting on the screen: never a name, only the code. */
export interface BeamerJoin {
  code: string;
  url: string;
  qr: QrMatrix;
}

/** The people in the room: present members and admitted guests. */
export interface BeamerPresence {
  members: number;
  guests: number;
}

/** The texts of the screen for one vote. */
interface BeamerText {
  /** Show the counts as bars. */
  bars: boolean;
  /** "14 von 19 Anwesenden haben abgestimmt", the label of the bar. */
  turnout: string;
  hiddenKey: TranslationKey;
  /** "Einfache Mehrheit · offene Abstimmung · Quorum 12". */
  rules: string;
  /** "Quorum 12 · noch nicht erreicht" while an open vote misses its quorum. */
  quorumWarning: string | null;
  passed: boolean;
  /** "Einfache Mehrheit · Quorum erreicht · 20 Stimmen". */
  outcome: string;
  /** A vote with guests: "19 Mitglieder + 7 Gäste anwesend", else `null`. */
  composition: string | null;
}

/**
 * The beamer screen (boards Beamer, Beamer-Laeuft, Beamer-Leerlauf, Beamer-Quorum,
 * Beamer-Gleichstand): large type for a projector, no controls.
 *
 * - No vote: "Jetzt", the agenda item that the room handles, "Zurzeit keine aktive
 *   Abstimmung."
 * - An open vote: the question, the number of ballots in large type, "von 19 Anwesenden
 *   haben abgestimmt", a bar, and the fixed line about the hidden counts. The screen
 *   shows no interim tally: only the counts that the server reveals (every present
 *   member voted, not secret) show as bars. The foot names the rules, and a quorum that
 *   is not reached yet shows in the warning colour.
 * - A closed vote: the bars, then "Angenommen" (accent) or "Abgelehnt" (error) with the
 *   rule, the quorum and the number of ballots. A tie is "Abgelehnt" with "Einfache
 *   Mehrheit nicht erreicht".
 *
 * The page (`voting/beamer`) reads the server and passes the data in.
 */
@Component({
  selector: 'app-meeting-beamer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    IconComponent,
    QrCodeComponent,
    ElectionResultComponent,
    PollResultComponent,
    SegBarComponent,
    StatusTextComponent,
    VoteBarsComponent,
  ],
  templateUrl: './meeting-beamer.component.html',
  styleUrl: './meeting-beamer.component.scss',
})
export class MeetingBeamerComponent {
  private readonly i18n = inject(I18nService);

  readonly meetingTitle = input<string | null>(null);
  /** "TOP 3 · Zuschuss Erstsemester-Party": the item of the vote, or the current item. */
  readonly topLine = input<string | null>(null);
  readonly vote = input<BeamerVote | null>(null);
  readonly logoSrc = input.required<string>();
  /** The join code of a public meeting: a large card while idle, a corner badge in a vote. */
  readonly join = input<BeamerJoin | null>(null);
  /** The people in the room, while the meeting is public. */
  readonly presence = input<BeamerPresence | null>(null);

  protected readonly formatCode = formatJoinCode;

  /** The short link without the scheme: "workflow.example/j/7KQ4MP". */
  protected shortUrl(j: BeamerJoin): string {
    return j.url.replace(/^https?:\/\//, '');
  }

  protected qrLabel(j: BeamerJoin): string {
    return this.i18n.translate('guests.qr.label', { url: j.url });
  }

  /** The status of a closed election: "Gewählt", "Stichwahl" and so on. */
  protected electionKey(result: VoteResult | null): TranslationKey {
    return electionStatus(result).key;
  }

  /** The texts of the shown vote, or `null` while idle. */
  protected readonly text = computed<BeamerText | null>(() => {
    const v = this.vote();
    return v ? this.describe(v) : null;
  });

  private describe(v: BeamerVote): BeamerText {
    const t: Translate = (key, params) => this.i18n.translate(key, params);
    if (v.election) return this.describeElection(v, v.election, t);
    if (v.poll) return this.describePoll(v, v.poll, t);
    const guests = !!v.guestsVote;
    const majority = majorityLabel(v.majorityRule, guests, t);
    const q = v.quorum;
    const quorum = q ? quorumLabel(q, t) : '';
    const passed = v.result === 'passed';
    const quorumOpen = v.status === 'open' && !!q && !v.quorumMet;

    const rules = voteRulesParts(
      { majorityRule: v.majorityRule, secret: v.secret, quorum: quorumOpen ? null : q, guestsVote: guests },
      t,
    );

    const missedQuorum = v.failedReason === 'quorum';
    const outcome = [passed || missedQuorum ? majority : t('beamer.majorityMissed', { rule: majority })];
    if (q) outcome.push(t(missedQuorum ? 'beamer.quorumMissed' : 'beamer.quorumMet'));
    outcome.push(v.voted === 1 ? t('beamer.ballotsOne') : t('beamer.ballots', { n: v.voted }));
    const composition = guests ? guestComposition(v.presentMembers, v.presentGuests, t) : null;

    return {
      bars: v.counts !== null && (v.status === 'closed' || !v.secret),
      turnout: t('meetings.vote.progress', { voted: v.voted, present: v.present }),
      hiddenKey: v.secret ? 'meetings.vote.hiddenSecret' : 'meetings.vote.progressHidden',
      rules: rules.join(' · '),
      quorumWarning: quorumOpen ? t('beamer.quorumPending', { quorum }) : null,
      passed,
      outcome: guests
        ? [t('guests.vote.castN', { n: v.voted }), t('guests.vote.majorityOfCast')].join(' · ')
        : outcome.join(' · '),
      composition,
    };
  }

  /** A poll: "Umfrage · Einzelwahl · offene Abstimmung". It has no result. */
  private describePoll(v: BeamerVote, poll: PollConfig, t: Translate): BeamerText {
    const rules = [pollCaption(poll, t), secrecyLabel(v.secret, t)].join(' · ');
    return {
      bars: v.counts !== null && (v.status === 'closed' || !v.secret),
      turnout: t('meetings.vote.progress', { voted: v.voted, present: v.present }),
      hiddenKey: v.secret ? 'meetings.vote.hiddenSecret' : 'meetings.vote.progressHidden',
      rules,
      quorumWarning: null,
      passed: false,
      outcome: rules,
      composition: null,
    };
  }

  /** An election: "Wahl · 2 Posten · geheime Abstimmung", then "Gewählt: Anna". */
  private describeElection(
    v: BeamerVote,
    election: ElectionConfig,
    t: Translate,
  ): BeamerText {
    const rules = [electionCaption(election, v.round, t), secrecyLabel(v.secret, t)].join(' · ');
    const ballots = v.voted === 1 ? t('beamer.ballotsOne') : t('beamer.ballots', { n: v.voted });
    return {
      bars: v.counts !== null && (v.status === 'closed' || !v.secret),
      turnout: t('meetings.vote.progress', { voted: v.voted, present: v.present }),
      hiddenKey: v.secret ? 'meetings.vote.hiddenSecret' : 'meetings.vote.progressHidden',
      rules,
      quorumWarning: null,
      passed: v.result === 'elected',
      outcome: [electionResultLine(election, v.result, v.electionResult ?? null, t), ballots].join(' · '),
      composition: null,
    };
  }
}
