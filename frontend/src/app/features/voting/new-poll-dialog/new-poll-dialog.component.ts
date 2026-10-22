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
import type { Vote } from '@core/api/models';
import { problemDetail } from '@core/api/problem';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  SelectFieldComponent,
  type SelectOption,
  SwitchComponent,
  TextareaComponent,
  TimeInputComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminOptionsService } from '../../../pages/admin/admin-options.service';
import { PollEditorComponent } from '../poll-editor/poll-editor.component';
import { type PollDraft, emptyPollDraft, localMoment, pollDraftValid, pollInOf } from '../poll.util';

/** The end of a poll lies at least this far ahead (the server checks it too). */
export const POLL_MIN_RUNTIME_MS = 60 * 60 * 1000;

/**
 * "Neue Umfrage" (`/voting`, the FAB): a poll of a Gremium, outside a meeting.
 *
 * The person picks the Gremium (one where they hold `vote.manage`; the admin any), the
 * question, the mode and the options (`app-poll-editor`), the end (date and time, at
 * least one hour ahead) and "Geheime Umfrage". "Als Entwurf speichern" keeps it a draft,
 * "Starten" opens it at once; the members with `vote.cast` then get a mail. A date poll
 * is open by default, like every poll.
 */
@Component({
  selector: 'app-new-poll-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    DatepickerComponent,
    DialogComponent,
    FormsModule,
    IconComponent,
    PollEditorComponent,
    SelectFieldComponent,
    SwitchComponent,
    TextareaComponent,
    TimeInputComponent,
    TranslatePipe,
  ],
  templateUrl: './new-poll-dialog.component.html',
  styleUrl: './new-poll-dialog.component.scss',
})
export class NewPollDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly options = inject(AdminOptionsService);

  readonly open = input(false);
  /** The Gremium to preselect, for example the active list filter. */
  readonly gremiumId = input('');
  readonly closed = output<void>();
  /** The server created the poll. */
  readonly created = output<Vote>();

  readonly gremium = signal('');
  readonly question = signal('');
  readonly draft = signal<PollDraft>(emptyPollDraft());
  readonly endDate = signal('');
  readonly endTime = signal('');
  readonly secret = signal(false);
  readonly submitting = signal(false);
  /** The running submit saves a draft: its button shows the spinner. */
  readonly savingDraft = signal(false);
  readonly gremiumOptions = signal<SelectOption[]>([]);
  private optionsLoaded = false;

  /** The end as an ISO moment, or `null`. */
  readonly closesAt = computed(() => localMoment(this.endDate(), this.endTime()));
  /** The end lies at least one hour ahead. */
  readonly endOk = computed(() => {
    const at = this.closesAt();
    return !!at && new Date(at).getTime() >= Date.now() + POLL_MIN_RUNTIME_MS;
  });
  readonly canSubmit = computed(
    () =>
      !!this.gremium() &&
      !!this.question().trim() &&
      pollDraftValid(this.draft()) &&
      this.endOk() &&
      !this.submitting(),
  );

  constructor() {
    effect(() => {
      if (this.open()) untracked(() => this.reset());
    });
  }

  private reset(): void {
    this.question.set('');
    this.draft.set(emptyPollDraft());
    this.endDate.set('');
    this.endTime.set('');
    this.secret.set(false);
    this.submitting.set(false);
    this.savingDraft.set(false);
    this.gremium.set(this.gremiumId());
    if (this.optionsLoaded) this.keepKnownGremium();
    else this.loadOptions();
  }

  /** The Gremien where the person may create a poll: `vote.manage`, or the admin. */
  private loadOptions(): void {
    this.options.gremiumOptions().subscribe({
      next: (opts) => {
        this.gremiumOptions.set(
          opts.filter((o) => this.auth.canInGremium(String(o.value), 'vote.manage')),
        );
        this.optionsLoaded = true;
        this.keepKnownGremium();
      },
      error: () => {
        this.gremiumOptions.set([]);
        this.optionsLoaded = true;
        this.keepKnownGremium();
      },
    });
  }

  /** A preselected Gremium is a choice only when the person may create a poll there; a
   *  single choice is preselected. */
  private keepKnownGremium(): void {
    const opts = this.gremiumOptions();
    const id = this.gremium();
    if (id && !opts.some((o) => o.value === id)) this.gremium.set('');
    if (!this.gremium() && opts.length === 1) this.gremium.set(String(opts[0]!.value));
  }

  cancel(): void {
    this.closed.emit();
  }

  /** "Starten" (`draft` false) or "Als Entwurf speichern" (`draft` true). */
  submit(draft: boolean): void {
    if (!this.canSubmit()) return;
    this.submitting.set(true);
    this.savingDraft.set(draft);
    this.api
      .createPoll({
        kind: 'poll',
        eligibleGroup: this.gremium(),
        question: this.question().trim(),
        ...pollInOf(this.draft()),
        secret: this.secret(),
        closesAt: this.closesAt()!,
        draft,
      })
      .subscribe({
        next: (vote) => {
          this.submitting.set(false);
          this.toast.success(this.i18n.translate(draft ? 'poll.toast.saved' : 'poll.toast.started'));
          this.created.emit(vote);
        },
        error: (err: unknown) => {
          this.submitting.set(false);
          const detail = problemDetail(err);
          const base = this.i18n.translate('meetings.toast.actionFailed');
          this.toast.error(detail ? `${base}: ${detail}` : base);
        },
      });
  }
}
