import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';

/** Formly-Feldtyp `textarea` — mehrzeiliges Textfeld (Form-Definition `textarea`). */
@Component({
  selector: 'app-formly-textarea',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  template: `
    <div class="field">
      <label class="field__label" [for]="controlId">
        {{ props.label }}
        @if (props.required) {
          <span class="field__req" aria-hidden="true">*</span>
        }
      </label>
      <textarea
        class="field__control"
        [id]="controlId"
        [formControl]="formControl"
        [attr.placeholder]="props.placeholder || null"
        [attr.aria-invalid]="showError ? 'true' : null"
        [attr.aria-describedby]="describedBy"
        [rows]="props['rows'] ?? 4"
      ></textarea>
      @if (props.description && !showError) {
        <p class="field__hint" [id]="controlId + '-hint'">{{ props.description }}</p>
      }
      @if (showError) {
        <p class="field__error" [id]="controlId + '-error'" role="alert">
          {{ props['errorText'] ?? 'Ungültige Eingabe' }}
        </p>
      }
    </div>
  `,
  styles: [
    `
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .field__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .field__req {
        color: var(--color-danger);
      }
      .field__control {
        padding: var(--space-3) var(--space-4);
        font: inherit;
        font-size: var(--fs-md);
        color: var(--color-text);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        resize: vertical;
      }
      .field__control[aria-invalid='true'] {
        border-color: var(--color-danger);
      }
      .field__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .field__error {
        font-size: var(--fs-xs);
        color: var(--color-danger);
      }
    `,
  ],
})
export class FormlyTextareaType extends FieldType<FieldTypeConfig> {
  get controlId(): string {
    return `${this.field.id ?? 'app-textarea'}`;
  }
  get describedBy(): string | null {
    if (this.showError) return `${this.controlId}-error`;
    if (this.props.description) return `${this.controlId}-hint`;
    return null;
  }
}
