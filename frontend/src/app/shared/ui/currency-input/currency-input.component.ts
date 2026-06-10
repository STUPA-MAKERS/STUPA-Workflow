import {
  ChangeDetectionStrategy,
  Component,
  inject,
  input,
  signal,
} from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';

/**
 * Einheitliches Währungs-Eingabefeld (#currency). Überall gleiche Optik:
 * rechtsbündig, Tausender-Gruppierung + 2 Nachkommastellen, „€"-Suffix.
 *
 * `ControlValueAccessor` → per `[(ngModel)]` nutzbar. Das **Modell** ist stets ein
 * kanonischer Dezimal-String mit Punkt (`"1234.56"`, parsebar fürs Backend) bzw.
 * `''` für leer. Die **Anzeige** ist lokalisiert (de `1.234,56`, en `1,234.56`):
 * beim Fokus editierbar (ohne Gruppierung), beim Verlassen formatiert.
 */
@Component({
  selector: 'app-currency-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [
    { provide: NG_VALUE_ACCESSOR, useExisting: CurrencyInputComponent, multi: true },
  ],
  template: `
    <div class="flex flex-col gap-1">
      @if (label()) {
        <label class="text-sm font-medium text-muted">
          {{ label() }}
          @if (required()) {
            <span class="text-danger ms-[2px]" aria-hidden="true">*</span>
          }
        </label>
      }
      <span class="cur" [class.cur--disabled]="disabled()">
        <input
          class="cur__input"
          type="text"
          inputmode="decimal"
          [value]="text()"
          [disabled]="disabled()"
          [attr.placeholder]="placeholder()"
          [attr.aria-label]="ariaLabel() || label() || null"
          [attr.aria-invalid]="error() ? 'true' : null"
          [attr.name]="name() || null"
          (focus)="onFocus()"
          (input)="onInput($any($event.target).value)"
          (blur)="onBlur()"
        />
        <span class="cur__symbol" aria-hidden="true">€</span>
      </span>
      @if (hint() && !error()) {
        <p class="text-xs text-muted m-0">{{ hint() }}</p>
      }
      @if (error()) {
        <p class="text-xs text-danger m-0" role="alert">{{ error() }}</p>
      }
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        width: 100%;
      }
      .cur {
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        width: 100%;
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-bg, var(--color-surface));
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
      }
      .cur:focus-within {
        outline: 2px solid var(--color-primary);
        outline-offset: 1px;
      }
      .cur--disabled {
        opacity: 0.6;
      }
      .cur__input {
        flex: 1 1 auto;
        min-width: 0;
        height: 100%;
        border: 0;
        background: transparent;
        color: var(--color-text);
        font: inherit;
        font-variant-numeric: tabular-nums;
        text-align: end;
        padding: 0;
      }
      .cur__input:focus {
        outline: none;
      }
      .cur__symbol {
        flex: 0 0 auto;
        color: var(--color-text-muted);
      }
    `,
  ],
})
export class CurrencyInputComponent implements ControlValueAccessor {
  private readonly i18n = inject(I18nService);

  readonly placeholder = input('');
  readonly ariaLabel = input('');
  readonly name = input('');
  /** Optionales Feld-Label; gesetzt → volle Feld-Optik (Label/Hint/Error),
   *  leer → blankes Control (für eigene Label-Wrapper, z. B. Filter/Dialoge). */
  readonly label = input('');
  readonly hint = input('');
  readonly error = input('');
  readonly required = input(false);

  /** Sichtbarer Text (formatiert oder beim Tippen roh). */
  protected readonly text = signal('');
  protected readonly disabled = signal(false);

  /** Kanonischer Wert (Punkt-Dezimal, ohne Gruppierung) — das Modell. */
  private canonical = '';
  private focused = false;

  private onChange: (value: string) => void = () => {};
  private onTouched: () => void = () => {};

  // --- ControlValueAccessor ---------------------------------------------------
  writeValue(value: string | number | null): void {
    this.canonical = this.toCanonical(value == null ? '' : String(value));
    this.text.set(this.focused ? this.toEditable(this.canonical) : this.format(this.canonical));
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

  // --- Interaktion ------------------------------------------------------------
  protected onFocus(): void {
    this.focused = true;
    this.text.set(this.toEditable(this.canonical));
  }

  protected onInput(raw: string): void {
    this.text.set(raw); // roh stehen lassen (kein Cursor-Springen)
    this.canonical = this.parse(raw);
    this.onChange(this.canonical);
  }

  protected onBlur(): void {
    this.focused = false;
    this.text.set(this.format(this.canonical));
    this.onTouched();
  }

  // --- Parsen / Formatieren ---------------------------------------------------
  private get decimalSep(): string {
    return this.i18n.locale() === 'en' ? '.' : ',';
  }

  /** Roh-Eingabe → kanonischer Punkt-Dezimal-String (oder ''). */
  private parse(raw: string): string {
    const trimmed = (raw ?? '').trim();
    if (!trimmed) return '';
    // Alles außer Ziffern und Separatoren entfernen; letzter Separator = Dezimaltrenner.
    let s = trimmed.replace(/[^\d.,-]/g, '');
    const neg = s.startsWith('-');
    s = s.replace(/-/g, '');
    const lastSep = Math.max(s.lastIndexOf(','), s.lastIndexOf('.'));
    let intPart: string;
    let fracPart: string;
    if (lastSep === -1) {
      intPart = s;
      fracPart = '';
    } else {
      intPart = s.slice(0, lastSep).replace(/[.,]/g, '');
      fracPart = s.slice(lastSep + 1).replace(/[.,]/g, '');
    }
    intPart = intPart.replace(/^0+(?=\d)/, '');
    if (!intPart && !fracPart) return '';
    const canonical = fracPart ? `${intPart || '0'}.${fracPart}` : intPart || '0';
    return neg ? `-${canonical}` : canonical;
  }

  /** Beliebigen Wert (Backend-Punkt oder lokal) → kanonisch. */
  private toCanonical(value: string): string {
    return this.parse(value);
  }

  /** Kanonisch → editierbarer Text (lokaler Dezimaltrenner, keine Gruppierung). */
  private toEditable(canonical: string): string {
    if (!canonical) return '';
    return this.decimalSep === ',' ? canonical.replace('.', ',') : canonical;
  }

  /** Kanonisch → lokalisiert formatiert (1.234,56) mit 2 Nachkommastellen. */
  private format(canonical: string): string {
    if (!canonical) return '';
    const n = Number(canonical);
    if (Number.isNaN(n)) return '';
    const locale = this.i18n.locale() === 'en' ? 'en-US' : 'de-DE';
    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);
  }
}
