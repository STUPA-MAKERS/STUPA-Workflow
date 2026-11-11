import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import {
  ANSWER_KEYS,
  type Appointment,
  CalendarApiService,
} from '@core/api/calendar.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  AvatarComponent,
  ButtonComponent,
  ChipComponent,
  ConfirmDialogComponent,
  DialogComponent,
  IconComponent,
  SegmentedComponent,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { CALENDAR_NOW } from '../calendar-grid.util';
import { answerKey, answerKind, hasEnded, spanText } from '../calendar.util';

/**
 * The dialog of one Termin (§ 000714, 000719): when, where, from whom, the description,
 * the invited Gremien and persons and the answers as a list of names.
 *
 * An invited person answers with Zusage, Vorbehalt or Absage until the Termin ends. The
 * creator and a person with `calendar.manage` change and delete the Termin (`canEdit`
 * comes from the server). On a phone the kit shows the dialog as a bottom sheet.
 */
@Component({
  selector: 'app-appointment-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    AvatarComponent,
    ButtonComponent,
    ChipComponent,
    ConfirmDialogComponent,
    DialogComponent,
    IconComponent,
    SegmentedComponent,
    StatusTextComponent,
    TranslatePipe,
  ],
  templateUrl: './appointment-detail.component.html',
  styleUrl: './appointment-detail.component.scss',
})
export class AppointmentDetailComponent {
  private readonly api = inject(CalendarApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly now = inject(CALENDAR_NOW);

  readonly open = input(false);
  readonly appointment = input<Appointment | null>(null);

  readonly closed = output<void>();
  /** The person asks for the edit dialog. */
  readonly edit = output<Appointment>();
  /** The Termin with the new answer of the person. */
  readonly answered = output<Appointment>();
  readonly removed = output<Appointment>();

  readonly confirming = signal(false);
  readonly removing = signal(false);
  readonly answering = signal(false);

  readonly when = computed(() => {
    const a = this.appointment();
    return a ? spanText(a, this.i18n.formatLocale()) : '';
  });
  /** The answer control shows for an invited person until the Termin ends. */
  readonly canAnswer = computed(() => {
    const a = this.appointment();
    return !!a && a.invited && !hasEnded(a, this.now());
  });
  readonly answerOptions = computed(() =>
    ANSWER_KEYS.map((key) => ({ value: key, label: this.i18n.translate(answerKey(key)) })),
  );
  readonly hasInvited = computed(() => {
    const a = this.appointment();
    return !!a && a.gremien.length + a.persons.length > 0;
  });

  readonly answerKey = answerKey;
  readonly answerKind = answerKind;

  setAnswer(value: string | null): void {
    const a = this.appointment();
    const answer = ANSWER_KEYS.find((key) => key === value);
    if (!a || !answer || answer === a.myAnswer || this.answering()) return;
    this.answering.set(true);
    this.api.answer(a.id, answer).subscribe({
      next: (result) => {
        this.answering.set(false);
        this.answered.emit(result);
      },
      error: () => {
        this.answering.set(false);
        this.toast.error(this.i18n.translate('calendar.toast.answerFailed'));
      },
    });
  }

  remove(): void {
    const a = this.appointment();
    if (!a || this.removing()) return;
    this.removing.set(true);
    this.api.remove(a.id).subscribe({
      next: () => {
        this.removing.set(false);
        this.confirming.set(false);
        this.toast.success(this.i18n.translate('calendar.toast.removed'));
        this.removed.emit(a);
      },
      error: () => {
        this.removing.set(false);
        this.toast.error(this.i18n.translate('calendar.toast.removeFailed'));
      },
    });
  }
}
