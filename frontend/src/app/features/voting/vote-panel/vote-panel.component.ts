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
 * The vote page, the live page and the participant view of a meeting (`layout="card"`)
 * use it; they load the data and send the ballots. A vote without a meeting shows a link to its application instead of the
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
    '[class.vpn--card]': "layout() === 'card'",
    '[class.vpn--strip]': "layout() === 'strip'",
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
  /**
   * `card`: the small card of a side column (the participant view of a meeting).
   * `strip`: the card above the text on a narrow screen (board Schmal-Teilnahme): the
   * caption with the TOP and the turnout "14 von 19", the rows side by side.
   */
  readonly layout = input<'page' | 'phone' | 'card' | 'strip'>('page');

  /** Why the person cannot vote (a warning note), or `null`. */
  readonly notice = input<string | null>(null);

  readonly castDone = output<BallotCast>();
  readonly castFailed = output<BallotFailure>();

  protected readonly status = computed<StatusView>(() => meetingVoteStatus(this.vote().status));
  /** The caption of the card: "Abstimmung offen", "Abstimmung geschlossen". */
  protected readonly cardCap = computed<TranslationKey>(() => {
    const status = this.vote().status;
    if (status === 'open') return 'meetings.vote.card.open';
    if (status === 'closed') return 'meetings.vote.card.closed';
    return this.status().key;
  });
  /** The caption of the strip: "Abstimmung offen · TOP 3". */
  protected readonly stripCap = computed(() => {
    const cap = this.i18n.translate(this.cardCap());
    const n = this.context().position;
    return n === null ? cap : `${cap} · ${this.i18n.translate('meetings.agenda.top', { n })}`;
  });
  /** The card keeps its confirm button inside the card, also on a phone. */
  protected readonly ballotLayout = computed<'page' | 'phone'>(() =>
    this.layout() === 'phone' ? 'phone' : 'page',
  );
  protected readonly isOpen = computed(() => this.vote().status === 'open');
  /** The card and the strip carry the small ballot. */
  protected readonly compact = computed(() => this.layout() === 'card' || this.layout() === 'strip');
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

  /** "14 von 19 Anwesenden haben abgestimmt": the long form of the turnout of the strip. */
  protected readonly turnoutLabel = computed(() =>
    this.i18n.translate('meetings.vote.progress', {
      voted: this.vote().tally.voted ?? 0,
      present: this.turnoutTotal(),
    }),
  );

  /** The fixed line while the counts are hidden (the strip has no progress block). */
  protected readonly hiddenKey = computed<TranslationKey>(() =>
    this.secret() ? 'meetings.vote.hiddenSecret' : 'meetings.vote.progressHidden',
  );

  /** The ballot shows while the vote is open and the person holds a ballot. */
  protected readonly showBallot = computed(
    () => this.isOpen() && (this.own() !== null || !!this.proxyName()),
  );

  /**
   * The line below the result of a closed vote: "20 von 20 Stimmen · Quorum: erreicht".
   * The quorum part shows only for a vote with a quorum, and not when the result line
   * already says "Quorum nicht erreicht".
   */
  protected readonly closedSummary = computed<string | null>(() => {
    const v = this.vote();
    if (v.status !== 'closed') return null;
    const t = v.tally;
    const cast = t.voted ?? Object.values(t.counts).reduce((sum, n) => sum + n, 0);
    const parts = [this.i18n.translate('voting.beamer.votesOf', { cast, eligible: t.eligible })];
    if ((v.quorum ?? v.config.quorum) && t.failedReason !== 'quorum') {
      const state = this.i18n.translate(t.quorumMet ? 'vote.tally.quorumMet' : 'vote.tally.quorumMissed');
      parts.push(`${this.i18n.translate('vote.tally.quorum')}: ${state}`);
    }
    return parts.join(' · ');
  });

  /** Counts show after the close, or while open once the server revealed them. */
  protected readonly showBars = computed(() => {
    const v = this.vote();
    if (v.status === 'closed') return true;
    return v.status === 'open' && v.tally.revealed !== false && Object.keys(v.tally.counts).length > 0;
  });
}
