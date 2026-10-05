import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { MajorityRule, Quorum, VoteResult } from '@core/api/models';
import { SegBarComponent } from '@shared/ui/seg-bar/seg-bar.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { IconComponent } from '@stupa-makers/ui-kit';
import { VoteBarsComponent } from '../voting/vote-bars.component';

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
 *   Mehrheit nicht erreicht" (O18).
 *
 * The page (`voting/beamer`) reads the server and passes the data in.
 */
@Component({
  selector: 'app-meeting-beamer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, IconComponent, SegBarComponent, StatusTextComponent, VoteBarsComponent],
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

  /** The texts of the shown vote, or `null` while idle. */
  protected readonly text = computed<BeamerText | null>(() => {
    const v = this.vote();
    return v ? this.describe(v) : null;
  });

  private describe(v: BeamerVote): BeamerText {
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    const majority = t(`vote.majority.${v.majorityRule}` as TranslationKey);
    const q = v.quorum;
    const quorum = q
      ? t(q.type === 'percent' ? 'meetings.vote.quorumPercent' : 'meetings.vote.quorumCount', {
          n: q.value,
        })
      : '';
    // Every result that is not `passed` is a rejection, also a tie (O18).
    const passed = v.result === 'passed';
    const quorumOpen = v.status === 'open' && !!q && !v.quorumMet;

    // "Einfache Mehrheit · offene Abstimmung", plus the quorum while it is reached.
    const rules = [majority, t(v.secret ? 'meetings.vote.secretShort' : 'meetings.vote.publicShort')];
    if (q && !quorumOpen) rules.push(quorum);

    // "Einfache Mehrheit · Quorum erreicht · 20 Stimmen". A closed vote missed its
    // quorum exactly when the server names it as the reason.
    const missedQuorum = v.failedReason === 'quorum';
    const outcome = [passed || missedQuorum ? majority : t('beamer.majorityMissed', { rule: majority })];
    if (q) outcome.push(t(missedQuorum ? 'beamer.quorumMissed' : 'beamer.quorumMet'));
    outcome.push(v.voted === 1 ? t('beamer.ballotsOne') : t('beamer.ballots', { n: v.voted }));

    return {
      // Counts show after the close, or while open once the server revealed them.
      bars: v.counts !== null && (v.status === 'closed' || !v.secret),
      turnout: t('meetings.vote.progress', { voted: v.voted, present: v.present }),
      hiddenKey: v.secret ? 'meetings.vote.hiddenSecret' : 'meetings.vote.progressHidden',
      rules: rules.join(' · '),
      quorumWarning: quorumOpen ? t('beamer.quorumPending', { quorum }) : null,
      passed,
      outcome: outcome.join(' · '),
    };
  }
}
