import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { CurrencyInputComponent, DatepickerComponent, InputComponent } from '@stupa-makers/ui-kit';

/**
 * Formly field type `input` that uses the UI-kit input — the bridge between the
 * form definition (forms engine) and the design system. Date fields
 * (`props.type === 'date'`) render the a11y-capable {@link DatepickerComponent};
 * currency fields (`props.type === 'currency'`) the {@link CurrencyInputComponent}
 * (€ symbol + localized formatting) — otherwise a plain UI-kit input.
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
  /** `min`/`max` may be declared numeric; the datepicker wants ISO strings. */
  asString(v: unknown): string {
    return v == null ? '' : String(v);
  }
}
