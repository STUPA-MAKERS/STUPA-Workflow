import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { CurrencyInputComponent, DatepickerComponent, InputComponent } from '@stupa-makers/ui-kit';

/**
 * Formly-Feldtyp `input`, der das UI-Kit-Input nutzt — Brücke zwischen der
 * Form-Definition (forms-Engine, T-11) und dem Design-System. Datumsfelder
 * (`props.type === 'date'`) rendern den a11y-fähigen {@link DatepickerComponent};
 * Währungsfelder (`props.type === 'currency'`) den {@link CurrencyInputComponent}
 * (€-Symbol + lokalisierte Formatierung) — sonst ein rohes UI-Kit-Input.
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
  /** `min`/`max` können numerisch deklariert sein; der Datepicker will ISO-Strings. */
  asString(v: unknown): string {
    return v == null ? '' : String(v);
  }
}
