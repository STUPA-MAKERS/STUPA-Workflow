import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { AgendaItem, MajorityRule, Meeting } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DecisionEditorComponent } from '@shared/decision/decision-editor.component';
import {
  type DecisionDraft,
  decisionQuestion,
  draftError,
  emptyDraft,
  toProposal,
} from '@shared/decision/decision.util';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  SegmentedComponent,
  SwitchComponent,
  ToastService,
  type SegmentedOption,
} from '@stupa-makers/ui-kit';
import { FIXED_VOTE_OPTIONS, errorDetail } from '../meetings-display.util';

const MAJORITY_RULES: readonly MajorityRule[] = ['simple', 'absolute', 'two_thirds'];

/**
 * "Abstimmung öffnen" for one agenda item.
 *
 * The lead sets the decision question, the majority rule and whether the vote is
 * secret. Everything else comes from the Gremium: the quorum and the eligible voters
 * (the server counts them from the roster). A meeting vote has no tie break, a tie is
 * a rejection (O18), and a ballot never changes after the cast (O11). The options are
 * always yes, no and abstain, so the result can fire the pass or fail branch.
 *
 * An application item also takes a decision proposal ("Beschlussvorschlag", F1): an
 * approved amount and conditions that apply when the vote passes. The question follows
 * the proposal until the lead edits it by hand.
 */
@Component({
  selector: 'app-vote-open-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    IconComponent,
    SegmentedComponent,
    SwitchComponent,
    DecisionEditorComponent,
  ],
  templateUrl: './vote-open-dialog.component.html',
  styleUrl: './vote-open-dialog.component.scss',
})
export class VoteOpenDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly meeting = input.required<Meeting>();
  /** The agenda item that gets the vote. The dialog is open while it is set. */
  readonly item = input<AgendaItem | null>(null);
  /** The 1-based number of the item on the agenda. */
  readonly topNumber = input(0);
  /** The members on the roster and the present ones, for the line of the voters. */
  readonly rosterCount = input(0);
  readonly presentMembers = input(0);
  readonly closed = output<void>();
  /** The server opened the vote. Carries the updated meeting. */
  readonly opened = output<Meeting>();

  readonly question = signal('');
  readonly majorityRule = signal<MajorityRule>('simple');
  readonly secret = signal(false);
  /** Admitted guests vote too (#17): no quorum, the majority of the cast votes. */
  readonly guestsVote = signal(false);
  readonly submitting = signal(false);
  /** F1: the decision proposal of an application item. */
  readonly draft = signal<DecisionDraft>(emptyDraft(null));
  /** The lead edited the question by hand: the proposal no longer rewrites it. */
  private questionEdited = false;

  /** Only an application item takes a decision proposal. */
  readonly forApplication = computed(() => !!this.item()?.applicationId);
  /** The requested amount of the application item, for the proposal. */
  readonly requested = computed(() => this.item()?.amount ?? null);
  readonly proposalInvalid = computed(
    () => this.forApplication() && draftError(this.draft(), this.requested()) !== null,
  );

  readonly ruleOptions = computed<SegmentedOption[]>(() =>
    MAJORITY_RULES.map((v) => ({ value: v, label: this.i18n.translate(`meetings.vote.rule.${v}`) })),
  );

  /** The switch exists only when the meeting lets guests vote. */
  readonly guestsAllowed = computed(
    () => this.meeting().publicJoin && this.meeting().guestsMode === 'vote',
  );
  /** A non-public item never lets guests vote. */
  readonly guestsLocked = computed(() => !!this.item()?.nonPublic);
  /** "Stimmberechtigt jetzt: 26 (19 Mitglieder + 7 Gäste anwesend)", or the members line. */
  readonly votersLine = computed(() => {
    const members = this.presentMembers();
    if (this.guestsVote()) {
      const guests = this.meeting().admittedGuests;
      return this.i18n.translate('guests.vote.votersWith', {
        n: members + guests,
        members,
        guests,
      });
    }
    return this.i18n.translate('guests.vote.votersMembers', {
      n: this.rosterCount(),
      present: members,
    });
  });

  /** "TOP 3 · Zuschuss Erstsemester-Party WS 26/27". */
  readonly subtitle = computed(() => {
    const it = this.item();
    if (!it) return '';
    const top = this.i18n.translate('meetings.agenda.top', { n: this.topNumber() });
    return it.title ? `${top} · ${it.title}` : top;
  });

  constructor() {
    effect(() => {
      const it = this.item();
      if (it) untracked(() => this.reset(it));
    });
  }

  /**
   * An application item carries the title of the application, so the question asks
   * whether to fund it. A free-text item starts with its own title. The lead can
   * change both.
   */
  private reset(it: AgendaItem): void {
    this.draft.set(emptyDraft(it.amount ?? null));
    this.questionEdited = false;
    this.question.set(it.applicationId ? this.prefill(it) : (it.title ?? ''));
    this.majorityRule.set('simple');
    this.secret.set(false);
    this.guestsVote.set(this.guestsAllowed() && !it.nonPublic);
    this.submitting.set(false);
  }

  /** The question of an application item, from the proposal (F1). */
  private prefill(it: AgendaItem): string {
    return decisionQuestion(
      it.title ?? '',
      toProposal(this.draft(), it.amount ?? null),
      it.amount ?? null,
      this.i18n.formatLocale(),
      (key, params) => this.i18n.translate(key, params),
    );
  }

  /** The lead typed the question: it stays as typed. */
  setQuestion(value: string): void {
    this.questionEdited = true;
    this.question.set(value);
  }

  /** The proposal changed: regenerate the question until the lead edits it. */
  setDraft(draft: DecisionDraft): void {
    this.draft.set(draft);
    const it = this.item();
    if (it?.applicationId && !this.questionEdited) this.question.set(this.prefill(it));
  }

  setRule(value: string | null): void {
    if (value && (MAJORITY_RULES as readonly string[]).includes(value)) {
      this.majorityRule.set(value as MajorityRule);
    }
  }

  cancel(): void {
    this.closed.emit();
  }

  submit(): void {
    const it = this.item();
    if (!it || this.submitting() || this.proposalInvalid()) return;
    const proposal = it.applicationId ? toProposal(this.draft(), it.amount ?? null) : null;
    this.submitting.set(true);
    this.api
      .openMeetingVote(this.meeting().id, {
        agendaItemId: it.id,
        question: this.question().trim() || null,
        options: [...FIXED_VOTE_OPTIONS],
        secret: this.secret(),
        majorityRule: this.majorityRule(),
        // Only a meeting that lets guests vote carries the switch; else the server decides.
        ...(this.guestsAllowed() ? { guestsVote: this.guestsVote() && !this.guestsLocked() } : {}),
        // F1: the decision proposal, only when it deviates.
        ...(proposal ? { proposal } : {}),
        // No quorum: the server takes the Gremium default.
      })
      .subscribe({
        next: (updated) => {
          this.submitting.set(false);
          this.toast.success(this.i18n.translate('meetings.toast.voteOpened'));
          this.opened.emit(updated);
        },
        error: (err: unknown) => {
          this.submitting.set(false);
          const detail = errorDetail(err);
          const base = this.i18n.translate('meetings.toast.actionFailed');
          this.toast.error(detail ? `${base}: ${detail}` : base);
        },
      });
  }
}
