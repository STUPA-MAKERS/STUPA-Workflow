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
  template: `
    <fieldset class="dr">
      @if (legend) {
        <legend class="dr__legend">{{ legend }}</legend>
      }
      <div class="dr__row">
        <div class="dr__field">
          <app-datepicker
            [id]="id + '-start'"
            [ariaLabel]="startLabel"
            [max]="end()"
            [ngModel]="start()"
            (ngModelChange)="onStart($event)"
          />
        </div>
        <span class="dr__sep" aria-hidden="true">–</span>
        <div class="dr__field">
          <app-datepicker
            [id]="id + '-end'"
            [ariaLabel]="endLabel"
            [min]="start()"
            [ngModel]="end()"
            (ngModelChange)="onEnd($event)"
          />
        </div>
      </div>
    </fieldset>
  `,
  styles: [
    `
      .dr {
        border: 0;
        margin: 0;
        padding: 0;
        min-inline-size: 0;
      }
      .dr__legend {
        padding: 0;
        margin-bottom: var(--space-2);
        font-size: var(--fs-sm);
        font-weight: var(--fw-semibold);
        color: var(--color-text);
      }
      .dr__row {
        display: flex;
        align-items: end;
        gap: var(--space-3);
        flex-wrap: wrap;
      }
      .dr__field {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        flex: 1 1 9rem;
      }
      .dr__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .dr__control {
        color-scheme: light dark;
        padding: var(--space-3) var(--space-4);
        font: inherit;
        font-size: var(--fs-md);
        color: var(--color-text);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        transition: border-color var(--motion-fast) var(--ease-standard);
      }
      .dr__control:hover:not(:disabled) {
        border-color: var(--color-text-muted);
      }
      .dr__control:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .dr__sep {
        padding-bottom: var(--space-3);
        color: var(--color-text-muted);
      }
    `,
  ],
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
