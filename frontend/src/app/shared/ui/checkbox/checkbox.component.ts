import { ChangeDetectionStrategy, Component, Input, signal } from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';

let nextId = 0;

/**
 * Checkbox des UI-Kits. Boolescher Wert über `ControlValueAccessor`
 * (Reactive Forms + `ngModel`). Token-basiert (`accent-color` = CD-Primär),
 * sichtbarer Fokus-Ring (global `:focus-visible`), Label/`for`-Bindung für a11y.
 * Label-Text wird projiziert: `<app-checkbox [(ngModel)]="x">Text</app-checkbox>`.
 */
@Component({
  selector: 'app-checkbox',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: CheckboxComponent, multi: true }],
  templateUrl: './checkbox.component.html',
  styleUrl: './checkbox.component.scss',
})
export class CheckboxComponent implements ControlValueAccessor {
  @Input() id = `app-checkbox-${nextId++}`;
  @Input() hint = '';

  readonly checked = signal(false);
  readonly disabled = signal(false);

  private onChange: (value: boolean) => void = () => {};
  onTouched: () => void = () => {};

  onToggle(event: Event): void {
    const v = (event.target as HTMLInputElement).checked;
    this.checked.set(v);
    this.onChange(v);
  }

  writeValue(value: boolean | null): void {
    this.checked.set(!!value);
  }
  registerOnChange(fn: (value: boolean) => void): void {
    this.onChange = fn;
  }
  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }
  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }
}
