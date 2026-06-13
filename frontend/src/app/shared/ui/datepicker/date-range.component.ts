import { ChangeDetectionStrategy, Component, Input, signal } from '@angular/core';
import { FormsModule, NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';
import { DatepickerComponent } from './datepicker.component';

let nextId = 0;

/** Zeitraum-Wert: ISO-Start/-Ende (`YYYY-MM-DD`), je leer wenn ungesetzt. */
export interface DateRange {
  start: string;
  end: string;
}

/**
 * Zeitraum-Feld (#79): zwei gekoppelte native Datumsfelder (Start/Ende). Das Ende
 * kann nicht vor dem Start liegen (`min`/`max`-Kopplung). Wert ist `{ start, end }`;
 * `ControlValueAccessor` → Reactive Forms + `ngModel`. a11y über `<fieldset>` +
 * `<legend>` und `<label for>`-Bindung je Feld; native Kalender-UI folgt dem Theme
 * (`color-scheme`), Dark/Light via Tokens.
 */
@Component({
  selector: 'app-date-range',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DatepickerComponent],
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: DateRangeComponent, multi: true }],
  templateUrl: './date-range.component.html',
  styleUrl: './date-range.component.scss',
})
export class DateRangeComponent implements ControlValueAccessor {
  @Input() legend = '';
  @Input() startLabel = '';
  @Input() endLabel = '';
  @Input() id = `app-date-range-${nextId++}`;

  readonly start = signal('');
  readonly end = signal('');
  readonly disabled = signal(false);

  private onChange: (value: DateRange) => void = () => {};
  onTouched: () => void = () => {};

  onStart(v: string): void {
    this.start.set(v);
    this.emit();
  }

  onEnd(v: string): void {
    this.end.set(v);
    this.emit();
  }

  private emit(): void {
    this.onChange({ start: this.start(), end: this.end() });
  }

  writeValue(value: DateRange | null): void {
    this.start.set(value?.start ?? '');
    this.end.set(value?.end ?? '');
  }
  registerOnChange(fn: (value: DateRange) => void): void {
    this.onChange = fn;
  }
  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }
  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }
}
