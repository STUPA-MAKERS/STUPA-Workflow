import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';

/** Formly-Feldtyp `checkbox` — boolesche Zustimmung (Form-Definition `checkbox`). */
@Component({
  selector: 'app-formly-checkbox',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
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
          {{ props['errorText'] ?? 'Bitte bestätigen.' }}
        </p>
      }
    </div>
  `,
  styles: [
    `
      .check {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .check__row {
        display: inline-flex;
        /* Box vertikal zentriert zum Label → gleich viel Luft oben wie unten (#17),
           wie bei <app-checkbox>. */
        align-items: center;
        gap: var(--space-3);
        cursor: pointer;
      }
      .check__box {
        flex: none;
        width: 1.15rem;
        height: 1.15rem;
        margin: 0;
        accent-color: var(--color-primary);
      }
      .check__label {
        font-size: var(--fs-md);
        color: var(--color-text);
      }
      .check__req {
        color: var(--color-danger);
      }
      .check__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .check__error {
        font-size: var(--fs-xs);
        color: var(--color-danger);
      }
    `,
  ],
})
export class FormlyCheckboxType extends FieldType<FieldTypeConfig> {
  get controlId(): string {
    return `${this.field.id ?? 'app-checkbox'}`;
  }
}
