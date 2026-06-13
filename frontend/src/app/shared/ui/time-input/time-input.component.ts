import {
  ChangeDetectionStrategy,
  Component,
  Input,
  signal,
} from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';

let nextId = 0;

/**
 * Uhrzeit-Feld des UI-Kits (#time-input). Erzwingt **24h-Format** (`HH:MM`) —
 * das native `<input type="time">` rendert je nach Browser-/OS-Locale AM/PM,
 * unabhängig von der App-Sprache. Der Wert ist immer `HH:MM` (oder `''`).
 *
 * Eingabe tolerant: `9:30`, `09.30`, `0930` → `09:30`; Commit bei Blur,
 * Ungültiges fällt auf den letzten gültigen Wert zurück (wie `app-datepicker`).
 * `ControlValueAccessor` → Reactive Forms/`ngModel`.
 */
@Component({
  selector: 'app-time-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: TimeInputComponent, multi: true }],
  templateUrl: './time-input.component.html',
  styleUrl: './time-input.component.scss',
})
export class TimeInputComponent implements ControlValueAccessor {
  @Input() label = '';
  @Input() ariaLabel = '';
  @Input() required = false;
  @Input() id = `app-time-input-${nextId++}`;

  /** Kanonischer Wert (`HH:MM` | `''`), CVA-Quelle. */
  readonly value = signal('');
  /** Sichtbarer Text — beim Tippen unverändert, Commit bei Blur. */
  readonly display = signal('');
  readonly disabled = signal(false);

  private onChange: (value: string) => void = () => {};
  onTouched: () => void = () => {};

  onText(text: string): void {
    this.display.set(text);
  }

  onBlur(): void {
    this.onTouched();
    const parsed = parseTime(this.display());
    if (parsed !== null) {
      this.commit(parsed);
    } else {
      // Ungültig → letzten gültigen Wert wieder anzeigen.
      this.display.set(this.value());
    }
  }

  private commit(value: string): void {
    this.value.set(value);
    this.display.set(value);
    this.onChange(value);
  }

  writeValue(value: string | null): void {
    const v = normalizeWire(value);
    this.value.set(v);
    this.display.set(v);
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

/** Wire-Wert normalisieren: `HH:MM:SS` (Backend-`time`) → `HH:MM`. */
function normalizeWire(value: string | null): string {
  const m = /^(\d{2}):(\d{2})/.exec(value ?? '');
  return m ? `${m[1]}:${m[2]}` : '';
}

/** Freie Eingabe → `HH:MM` (24h) | `''` (leer) | `null` (ungültig). */
function parseTime(text: string): string | null {
  const t = text.trim();
  if (!t) return '';
  const m = /^(\d{1,2})[:.,]?([0-5]\d)$/.exec(t) ?? /^(\d{1,2})$/.exec(t);
  if (!m) return null;
  const hh = Number(m[1]);
  const mm = m[2] !== undefined ? Number(m[2]) : 0;
  if (hh > 23) return null;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}
