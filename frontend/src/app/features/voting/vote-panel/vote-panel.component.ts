import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { MyBallot, Vote } from '@core/api/models';
import { NoteComponent } from '@shared/ui/note/note.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { meetingVoteStatus, type StatusView } from '@shared/status-kind.util';
import {
  BallotComponent,
  type BallotCast,
  type BallotCaster,
  type BallotFailure,
} from '../ballot/ballot.component';
import { VoteBarsComponent } from '../vote-bars.component';
import { VoteProgressComponent } from '../vote-progress/vote-progress.component';
import { NO_CONTEXT, type VoteContext } from './vote-context';

/**
 * One vote as a card (board Arbeit-Abstimmungen) or as the phone page body (board
 * Telefon-Abstimmen): the status, "<Sitzung> · TOP 3 · Einfache Mehrheit", the question,
 * the ballot, the turnout and, once the server shows them, the counts with the result.
 *
 * The vote page and the live page both use it; they load the data and send the
 * ballots. A vote without a meeting shows a link to its application instead of the
 * meeting line, and counts its turnout against the eligible voters.
 */
@Component({
  selector: 'app-vote-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    BallotComponent,
    NoteComponent,
    StatusTextComponent,
    VoteBarsComponent,
    VoteProgressComponent,
  ],
  host: {
    '[class.vpn--phone]': "layout() === 'phone'",
  },
  templateUrl: './vote-panel.component.html',
  styleUrl: './vote-panel.component.scss',
})
export class VotePanelComponent {
  private readonly i18n = inject(I18nService);

  readonly vote = input.required<Vote>();
  readonly context = input<VoteContext>(NO_CONTEXT);
  /** The own ballot, or `null` when the person may not cast one. */
  readonly own = input<MyBallot | null>(null);
  readonly proxyName = input<string | null>(null);
  readonly proxyCast = input(false);
  readonly caster = input.required<BallotCaster>();
  readonly layout = input<'page' | 'phone'>('page');
  /** Why the person cannot vote (a warning note), or `null`. */
  readonly notice = input<string | null>(null);

  readonly castDone = output<BallotCast>();
  readonly castFailed = output<BallotFailure>();

  protected readonly status = computed<StatusView>(() => meetingVoteStatus(this.vote().status));
  protected readonly isOpen = computed(() => this.vote().status === 'open');
  protected readonly secret = computed(() => this.vote().secret || !!this.vote().config.secret);
  protected readonly options = computed(() => this.vote().config.options ?? []);

  /** "34. Sitzung des Studierendenparlaments · TOP 3", or `null` without a meeting. */
  protected readonly where = computed(() => {
    const { meeting, position } = this.context();
    if (!meeting) return null;
    return position === null
      ? meeting.title
      : this.i18n.translate('voting.panel.where', { meeting: meeting.title, n: position });
  });

  /** "Einfache Mehrheit · Quorum 12 · geheime Abstimmung". */
  protected readonly rules = computed(() => {
    const v = this.vote();
    const parts = [
      this.i18n.translate(
        `vote.majority.${v.majorityRule ?? v.config.majorityRule ?? 'simple'}` as TranslationKey,
      ),
    ];
    const quorum = v.quorum ?? v.config.quorum;
    if (quorum) {
      parts.push(
        this.i18n.translate(
          quorum.type === 'percent' ? 'meetings.vote.quorumPercent' : 'meetings.vote.quorumCount',
          { n: quorum.value },
        ),
      );
    }
    if (this.secret()) parts.push(this.i18n.translate('meetings.vote.secretShort'));
    return parts.join(' · ');
  });

  protected readonly question = computed(
    () => this.vote().question || this.i18n.translate('meetings.vote.untitled'),
  );

  /** A meeting vote counts the turnout against the present members. */
  protected readonly basis = computed<'present' | 'eligible'>(() =>
    this.vote().meetingId ? 'present' : 'eligible',
  );
  protected readonly turnoutTotal = computed(() => {
    const t = this.vote().tally;
    return this.basis() === 'present' ? (t.present ?? 0) : t.eligible;
  });

  /** The ballot shows while the vote is open and the person holds a ballot. */
  protected readonly showBallot = computed(
    () => this.isOpen() && (this.own() !== null || !!this.proxyName()),
  );

  /** Counts show after the close, or while open once the server revealed them. */
  protected readonly showBars = computed(() => {
    const v = this.vote();
    if (v.status === 'closed') return true;
    return v.status === 'open' && v.tally.revealed !== false && Object.keys(v.tally.counts).length > 0;
  });
}
