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
import type { AgendaItem, Attendance, MajorityRule, Meeting, Uuid, VoteKind } from '@core/api/models';
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
  InputComponent,
  SegmentedComponent,
  SelectComponent,
  SwitchComponent,
  ToastService,
  type SegmentedOption,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { FIXED_VOTE_OPTIONS, errorDetail } from '../meetings-display.util';

const MAJORITY_RULES: readonly MajorityRule[] = ['simple', 'absolute', 'two_thirds'];
const KINDS: readonly VoteKind[] = ['motion', 'election'];
/** The bounds of the server (`ElectionConfig`). */
export const MAX_SEATS = 50;
export const MAX_CANDIDATES = 50;

/** One candidate in the dialog: a member of the roster or a free name. */
export interface CandidateDraft {
  /** A local key for the list; the server gives the ids. */
  key: number;
  name: string;
  principalId: Uuid | null;
}

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
 *
 * On a free-text item the lead can open a personnel election instead ("Beschluss |
 * Wahl", F2): the name of the round, the seats to fill and the candidates (a member of
 * the roster or a free name, in a list the lead can reorder). An election is secret by
 * default, and guests vote only when the lead switches them on. The dialog cannot
 * submit while there are fewer candidates than seats.
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
    InputComponent,
    SegmentedComponent,
    SelectComponent,
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
  /** The roster of the meeting: the persons the lead can pick as candidates. */
  readonly members = input<readonly Attendance[]>([]);
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

  /** `motion`: a decision. `election`: a personnel election (F2). */
  readonly kind = signal<VoteKind>('motion');
  readonly seats = signal(1);
  readonly candidates = signal<CandidateDraft[]>([]);
  /** The free name that the lead types for a new candidate. */
  readonly freeName = signal('');
  /** An election is secret by default. */
  readonly electionSecret = signal(true);
  private nextKey = 1;

  readonly kindOptions = computed<SegmentedOption[]>(() =>
    KINDS.map((v) => ({ value: v, label: this.i18n.translate(`meetings.vote.kind.${v}`) })),
  );
  /** An election is only possible on a free-text item. */
  readonly electionAllowed = computed(() => !this.item()?.applicationId);
  readonly isElection = computed(() => this.kind() === 'election');

  /** The roster members that are no candidate yet, for the picker. */
  readonly memberOptions = computed<SelectOption[]>(() => {
    const taken = new Set(this.candidates().map((c) => c.principalId));
    return this.members()
      .filter((m) => !taken.has(m.principalId))
      .map((m) => ({ value: m.principalId, label: m.displayName || m.email || m.principalId }));
  });

  /**
   * The election needs a name and at least as many candidates as seats. A motion on
   * an application item needs a valid decision proposal (F1).
   */
  readonly tooFew = computed(() => this.candidates().length < this.seats());
  readonly canSubmit = computed(() => {
    if (!this.isElection()) return !this.proposalInvalid();
    return !this.tooFew() && this.question().trim().length > 0;
  });

  /** "Jede Person hat 2 Stimmen …": the rule of the election in one sentence. */
  readonly ruleSentence = computed(() => {
    const seats = this.seats();
    if (seats === 1 && this.candidates().length === 1) {
      return this.i18n.translate('election.rule.yesNo');
    }
    return seats === 1
      ? this.i18n.translate('election.rule.single')
      : this.i18n.translate('election.rule.multi', { n: seats });
  });

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
    this.kind.set('motion');
    this.seats.set(1);
    this.candidates.set([]);
    this.freeName.set('');
    this.electionSecret.set(true);
  }

  setKind(value: string | null): void {
    if (value !== 'motion' && value !== 'election') return;
    if (value === 'election' && !this.electionAllowed()) return;
    this.kind.set(value);
    const it = this.item();
    // Guests vote in an election only when the lead switches them on.
    this.guestsVote.set(value === 'motion' && this.guestsAllowed() && !it?.nonPublic);
  }

  /** The seats stepper: 1 to 50. */
  changeSeats(delta: number): void {
    this.seats.update((n) => Math.min(MAX_SEATS, Math.max(1, n + delta)));
  }

  /** Add the picked roster member as a candidate. */
  addMember(principalId: string): void {
    const member = this.members().find((m) => m.principalId === principalId);
    if (!member || this.candidates().length >= MAX_CANDIDATES) return;
    if (this.candidates().some((c) => c.principalId === principalId)) return;
    const name = member.displayName || member.email || principalId;
    this.candidates.update((list) => [...list, { key: this.nextKey++, name, principalId }]);
  }

  /** Add the typed free name as a candidate. */
  addFreeName(): void {
    const name = this.freeName().trim();
    if (!name || this.candidates().length >= MAX_CANDIDATES) return;
    this.candidates.update((list) => [
      ...list,
      { key: this.nextKey++, name: name.slice(0, 200), principalId: null },
    ]);
    this.freeName.set('');
  }

  /** Move a candidate one place up (-1) or down (+1). */
  moveCandidate(index: number, delta: -1 | 1): void {
    const to = index + delta;
    this.candidates.update((list) => {
      if (to < 0 || to >= list.length) return list;
      const next = [...list];
      [next[index], next[to]] = [next[to], next[index]];
      return next;
    });
  }

  removeCandidate(key: number): void {
    this.candidates.update((list) => list.filter((c) => c.key !== key));
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
    if (!it || this.submitting() || !this.canSubmit()) return;
    const proposal = it.applicationId ? toProposal(this.draft(), it.amount ?? null) : null;
    this.submitting.set(true);
    // Only a meeting that lets guests vote carries the switch; else the server decides.
    const guests = this.guestsAllowed()
      ? { guestsVote: this.guestsVote() && !this.guestsLocked() }
      : {};
    const body = this.isElection()
      ? {
          agendaItemId: it.id,
          kind: 'election' as const,
          question: this.question().trim(),
          seats: this.seats(),
          candidates: this.candidates().map((c) => ({
            name: c.name,
            ...(c.principalId ? { principalId: c.principalId } : {}),
          })),
          secret: this.electionSecret(),
          ...guests,
        }
      : {
          agendaItemId: it.id,
          question: this.question().trim() || null,
          options: [...FIXED_VOTE_OPTIONS],
          secret: this.secret(),
          majorityRule: this.majorityRule(),
          ...guests,
          // F1: the decision proposal, only when it deviates.
          ...(proposal ? { proposal } : {}),
          // No quorum: the server takes the Gremium default.
        };
    this.api
      .openMeetingVote(this.meeting().id, body)
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
