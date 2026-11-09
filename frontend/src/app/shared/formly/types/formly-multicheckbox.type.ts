import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';

interface MultiOption {
  readonly value: string;
  readonly label: string;
  readonly lang?: string;
}

/**
 * Formly field type `multicheckbox` for a multi-select field.
 *
 * The form definition calls this field `multiselect`. The model value is a string array
 * of the selected option values.
 */
@Component({
  selector: 'app-formly-multicheckbox',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  template: `
    <fieldset class="multi">
      <legend class="multi__legend">
        <span [attr.lang]="props['textLang'] ?? null">{{ props.label }}</span>
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
          <span class="multi__label" [attr.lang]="opt.lang ?? null">{{ opt.label }}</span>
        </label>
      }
      @if (props.description && !showError) {
        <p class="multi__hint" [attr.lang]="props['textLang'] ?? null">{{ props.description }}</p>
      }
      @if (showError) {
        <p class="multi__error" role="alert">
          {{ props['errorText'] ?? ('formly.multicheckbox.error' | t) }}
        </p>
      }
    </fieldset>
  `,
  styleUrl: './formly-multicheckbox.type.scss',
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
    const cur = this.current();
    const set = new Set(checked ? [...cur, value] : cur.filter((v) => v !== value));
    this.formControl.setValue([...set]);
    this.formControl.markAsDirty();
    this.formControl.markAsTouched();
  }
}
