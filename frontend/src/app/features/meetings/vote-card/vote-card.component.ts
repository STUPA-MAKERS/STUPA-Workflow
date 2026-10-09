import {
  ChangeDetectionStrategy,
  Component,
  Injector,
  computed,
  inject,
  input,
  output,
} from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { MeetingStatus, MeetingVote, MyBallot, Uuid, Vote } from '@core/api/models';
import { ButtonComponent, IconComponent, ToastService } from '@stupa-makers/ui-kit';
import { SegBarComponent } from '@shared/ui/seg-bar/seg-bar.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { meetingVoteStatus, voteResultStatus, type StatusView } from '@shared/status-kind.util';
import {
  BallotComponent,
  type BallotCaster,
  type BallotFailure,
} from '../../voting/ballot/ballot.component';
import { ElectionResultComponent } from '../../voting/election-result/election-result.component';
import { electionCaption, electionOf, electionStatus } from '../../voting/election.util';
import {
  countEntries,
  errorDetail,
  guestComposition,
  voteMetaLine,
  voteOptionLabel,
  voteOptionsFor,
} from '../meetings-display.util';

/**
 * One vote of the open agenda item, as a card beside the sheet.
 *
 * An open vote shows the question, the rules ("Einfache Mehrheit · offene Abstimmung ·
 * Quorum 12 · seit 18:48") and the progress ("14 von 19 Anwesenden haben abgestimmt").
 * The lead sees no interim tally: the server reveals the counts only when every present
 * member voted on an open vote, or after the close. The card then shows them.
 *
 * The vote manager closes or cancels (danger) an open vote, opens a planned one and
 * deletes a planned or cancelled one while the meeting is planned or live (O24). Only one
 * vote of the meeting is open at a time, so "Abstimmung öffnen" waits for it. A voter
 * who did not vote yet gets the options; a ballot never changes once it is cast (O11).
 * A closed vote offers to put its result into the text of the item ("Ins Protokoll
 * übernehmen"), and says "Im Protokoll" once the text holds it.
 *
 * A personnel election (F2) shows the election ballot (candidates, abstention) and,
 * once closed, the bars per candidate with the runoff and lot actions of the manager.
 */
@Component({
  selector: 'app-vote-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    BallotComponent,
    ButtonComponent,
    ElectionResultComponent,
    IconComponent,
    SegBarComponent,
    StatusTextComponent,
  ],
  templateUrl: './vote-card.component.html',
  styleUrl: './vote-card.component.scss',
})
export class VoteCardComponent {
  private readonly i18n = inject(I18nService);
  /** The API client, looked up on use: only an election ballot sends from the card. */
  private readonly injector = inject(Injector);
  private readonly toast = inject(ToastService);

  readonly vote = input.required<MeetingVote>();
  readonly meetingStatus = input.required<MeetingStatus>();
  /** Open, close, cancel and delete votes (`Meeting.canManageVotes`). */
  readonly canManage = input(false);
  /** Eligible to vote in this meeting (`Meeting.canVote`). */
  readonly canVote = input(false);
  /** The own choice of this session, or `null`. The server value is `vote.myBallot`. */
  readonly myChoice = input<string | null>(null);
  /** The vote with a ballot in flight. */
  readonly casting = input<Uuid | null>(null);
  readonly deleting = input<Uuid | null>(null);
  /** The protocol is final or renders. */
  readonly locked = input(false);
  /** Offer "Ins Protokoll übernehmen": the result is not in the text yet. */
  readonly canInsert = input(false);
  /** The result is in the text of the item: the card says "Im Protokoll". */
  readonly inProtocol = input(false);
  /**
   * A vote of the meeting is open, on this item or on another one. A planned vote then
   * waits: the reconnect state, the beamer and the dock follow only one open vote.
   */
  readonly otherOpen = input(false);

  readonly close = output<Uuid>();
  readonly cancel = output<Uuid>();
  readonly open = output<Uuid>();
  readonly remove = output<Uuid>();
  readonly cast = output<{ voteId: Uuid; choice: string }>();
  readonly insertResult = output<MeetingVote>();
  /** The lot was drawn, or the runoff opened (F2): the page reads the meeting again. */
  readonly electionChanged = output<Vote>();

  /** The personnel election of the vote (F2), or `null` for a motion. */
  protected readonly election = computed(() => electionOf(this.vote()));
  /** "Wahl · 2 Posten" or "Stichwahl (2. Wahlgang) · 1 Posten". */
  protected readonly electionCap = computed(() => {
    const el = this.election();
    return el ? electionCaption(el, this.vote().round, (k, p) => this.i18n.translate(k, p)) : null;
  });
  /** The election ballot sends the list of the candidate ids. */
  protected readonly caster: BallotCaster = (choice) =>
    this.injector.get(ApiClient).castBallot(this.vote().id, choice);
  protected readonly notCast: MyBallot = { cast: false, choice: null };

  protected onBallotFailed(failure: BallotFailure): void {
    const detail = failure.alreadyVoted ? '' : errorDetail(failure.error);
    const base = this.i18n.translate(
      failure.alreadyVoted ? 'voting.cast.toast.alreadyVoted' : 'meetings.toast.actionFailed',
    );
    this.toast.error(detail ? `${base}: ${detail}` : base);
  }

  protected readonly status = computed<StatusView>(() => meetingVoteStatus(this.vote().status));
  /** The caption of the card: "Abstimmung offen", "… geschlossen" and so on. */
  protected readonly capKey = computed(
    () => `meetings.vote.card.${this.vote().status}` as TranslationKey,
  );
  /** The result of a closed vote. A tie is a rejection (O18). */
  protected readonly result = computed<StatusView | null>(() => {
    const v = this.vote();
    if (v.status !== 'closed') return null;
    if (this.election()) return electionStatus(v.result);
    return voteResultStatus(v.result === 'passed' ? 'passed' : 'rejected');
  });

  protected readonly meta = computed(() =>
    voteMetaLine(this.vote(), (key, params) => this.i18n.translate(key, params), this.i18n.locale()),
  );

  /** A vote with guests (#17): "19 Mitglieder + 7 Gäste anwesend", else `null`. */
  protected readonly composition = computed(() => {
    const v = this.vote();
    if (!v.guestsVote) return null;
    return guestComposition(v.presentMembers, v.presentGuests, (k, p) => this.i18n.translate(k, p));
  });
  /** The closed result of a vote with guests: present, cast, majority of the cast votes. */
  protected readonly guestResult = computed(() => {
    const v = this.vote();
    if (!v.guestsVote || v.status !== 'closed') return null;
    const cast = Object.values(v.counts ?? {}).reduce((a, b) => a + b, 0);
    const members = v.presentMembers ?? null;
    const guests = v.presentGuests ?? null;
    return {
      present: members !== null && guests !== null ? members + guests : null,
      cast,
      passed: v.result === 'passed',
    };
  });

  protected readonly percent = computed(() => {
    const v = this.vote();
    return v.present > 0 ? Math.min(100, Math.round((v.voted / v.present) * 100)) : 0;
  });

  protected readonly progressLabel = computed(() => {
    const v = this.vote();
    return this.i18n.translate('meetings.vote.progress', { voted: v.voted, present: v.present });
  });

  /** The counts are visible: after the close, or once every present member voted. */
  protected readonly showCounts = computed(() => {
    const v = this.vote();
    return v.counts !== null && (v.status === 'closed' || v.revealed);
  });

  protected readonly counts = computed(() => countEntries(this.vote()));
  protected readonly options = computed(() => voteOptionsFor(this.vote()));

  /** The own ballot is in: from this session or from the server. */
  protected readonly hasVoted = computed(
    () => this.myChoice() !== null || this.vote().myBallot?.cast === true,
  );

  /** The hint below an open vote whose counts are still hidden. */
  protected readonly hiddenKey = computed<TranslationKey>(() =>
    this.vote().secret ? 'meetings.vote.hiddenSecret' : 'meetings.vote.progressHidden',
  );

  /** Plan, cancel and delete: only while the meeting is planned or live (O24). */
  protected readonly canEdit = computed(
    () => this.canManage() && !this.locked() && this.meetingStatus() !== 'closed',
  );

  /** Only a planned or cancelled vote can go; an open or closed one is part of the record. */
  protected readonly canDelete = computed(() => {
    const s = this.vote().status;
    return this.canEdit() && (s === 'draft' || s === 'cancelled');
  });

  protected optionLabel(opt: string): string {
    return voteOptionLabel(opt, (key) => this.i18n.translate(key));
  }
}
