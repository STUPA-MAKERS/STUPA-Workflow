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
  readonly closed = output<void>();
  /** The server opened the vote. Carries the updated meeting. */
  readonly opened = output<Meeting>();

  readonly question = signal('');
  readonly majorityRule = signal<MajorityRule>('simple');
  readonly secret = signal(false);
  readonly submitting = signal(false);

  readonly ruleOptions = computed<SegmentedOption[]>(() =>
    MAJORITY_RULES.map((v) => ({ value: v, label: this.i18n.translate(`meetings.vote.rule.${v}`) })),
  );

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
    this.question.set(
      it.applicationId
        ? this.i18n.translate('meetings.vote.questionPrefill', { name: it.title ?? '' })
        : (it.title ?? ''),
    );
    this.majorityRule.set('simple');
    this.secret.set(false);
    this.submitting.set(false);
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
    if (!it || this.submitting()) return;
    this.submitting.set(true);
    this.api
      .openMeetingVote(this.meeting().id, {
        agendaItemId: it.id,
        question: this.question().trim() || null,
        options: [...FIXED_VOTE_OPTIONS],
        secret: this.secret(),
        majorityRule: this.majorityRule(),
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
