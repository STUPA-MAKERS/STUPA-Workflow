import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';

interface MultiOption {
  value: string;
  label: string;
}

/** Formly-Feldtyp `multicheckbox` — Mehrfachauswahl (Form-Definition `multiselect`).
 * Modellwert ist ein String-Array der gewählten Options-Values. */
@Component({
  selector: 'app-formly-multicheckbox',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <fieldset class="multi">
      <legend class="multi__legend">
        {{ props.label }}
        @if (props.required) {
          <span class="multi__req" aria-hidden="true">*</span>
        }
      </legend>
      @for (opt of optionList; track opt.value) {
        <label class="multi__row">
          <input
            type="checkbox"
            class="multi__box"
            [checked]="isChecked(opt.value)"
            (change)="toggle(opt.value, $any($event.target).checked)"
          />
          <span class="multi__label">{{ opt.label }}</span>
        </label>
      }
      @if (props.description && !showError) {
        <p class="multi__hint">{{ props.description }}</p>
      }
      @if (showError) {
        <p class="multi__error" role="alert">{{ props['errorText'] ?? 'Bitte auswählen.' }}</p>
      }
    </fieldset>
  `,
  styles: [
    `
      .multi {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        border: none;
        padding: 0;
        margin: 0;
      }
      .multi__legend {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
        padding: 0;
        margin-bottom: var(--space-1);
      }
      .multi__req {
        color: var(--color-danger);
      }
      .multi__row {
        display: inline-flex;
        align-items: center;
        gap: var(--space-3);
        cursor: pointer;
      }
      .multi__box {
        width: 1.15rem;
        height: 1.15rem;
        accent-color: var(--color-primary);
      }
      .multi__label {
        font-size: var(--fs-md);
        color: var(--color-text);
      }
      .multi__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .multi__error {
        font-size: var(--fs-xs);
        color: var(--color-danger);
      }
    `,
  ],
})
export class FormlyMultiCheckboxType extends FieldType<FieldTypeConfig> {
  get optionList(): MultiOption[] {
    return (this.props.options as MultiOption[] | undefined) ?? [];
  }

  private current(): string[] {
    const v = this.formControl.value;
    return Array.isArray(v) ? (v as string[]) : [];
  }

  isChecked(value: string): boolean {
    return this.current().includes(value);
  }

  toggle(value: string, checked: boolean): void {
    const set = new Set(this.current());
    if (checked) set.add(value);
    else set.delete(value);
    this.formControl.setValue([...set]);
    this.formControl.markAsDirty();
    this.formControl.markAsTouched();
  }
}
