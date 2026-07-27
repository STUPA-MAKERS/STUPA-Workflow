import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { CurrencyInputComponent, DatepickerComponent, InputComponent } from '@stupa-makers/ui-kit';

/**
 * Formly field type `input` that uses the UI-kit input.
 *
 * This type bridges the form definition (forms engine) and the design system. A date
 * field (`props.type === 'date'`) renders the a11y-capable {@link DatepickerComponent}.
 * A currency field (`props.type === 'currency'`) renders the
 * {@link CurrencyInputComponent} with a euro symbol and localized formatting. Every
 * other field renders a plain UI-kit input.
 */
@Component({
  selector: 'app-formly-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, InputComponent, DatepickerComponent, CurrencyInputComponent],
  template: `
    @if (props.type === 'date') {
      <app-datepicker
        [formControl]="formControl"
        [label]="props.label ?? ''"
        [required]="!!props.required"
        [hint]="props['hint'] ?? ''"
        [min]="asString(props['min'])"
        [max]="asString(props['max'])"
        [error]="showError && formControl.errors ? (props['errorText'] ?? 'Ungültige Eingabe') : ''"
      />
    } @else if (props.type === 'currency') {
      <app-currency-input
        [formControl]="formControl"
        [label]="props.label ?? ''"
        [required]="!!props.required"
        [hint]="props['hint'] ?? ''"
        [placeholder]="props.placeholder ?? ''"
        [error]="showError && formControl.errors ? (props['errorText'] ?? 'Ungültige Eingabe') : ''"
      />
    } @else {
      <app-input
        [formControl]="formControl"
        [label]="props.label ?? ''"
        [type]="props.type ?? 'text'"
        [placeholder]="props.placeholder ?? ''"
        [required]="!!props.required"
        [hint]="props['hint'] ?? ''"
        [error]="showError && formControl.errors ? (props['errorText'] ?? 'Ungültige Eingabe') : ''"
      />
    }
  `,
})
export class FormlyInputType extends FieldType<FieldTypeConfig> {
  /** A form definition can declare `min` and `max` as numbers. The datepicker needs ISO strings. */
  asString(v: unknown): string {
    return v == null ? '' : String(v);
  }
}
