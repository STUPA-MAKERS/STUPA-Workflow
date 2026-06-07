import { ChangeDetectionStrategy, Component, Input, signal } from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';

let nextId = 0;

/**
 * Datumsfeld des UI-Kits (#79). Kapselt das native `<input type="date">` (echter
 * a11y-fähiger Datepicker mit Tastatur-/Screenreader-Support, Dark/Light über
 * `color-scheme`). `ControlValueAccessor` → Reactive Forms + `ngModel`. Wert ist
 * ein ISO-Datum (`YYYY-MM-DD`). Für Zeiträume siehe {@link DateRangeComponent}.
 */
@Component({
  selector: 'app-datepicker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: DatepickerComponent, multi: true }],
  template: `
    <div class="dp">
      @if (label) {
        <label class="dp__label" [for]="id">
          {{ label }}
          @if (required) {
            <span class="dp__req" aria-hidden="true">*</span>
          }
        </label>
      }
      <input
        class="dp__control"
        type="date"
        [id]="id"
        [value]="value()"
        [disabled]="disabled()"
        [attr.aria-label]="!label && ariaLabel ? ariaLabel : null"
        [attr.aria-invalid]="error ? 'true' : null"
        [attr.aria-describedby]="describedBy"
        [attr.min]="min || null"
        [attr.max]="max || null"
        [attr.required]="required ? '' : null"
        (input)="onInput($event)"
        (blur)="onTouched()"
      />
      @if (hint && !error) {
        <p class="dp__hint" [id]="id + '-hint'">{{ hint }}</p>
      }
      @if (error) {
        <p class="dp__error" [id]="id + '-error'" role="alert">{{ error }}</p>
      }
    </div>
  `,
  styles: [
    `
      .dp {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .dp__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .dp__req {
        color: var(--color-danger);
      }
      .dp__control {
        /* Native Kalender-/Spinner-UI folgt dem Theme (hell/dunkel). */
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
      .dp__control:hover:not(:disabled) {
        border-color: var(--color-text-muted);
      }
      .dp__control:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .dp__control[aria-invalid='true'] {
        border-color: var(--color-danger);
      }
      .dp__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .dp__error {
        font-size: var(--fs-xs);
        color: var(--color-danger);
      }
    `,
  ],
})
export class DatepickerComponent implements ControlValueAccessor {
  @Input() label = '';
  @Input() ariaLabel = '';
  @Input() hint = '';
  @Input() error = '';
  @Input() required = false;
  /** ISO-Untergrenze (`YYYY-MM-DD`), z. B. Start eines Zeitraums. */
  @Input() min = '';
  /** ISO-Obergrenze (`YYYY-MM-DD`). */
  @Input() max = '';
  @Input() id = `app-datepicker-${nextId++}`;

  readonly value = signal('');
  readonly disabled = signal(false);

  private onChange: (value: string) => void = () => {};
  onTouched: () => void = () => {};

  get describedBy(): string | null {
    if (this.error) return `${this.id}-error`;
    if (this.hint) return `${this.id}-hint`;
    return null;
  }

  onInput(event: Event): void {
    const v = (event.target as HTMLInputElement).value;
    this.value.set(v);
    this.onChange(v);
  }

  writeValue(value: string | null): void {
    this.value.set(value ?? '');
  }
  registerOnChange(fn: (value: string) => void): void {
    this.onChange = fn;
  }
  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }
  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }
}
