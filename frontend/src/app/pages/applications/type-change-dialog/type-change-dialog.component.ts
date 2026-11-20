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
import type { ApplicationType, TypeChangeField, TypeChangePreview, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import {
  ButtonComponent,
  DialogComponent,
  SelectFieldComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';

/** A failed request: its status and the problem body of the server. */
interface FailedRequest {
  readonly status?: number;
  readonly error?: { readonly code?: string } | null;
}

/** The text of a failed preview: the reason of the server where the dialog knows it. */
function previewErrorKey(err: FailedRequest): TranslationKey {
  switch (err.error?.code) {
    case 'type_change_not_submitted':
      return 'applications.typeChange.error.notSubmitted';
    case 'type_change_type_not_submittable':
      return 'applications.typeChange.error.noForm';
    default:
      return err.status === 403
        ? 'applications.transitions.forbidden'
        : 'applications.typeChange.error.load';
  }
}

/**
 * "Antragsart ändern" (`application.change_type`, specs 001660-001663).
 *
 * The person picks the new Antragsart. The dialog then loads the preview: the fields that
 * move, the required fields that stay empty and the values that only the old version keeps.
 * With an empty required field the change sends the application back to the applicant, so
 * the dialog offers the transitions into an editable state and a message. Without such a
 * transition the change is not possible. `done` fires after a success.
 */
@Component({
  selector: 'app-type-change-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, DialogComponent, SelectFieldComponent],
  templateUrl: './type-change-dialog.component.html',
  styleUrl: './type-change-dialog.component.scss',
})
export class TypeChangeDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input<Uuid | null>(null);
  /** The current Antragsart. The picker leaves it out. */
  readonly currentTypeId = input<Uuid | null>(null);
  /** The Antragsarten of the platform; the picker offers the active ones. */
  readonly types = input<readonly ApplicationType[]>([]);
  readonly open = model(false);
  /** The Antragsart was changed. */
  readonly done = output<void>();

  readonly typeId = signal('');
  readonly transitionId = signal('');
  readonly note = signal('');
  readonly preview = signal<TypeChangePreview | null>(null);
  readonly loading = signal(false);
  readonly saving = signal(false);
  /** The i18n key of why the preview failed, shown in the dialog. */
  readonly previewError = signal<TranslationKey | null>(null);

  /** Every active Antragsart except the current one. */
  readonly typeOptions = computed<SelectOption[]>(() => {
    const current = this.currentTypeId() ?? '';
    return this.types()
      .filter((t) => t.active && t.id !== current)
      .map((t) => ({ value: t.id, label: t.name }));
  });

  readonly transitionOptions = computed<SelectOption[]>(() => {
    const lang = this.i18n.uiLocale();
    return (this.preview()?.transitions ?? []).map((t) => ({
      value: t.id,
      label: `${resolveI18n(t.label, lang)} → ${resolveI18n(t.toStateLabel, lang)}`,
    }));
  });

  readonly missing = computed(() => this.labels(this.preview()?.missing));
  readonly dropped = computed(() => this.labels(this.preview()?.dropped));
  readonly carried = computed(() => this.labels(this.preview()?.carried));

  /** The change goes ahead: a preview, possible, and a transition when a field is missing. */
  readonly canSubmit = computed(() => {
    const p = this.preview();
    if (!p || !p.possible || this.loading()) return false;
    return p.missing.length === 0 || this.transitionId() !== '';
  });

  private seq = 0;

  constructor() {
    effect(() => {
      const open = this.open();
      untracked(() => {
        if (open) this.reset();
      });
    });
  }

  /** Close the dialog and drop the answer of a preview that is still loading. */
  close(): void {
    this.seq = this.seq + 1;
    this.loading.set(false);
    this.open.set(false);
  }

  private labels(fields: readonly TypeChangeField[] | undefined): string[] {
    const lang = this.i18n.uiLocale();
    return (fields ?? []).map((f) => resolveI18n(f.label, lang) || f.key);
  }

  private reset(): void {
    this.seq = this.seq + 1;
    this.typeId.set('');
    this.transitionId.set('');
    this.note.set('');
    this.preview.set(null);
    this.previewError.set(null);
    this.loading.set(false);
  }

  /** A new Antragsart was picked: load what the change does. */
  pickType(typeId: string): void {
    this.typeId.set(typeId);
    this.transitionId.set('');
    this.preview.set(null);
    this.previewError.set(null);
    const id = this.applicationId();
    if (!id || !typeId) return;
    this.seq = this.seq + 1;
    const seq = this.seq;
    this.loading.set(true);
    this.api.typeChangePreview(id, typeId).subscribe({
      next: (preview) => {
        if (seq !== this.seq) return;
        this.loading.set(false);
        this.preview.set(preview);
        const only = preview.transitions.length === 1 ? preview.transitions[0].id : '';
        this.transitionId.set(only);
      },
      error: (err: FailedRequest) => {
        if (seq !== this.seq) return;
        this.loading.set(false);
        this.previewError.set(previewErrorKey(err));
      },
    });
  }

  /** Change the Antragsart. A 403 or a 409 answer shows its own toast. */
  submit(): void {
    const id = this.applicationId();
    const preview = this.preview();
    if (!id || !preview || !this.canSubmit() || this.saving()) return;
    const sendBack = preview.missing.length > 0;
    const note = this.note().trim();
    this.saving.set(true);
    this.api
      .changeType(id, {
        typeId: preview.typeId,
        transitionId: sendBack ? this.transitionId() : null,
        note: sendBack && note ? note : null,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.open.set(false);
          this.toast.success(this.i18n.translate('applications.typeChange.success'));
          this.done.emit();
        },
        error: (err: { status?: number }) => {
          this.saving.set(false);
          const key =
            err.status === 403
              ? 'applications.transitions.forbidden'
              : err.status === 409
                ? 'applications.actions.conflict'
                : 'applications.typeChange.error.save';
          this.toast.error(this.i18n.translate(key));
        },
      });
  }
}
