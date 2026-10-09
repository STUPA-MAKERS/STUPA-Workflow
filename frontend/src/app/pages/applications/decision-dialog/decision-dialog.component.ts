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
import { ApiClient } from '@core/api/api-client.service';
import type { ProblemDetail, Transition, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DecisionEditorComponent } from '@shared/decision/decision-editor.component';
import {
  type DecisionDraft,
  draftError,
  emptyDraft,
  toProposal,
} from '@shared/decision/decision.util';
import { ButtonComponent, DialogComponent, ToastService } from '@stupa-makers/ui-kit';

/** The server refused the decision: the codes of the 422 answers. */
const DECISION_CODES: Record<string, Parameters<I18nService['translate']>[0]> = {
  approved_amount_invalid: 'decision.error.amountInvalid',
  approved_amount_exceeds_requested: 'decision.error.amountExceeds',
  decision_not_allowed: 'decision.error.notAllowed',
};

/**
 * Fire a transition into an accepted state of the cost center (F1, `allowsDecision`).
 *
 * The dialog offers the decision: switched off, the transition fires as before
 * ("as requested, no conditions"). Switched on, it takes the approved amount and the
 * conditions. Other transitions never open this dialog. The detail and the row menu of
 * the list both open it; `done` fires after the transition, and also after a 409, so
 * the caller loads the application again.
 */
@Component({
  selector: 'app-decision-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, DialogComponent, DecisionEditorComponent],
  templateUrl: './decision-dialog.component.html',
  styleUrl: './decision-dialog.component.scss',
})
export class DecisionDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input<Uuid | null>(null);
  readonly applicationTitle = input('');
  /** The requested amount of the application (decimal string). */
  readonly requested = input<string | null>(null);
  readonly currency = input<string | null>('EUR');
  /** The transition to fire. It must have `allowsDecision`. */
  readonly transition = input<Transition | null>(null);
  readonly open = model(false);
  readonly done = output<void>();

  protected readonly draft = signal<DecisionDraft>(emptyDraft(null));
  protected readonly saving = signal(false);
  /** The reason the server refused the decision, shown in the dialog. */
  protected readonly refusal = signal('');

  protected readonly invalid = computed(() => draftError(this.draft(), this.requested()) !== null);
  protected readonly confirmLabel = computed(
    () => this.transition()?.label || this.i18n.translate('applications.transitions.fallback'),
  );

  constructor() {
    effect(() => {
      const open = this.open();
      const transition = this.transition();
      untracked(() => {
        if (open && transition) {
          this.draft.set(emptyDraft(this.requested()));
          this.refusal.set('');
          this.saving.set(false);
        }
      });
    });
  }

  close(): void {
    this.open.set(false);
  }

  submit(): void {
    const id = this.applicationId();
    const transition = this.transition();
    if (!id || !transition || this.saving() || this.invalid()) return;
    this.saving.set(true);
    this.refusal.set('');
    const decision = toProposal(this.draft(), this.requested());
    this.api
      .fireTransition(id, decision ? { transitionId: transition.id, decision } : { transitionId: transition.id })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.toast.success(this.i18n.translate('applications.actions.success'));
          this.open.set(false);
          this.done.emit();
        },
        error: (err: { status?: number; error?: ProblemDetail | null }) => {
          this.saving.set(false);
          const code = err.error?.code ?? '';
          if (err.status === 422 && code in DECISION_CODES) {
            this.refusal.set(this.i18n.translate(DECISION_CODES[code]));
            return;
          }
          if (err.status === 409) {
            this.toast.error(this.i18n.translate('applications.actions.conflict'));
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
