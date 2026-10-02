import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';

interface SelectOption {
  value: string;
  label: string;
}

/** Formly field type `select`: single choice (form definition `select`). */
@Component({
  selector: 'app-formly-select',
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
        <select
          class="field__control"
          [id]="controlId"
          [formControl]="formControl"
          [attr.aria-invalid]="showError ? 'true' : null"
          [attr.aria-describedby]="describedBy"
        >
          <option value="" disabled>
            {{ props.placeholder ?? ('formly.select.placeholder' | t) }}
          </option>
          @for (opt of optionList; track opt.value) {
            <option [value]="opt.value">{{ opt.label }}</option>
          }
        </select>
        <svg class="field__chevron" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </div>
      @if (props.description && !showError) {
        <p class="field__hint" [id]="controlId + '-hint'">{{ props.description }}</p>
      }
      @if (showError) {
        <p class="field__error" [id]="controlId + '-error'" role="alert">
          {{ props['errorText'] ?? ('formly.select.error' | t) }}
        </p>
      }
    </div>
  `,
  styleUrl: './formly-select.type.scss',
})
export class FormlySelectType extends FieldType<FieldTypeConfig> {
  get controlId(): string {
    return `${this.field.id ?? 'app-select'}`;
  }
  get optionList(): SelectOption[] {
    return (this.props.options as SelectOption[] | undefined) ?? [];
  }
  get describedBy(): string | null {
    if (this.showError) return `${this.controlId}-error`;
    if (this.props.description) return `${this.controlId}-hint`;
    return null;
  }
}
