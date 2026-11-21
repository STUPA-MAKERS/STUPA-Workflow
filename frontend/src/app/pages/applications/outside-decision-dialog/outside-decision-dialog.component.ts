import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting, OutsideDecisionBody, ProblemDetail, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DecisionEditorComponent } from '@shared/decision/decision-editor.component';
import {
  type DecisionDraft,
  draftError,
  emptyDraft,
  toProposal,
} from '@shared/decision/decision.util';
import { dayMonthYear, localToday } from '@shared/date-format';
import {
  ButtonComponent,
  DatepickerComponent,
  DialogComponent,
  InputComponent,
  SegmentedComponent,
  type SegmentedOption,
  SelectFieldComponent,
  type SelectOption,
  ToastService,
  ErrorTextComponent,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';

/** The result of a decision made outside the platform. */
export type OutsideResult = 'passed' | 'failed';

/** The most votes of one kind (as the server). */
export const MAX_COUNT = 10000;

/** The server refused the decision: the codes of the 422 answers. */
const REFUSALS: Record<string, TranslationKey> = {
  decision_date_invalid: 'outsideDecision.error.date',
  gremium_unknown: 'outsideDecision.error.gremium',
  meeting_unknown: 'outsideDecision.error.meeting',
  approved_amount_required: 'decision.error.amountRequired',
  approved_amount_invalid: 'decision.error.amountInvalid',
  approved_amount_exceeds_requested: 'decision.error.amountExceeds',
};

/** A count field: empty, or a whole number from 0 to 10000. */
function countOf(text: string): number | null | undefined {
  const value = text.trim();
  if (value === '') return null;
  if (!/^\d+$/.test(value)) return undefined;
  const n = Number(value);
  return n <= MAX_COUNT ? n : undefined;
}

/**
 * "Beschluss erfassen" (spec 001600): record a decision that a Gremium made in a meeting
 * without a vote on the platform. Needs `application.record_decision`, and the
 * application must sit in a vote state.
 *
 * The dialog asks for the result, the meeting date (not after today) and the Gremium,
 * preset with the Gremium of the vote state. The counts and the meeting are optional. A
 * passed decision with a requested amount asks for the approved amount, prefilled with
 * the requested one (spec 001610). The server fires the `pass` or the `fail` branch and
 * cancels the open votes of the state (spec 001601).
 */
@Component({
  selector: 'app-outside-decision-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    ErrorTextComponent,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DatepickerComponent,
    DecisionEditorComponent,
    DialogComponent,
    InputComponent,
    SegmentedComponent,
    SelectFieldComponent,
  ],
  templateUrl: './outside-decision-dialog.component.html',
  styleUrl: './outside-decision-dialog.component.scss',
})
export class OutsideDecisionDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input<Uuid | null>(null);
  readonly applicationTitle = input('');
  /** The requested amount (decimal string), or null for an application without money. */
  readonly requested = input<string | null>(null);
  readonly currency = input<string | null>('EUR');
  /** The Gremium of the vote state (000243): the preset of the picker. */
  readonly gremiumId = input<Uuid | null>(null);
  readonly open = model(false);
  /** The decision was recorded, or a 409 answer came: the caller loads again. */
  readonly done = output<void>();

  readonly result = signal<OutsideResult | null>(null);
  readonly date = signal('');
  readonly gremium = signal('');
  readonly meeting = signal('');
  readonly yes = signal('');
  readonly no = signal('');
  readonly abstain = signal('');
  readonly draft = signal<DecisionDraft>(emptyDraft(null, true));
  readonly saving = signal(false);
  /** The reason the server refused the decision, shown in the dialog. */
  readonly refusal = signal('');

  private readonly gremien = signal<{ id: Uuid; name: string }[]>([]);
  private readonly meetings = signal<Meeting[]>([]);

  /** Today, read again on each opening. */
  readonly today = signal(localToday());

  readonly resultOptions = computed<SegmentedOption[]>(() => [
    { value: 'passed', label: this.i18n.translate('outsideDecision.passed') },
    { value: 'failed', label: this.i18n.translate('outsideDecision.failed') },
  ]);

  readonly gremiumOptions = computed<SelectOption[]>(() =>
    this.gremien().map((g) => ({ value: g.id, label: g.name })),
  );

  /** The meetings of the Gremium, the newest first, as "Titel · 18.11.2026". */
  readonly meetingOptions = computed<SelectOption[]>(() => {
    const locale = this.i18n.formatLocale();
    return [...this.meetings()]
      .sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))
      .map((m) => ({
        value: m.id,
        label: m.date ? `${m.title} · ${dayMonthYear(m.date, locale)}` : m.title,
      }));
  });

  /** A passed decision of an application with money names the approved amount. */
  readonly asksAmount = computed(() => this.result() === 'passed' && this.requested() !== null);

  readonly dateError = computed(() =>
    this.date() && this.date() > this.today()
      ? this.i18n.translate('outsideDecision.error.date')
      : '',
  );

  readonly countError = computed(() =>
    [this.yes(), this.no(), this.abstain()].some((c) => countOf(c) === undefined)
      ? this.i18n.translate('outsideDecision.error.count', { max: MAX_COUNT })
      : '',
  );

  readonly ready = computed(
    () =>
      !!this.result() &&
      !!this.date() &&
      !this.dateError() &&
      !!this.gremium() &&
      !this.countError() &&
      (!this.asksAmount() || draftError(this.draft(), this.requested(), true) === null),
  );

  private seq = 0;

  constructor() {
    effect(() => {
      const open = this.open();
      const id = this.applicationId();
      untracked(() => {
        if (open && id) this.reset();
      });
    });
  }

  close(): void {
    this.open.set(false);
  }

  private reset(): void {
    this.today.set(localToday());
    this.result.set(null);
    this.date.set('');
    this.yes.set('');
    this.no.set('');
    this.abstain.set('');
    this.draft.set(emptyDraft(this.requested(), true));
    this.refusal.set('');
    this.saving.set(false);
    this.api.committeeNames().subscribe({
      next: (rows) => this.gremien.set(rows),
      error: () => this.gremien.set([]),
    });
    this.pickGremium(this.gremiumId() ?? '');
  }

  /** Pick the Gremium and load its meetings for the optional link. */
  pickGremium(id: string): void {
    this.gremium.set(id);
    this.meeting.set('');
    this.meetings.set([]);
    this.seq = this.seq + 1;
    const seq = this.seq;
    if (!id) return;
    this.api.listMeetings(id).subscribe({
      next: (rows) => {
        if (seq === this.seq) this.meetings.set(rows);
      },
      error: () => {},
    });
  }

  private body(result: OutsideResult): OutsideDecisionBody {
    const decision = this.asksAmount() ? toProposal(this.draft(), this.requested(), true) : null;
    return {
      result,
      meetingDate: this.date(),
      gremiumId: this.gremium(),
      yes: countOf(this.yes()) ?? null,
      no: countOf(this.no()) ?? null,
      abstain: countOf(this.abstain()) ?? null,
      meetingId: this.meeting() || null,
      decision,
    };
  }

  submit(): void {
    const id = this.applicationId();
    const result = this.result();
    if (!id || !result || !this.ready() || this.saving()) return;
    this.saving.set(true);
    this.refusal.set('');
    this.api.recordOutsideDecision(id, this.body(result)).subscribe({
      next: () => {
        this.saving.set(false);
        this.open.set(false);
        this.toast.show({ text: this.i18n.translate('outsideDecision.saved'), kind: 'success' });
        this.done.emit();
      },
      error: (err: { status?: number; error?: ProblemDetail | null }) => {
        this.saving.set(false);
        const code = err.error?.code ?? '';
        if (err.status === 422 && code in REFUSALS) {
          this.refusal.set(this.i18n.translate(REFUSALS[code]));
          return;
        }
        if (err.status === 409) {
          this.toast.show({
            text: this.i18n.translate('outsideDecision.error.state'),
            kind: 'error',
          });
          this.open.set(false);
          this.done.emit();
          return;
        }
        this.toast.show({
          text: this.i18n.translate(
            err.status === 403
              ? 'applications.transitions.forbidden'
              : 'applications.actions.error',
          ),
          kind: 'error',
        });
      },
    });
  }
}
