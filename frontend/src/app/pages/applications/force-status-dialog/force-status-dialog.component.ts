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
import { type ApplicationState, FORCE_REASONS, type ForceReason, type Uuid } from '@core/api/models';
import { DecisionEditorComponent } from '@shared/decision/decision-editor.component';
import { type DecisionDraft, draftError, emptyDraft, toProposal } from '@shared/decision/decision.util';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  SelectFieldComponent,
  type SelectOption,
  TextareaComponent,
  ToastService,
} from '@stupa-makers/ui-kit';

/** The shortest note of the reason `other` (spec 001650, as the server). */
export const MIN_OTHER_NOTE = 10;

/**
 * "Status setzen": put an application straight into a state of its flow
 * (`application.force_status`). The server bypasses the guards. A reason from the list
 * is mandatory (spec 001650); the note is optional, except for `other`, which needs a
 * note of at least 10 characters. A move into an approved state from one that is not
 * approved asks for the approved amount (spec 001653), as a manual approval does.
 *
 * The flow states load each time the dialog opens for an application. The list (row
 * menu) and the detail (overflow menu) both open it; `done` fires after a success, so
 * the caller can load the application again.
 */
@Component({
  selector: 'app-force-status-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    DecisionEditorComponent,
    SelectFieldComponent,
    TextareaComponent,
  ],
  templateUrl: './force-status-dialog.component.html',
  styleUrl: './force-status-dialog.component.scss',
})
export class ForceStatusDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input<Uuid | null>(null);
  /** The current state. The picker leaves it out. */
  readonly currentStateId = input<Uuid | null>(null);
  /** The requested amount (decimal string); `null` for an application without money. */
  readonly requested = input<string | null>(null);
  readonly currency = input<string | null>('EUR');
  readonly open = model(false);
  /** The state was set. */
  readonly done = output<void>();

  private readonly states = signal<ApplicationState[]>([]);
  readonly choice = signal('');
  readonly reason = signal<ForceReason | ''>('');
  readonly note = signal('');
  readonly saving = signal(false);
  readonly draft = signal<DecisionDraft>(emptyDraft(null, true));

  /** The target is approved and the current state is not: the amount is required. */
  readonly needsAmount = computed(() => {
    if (this.requested() === null) return false;
    const states = this.states();
    const target = states.find((s) => s.id === this.choice());
    const current = states.find((s) => s.id === this.currentStateId());
    return !!target?.isApproved && !current?.isApproved;
  });
  private readonly amountMissing = computed(
    () => this.needsAmount() && draftError(this.draft(), this.requested(), true) !== null,
  );

  /** The reasons of the list, in their order. */
  readonly reasonOptions = computed<SelectOption[]>(() =>
    FORCE_REASONS.map((r) => ({
      value: r,
      label: this.i18n.translate(`applications.forceReason.${r}`),
    })),
  );

  /** `other` needs a note of at least 10 characters. */
  readonly noteRequired = computed(() => this.reason() === 'other');
  readonly noteMissing = computed(
    () => this.noteRequired() && this.note().trim().length < MIN_OTHER_NOTE,
  );
  readonly ready = computed(
    () => !!this.choice() && !!this.reason() && !this.noteMissing() && !this.amountMissing(),
  );

  /** Every state of the flow except the current one. */
  readonly options = computed<SelectOption[]>(() => {
    const current = this.currentStateId() ?? '';
    return this.states()
      .filter((s) => s.id !== current)
      .map((s) => ({ value: s.id, label: s.label || s.key }));
  });

  private seq = 0;

  constructor() {
    effect(() => {
      const open = this.open();
      const id = this.applicationId();
      untracked(() => {
        if (open && id) this.reset(id);
      });
    });
  }

  close(): void {
    this.open.set(false);
  }

  private reset(id: Uuid): void {
    this.choice.set('');
    this.reason.set('');
    this.note.set('');
    this.draft.set(emptyDraft(this.requested(), true));
    this.states.set([]);
    this.seq = this.seq + 1;
    const seq = this.seq;
    this.api.flowStates(id).subscribe({
      next: (states) => {
        if (seq === this.seq) this.states.set(states);
      },
      error: () => {},
    });
  }

  /** Force the state. A 403 or a 409 answer shows its own toast. */
  submit(): void {
    const id = this.applicationId();
    const stateId = this.choice();
    const reason = this.reason();
    const note = this.note().trim();
    if (!id || !reason || !this.ready() || this.saving()) return;
    this.saving.set(true);
    const decision = this.needsAmount() ? toProposal(this.draft(), this.requested(), true) : null;
    this.api.forceStatus(id, { stateId, reason, note: note || null, ...(decision ? { decision } : {}) }).subscribe({
      next: () => {
        this.saving.set(false);
        this.open.set(false);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.done.emit();
      },
      error: (err: { status?: number }) => {
        this.saving.set(false);
        const key =
          err.status === 422
            ? 'decision.error.amountRequired'
            : err.status === 403
            ? 'applications.transitions.forbidden'
            : err.status === 409
              ? 'applications.actions.conflict'
              : 'applications.actions.error';
        this.toast.error(this.i18n.translate(key));
      },
    });
  }
}
