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
import type { ApplicationState, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  SelectComponent,
  ToastService,
  type SelectOption,
} from '@stupa-makers/ui-kit';

/**
 * "Status setzen": put an application straight into a state of its flow
 * (`application.force_status`). The server bypasses the guards; a reason is mandatory.
 *
 * The flow states load each time the dialog opens for an application. The list (row
 * menu) and the detail (overflow menu) both open it; `done` fires after a success, so
 * the caller can load the application again.
 */
@Component({
  selector: 'app-force-status-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, DialogComponent, SelectComponent],
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
  readonly open = model(false);
  /** The state was set. */
  readonly done = output<void>();

  private readonly states = signal<ApplicationState[]>([]);
  readonly choice = signal('');
  readonly note = signal('');
  readonly saving = signal(false);

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
    this.note.set('');
    this.states.set([]);
    const seq = ++this.seq;
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
    const note = this.note().trim();
    if (!id || !stateId || !note || this.saving()) return;
    this.saving.set(true);
    this.api.forceStatus(id, { stateId, note }).subscribe({
      next: () => {
        this.saving.set(false);
        this.open.set(false);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.done.emit();
      },
      error: (err: { status?: number }) => {
        this.saving.set(false);
        const key =
          err.status === 403
            ? 'applications.transitions.forbidden'
            : err.status === 409
              ? 'applications.actions.conflict'
              : 'applications.actions.error';
        this.toast.error(this.i18n.translate(key));
      },
    });
  }
}
