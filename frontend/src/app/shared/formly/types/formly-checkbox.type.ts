import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** Formly field type `checkbox` for a boolean consent (form definition `checkbox`). */
@Component({
  selector: 'app-formly-checkbox',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, TranslatePipe],
  template: `
    <div class="check">
      <label class="check__row">
        <input
          type="checkbox"
          class="check__box"
          [formControl]="formControl"
          [attr.aria-invalid]="showError ? 'true' : null"
          [attr.aria-describedby]="showError ? controlId + '-error' : null"
        />
        <span class="check__label">
          {{ props.label }}
          @if (props.required) {
            <span class="check__req" aria-hidden="true">*</span>
          }
        </span>
      </label>
      @if (props.description && !showError) {
        <p class="check__hint">{{ props.description }}</p>
      }
      @if (showError) {
        <p class="check__error" [id]="controlId + '-error'" role="alert">
          {{ props['errorText'] ?? ('formly.checkbox.error' | t) }}
        </p>
      }
    </div>
  `,
  styleUrl: './formly-checkbox.type.scss',
})
export class FormlyCheckboxType extends FieldType<FieldTypeConfig> {
  get controlId(): string {
    return `${this.field.id ?? 'app-checkbox'}`;
  }
}
