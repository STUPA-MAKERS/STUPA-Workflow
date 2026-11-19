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
import type { ProblemDetail, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { localToday } from '@shared/date-format';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  NoteComponent,
  SelectFieldComponent,
  type SelectOption,
  TextareaComponent,
  ToastService,
} from '@stupa-makers/ui-kit';

/** The shortest reason of a change (spec 001620, as the server). */
export const MIN_REASON = 10;
/** The longest reason of a change (as the server). */
export const MAX_REASON = 2000;

/** The server refused the change: the codes of the 422 answers. */
const REFUSALS: Record<string, TranslationKey> = {
  approved_amount_unchanged: 'amendAmount.error.unchanged',
  approved_amount_invalid: 'decision.error.amountInvalid',
  decision_date_invalid: 'outsideDecision.error.date',
  gremium_unknown: 'outsideDecision.error.gremium',
};

function toNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * "Genehmigten Betrag ändern" (spec 001620): change the approved amount of an approved
 * application after a new decision of a Gremium. Needs `application.amend_decision`.
 *
 * The dialog asks for the new amount, a reason of at least 10 characters, the date of
 * the decision (not after today) and the Gremium. A new amount above the requested one
 * is allowed and shows a warning (spec 001622). The applicant gets a mail with the old
 * and the new amount (spec 001621).
 */
@Component({
  selector: 'app-amend-amount-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    NoteComponent,
    SelectFieldComponent,
    TextareaComponent,
  ],
  templateUrl: './amend-amount-dialog.component.html',
  styleUrl: './amend-amount-dialog.component.scss',
})
export class AmendAmountDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input<Uuid | null>(null);
  readonly applicationTitle = input('');
  /** The requested amount (decimal string). */
  readonly requested = input<string | null>(null);
  /** The approved amount now, or null for "as requested". */
  readonly approved = input<string | null>(null);
  readonly currency = input<string | null>('EUR');
  /** The preset of the Gremium picker. */
  readonly gremiumId = input<Uuid | null>(null);
  readonly open = model(false);
  /** The amount was changed: the caller loads again. */
  readonly done = output<void>();

  readonly amount = signal('');
  readonly reason = signal('');
  readonly date = signal('');
  readonly gremium = signal('');
  readonly saving = signal(false);
  readonly refusal = signal('');
  /** Today, read again on each opening. */
  readonly today = signal(localToday());
  private readonly gremien = signal<{ id: Uuid; name: string }[]>([]);

  readonly maxReason = MAX_REASON;

  /** The amount that holds now: the approved one, else the requested one. */
  readonly current = computed(() => this.approved() ?? this.requested());

  readonly gremiumOptions = computed<SelectOption[]>(() =>
    this.gremien().map((g) => ({ value: g.id, label: g.name })),
  );

  readonly amountError = computed(() => {
    const text = this.amount();
    if (text.trim() === '') return '';
    const n = toNumber(text);
    if (n === null || n < 0 || !/^\d+(\.\d{1,2})?$/.test(text)) {
      return this.i18n.translate('decision.error.amountInvalid');
    }
    const current = toNumber(this.current());
    return current !== null && n === current ? this.i18n.translate('amendAmount.error.unchanged') : '';
  });

  /** Spec 001622: an amount above the requested one is allowed, with a warning. */
  readonly aboveRequested = computed(() => {
    const n = toNumber(this.amount());
    const req = toNumber(this.requested());
    return n !== null && req !== null && n > req && !this.amountError();
  });

  readonly reasonShort = computed(() => {
    const length = this.reason().trim().length;
    return length > 0 && length < MIN_REASON;
  });

  readonly dateError = computed(() =>
    this.date() && this.date() > this.today()
      ? this.i18n.translate('outsideDecision.error.date')
      : '',
  );

  readonly ready = computed(
    () =>
      this.amount().trim() !== '' &&
      !this.amountError() &&
      this.reason().trim().length >= MIN_REASON &&
      this.reason().trim().length <= MAX_REASON &&
      !!this.date() &&
      !this.dateError() &&
      !!this.gremium(),
  );

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
    this.amount.set(this.current() ?? '');
    this.reason.set('');
    this.date.set('');
    this.gremium.set(this.gremiumId() ?? '');
    this.refusal.set('');
    this.saving.set(false);
    this.api.committeeNames().subscribe({
      next: (rows) => this.gremien.set(rows),
      error: () => this.gremien.set([]),
    });
  }

  submit(): void {
    const id = this.applicationId();
    if (!id || !this.ready() || this.saving()) return;
    this.saving.set(true);
    this.refusal.set('');
    this.api
      .amendApprovedAmount(id, {
        approvedAmount: this.amount(),
        reason: this.reason().trim(),
        decisionDate: this.date(),
        gremiumId: this.gremium(),
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.open.set(false);
          this.toast.success(this.i18n.translate('amendAmount.saved'));
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
            this.toast.error(this.i18n.translate('amendAmount.error.state'));
            this.open.set(false);
            this.done.emit();
            return;
          }
          this.toast.error(
            this.i18n.translate(
              err.status === 403 ? 'applications.transitions.forbidden' : 'applications.actions.error',
            ),
          );
        },
      });
  }
}
