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
import { GremienApiService } from '@core/api/gremien.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  DialogComponent,
  ErrorTextComponent,
  InputComponent,
  TextareaComponent,
  ToastService,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';

/** The limits of the server (spec 001854). */
export const NOTIFY_MAX_SUBJECT = 200;
export const NOTIFY_MAX_MESSAGE = 10_000;

/** The error of the subject, or `null`: it must hold 1 to 200 characters after a trim. */
export function subjectError(subject: string): TranslationKey | null {
  const text = subject.trim();
  if (text === '') return 'gremien.notify.subjectRequired';
  return text.length > NOTIFY_MAX_SUBJECT ? 'gremien.notify.subjectTooLong' : null;
}

/** The error of the message, or `null`: it must hold 1 to 10000 characters after a trim. */
export function messageError(message: string): TranslationKey | null {
  return message.trim() === '' ? 'gremien.notify.messageRequired' : null;
}

/**
 * "Mitglieder benachrichtigen" (specs 001850-001854): a subject and a plain-text message
 * that the server mails to each member and to each person in the substitute pool of the
 * gremium. The dialog asks for no confirmation; after the send a toast tells the number
 * of recipients. The server stays authoritative for `members.notify`.
 */
@Component({
  selector: 'app-gremium-notify-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    ErrorTextComponent,
    InputComponent,
    TextareaComponent,
  ],
  templateUrl: './gremium-notify-dialog.component.html',
  styleUrl: './gremium-notify-dialog.component.scss',
})
export class GremiumNotifyDialogComponent {
  private readonly api = inject(GremienApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  readonly gremiumId = input.required<string>();
  readonly gremiumName = input('');
  readonly closed = output<void>();

  readonly maxMessage = NOTIFY_MAX_MESSAGE;
  readonly subject = signal('');
  readonly message = signal('');
  readonly sending = signal(false);
  /** The person pressed "Senden" once: the errors show from now on. */
  readonly tried = signal(false);

  readonly subjectErr = computed(() => (this.tried() ? subjectError(this.subject()) : null));
  readonly messageErr = computed(() => (this.tried() ? messageError(this.message()) : null));

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.subject.set('');
        this.message.set('');
        this.tried.set(false);
      });
    });
  }

  text(key: TranslationKey | null): string {
    return key === null ? '' : this.i18n.translate(key);
  }

  cancel(): void {
    this.closed.emit();
  }

  send(): void {
    this.tried.set(true);
    if (subjectError(this.subject()) || messageError(this.message()) || this.sending()) return;
    this.sending.set(true);
    const body = { subject: this.subject().trim(), message: this.message().trim() };
    this.api.notify(this.gremiumId(), body).subscribe({
      next: ({ recipients }) => {
        this.sending.set(false);
        this.toast.show({
          text:
            recipients === 1
              ? this.i18n.translate('gremien.notify.sent1')
              : this.i18n.translate('gremien.notify.sent', { n: recipients }),
          kind: 'success',
        });
        this.closed.emit();
      },
      error: () => {
        this.sending.set(false);
        this.toast.show({ text: this.i18n.translate('gremien.notify.error'), kind: 'error' });
      },
    });
  }
}
