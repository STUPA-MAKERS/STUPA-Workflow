import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** Formly field type `textarea`: multi-line text field (form definition `textarea`). */
@Component({
  selector: 'app-formly-textarea',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, TranslatePipe],
  template: `
    <div class="field">
      <div class="field__box" [class.field__box--invalid]="showError">
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
      </div>
      @if (props.description && !showError) {
        <p class="field__hint" [id]="controlId + '-hint'">{{ props.description }}</p>
      }
      @if (showError) {
        <p class="field__error" [id]="controlId + '-error'" role="alert">
          {{ props['errorText'] ?? ('formly.field.error' | t) }}
        </p>
      }
    </div>
  `,
  styleUrl: './formly-textarea.type.scss',
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
