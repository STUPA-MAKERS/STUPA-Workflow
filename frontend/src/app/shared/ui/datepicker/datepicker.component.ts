import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  Input,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';

let nextId = 0;

/**
 * Datumsfeld des UI-Kits (#79). **Lokalisiertes** Anzeigeformat (DE: `TT.MM.JJJJ`,
 * EN: `MM/DD/YYYY`) — unabhängig von der Browser-Sprache, die das native
 * `<input type="date">` sonst erzwingt. Der Wert ist immer ISO (`YYYY-MM-DD`).
 *
 * Bedienung: tippen im Textfeld (locale-Reihenfolge) **oder** den nativen Kalender
 * über den Kalender-Button öffnen (`showPicker()`; das native Feld bleibt unsichtbar,
 * nur sein Kalender-Popup erscheint). `ControlValueAccessor` → Reactive Forms/`ngModel`.
 */
@Component({
  selector: 'app-datepicker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
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
      <div class="dp__field">
        <input
          class="dp__text"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          [id]="id"
          [value]="display()"
          [placeholder]="placeholder()"
          [disabled]="disabled()"
          [attr.aria-label]="!label && ariaLabel ? ariaLabel : null"
          [attr.aria-invalid]="error ? 'true' : null"
          [attr.aria-describedby]="describedBy"
          [attr.required]="required ? '' : null"
          (input)="onText($any($event.target).value)"
          (blur)="onBlur()"
        />
        <button
          type="button"
          class="dp__cal"
          [disabled]="disabled()"
          [attr.aria-label]="'datepicker.openCalendar' | t"
          (click)="openPicker()"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" />
          </svg>
        </button>
        <input
          #native
          class="dp__native"
          type="date"
          tabindex="-1"
          aria-hidden="true"
          [value]="value()"
          [attr.min]="min || null"
          [attr.max]="max || null"
          (change)="onNative($any($event.target).value)"
        />
      </div>
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
      .dp { display: flex; flex-direction: column; gap: var(--space-2); }
      .dp__label { font-size: var(--fs-sm); font-weight: var(--fw-medium); color: var(--color-text); }
      .dp__req { color: var(--color-danger); }
      .dp__field { position: relative; display: flex; }
      .dp__text {
        flex: 1;
        height: var(--control-height);
        box-sizing: border-box;
        padding: 0 2.5rem 0 var(--space-4);
        font: inherit;
        font-size: var(--fs-md);
        color: var(--color-text);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        transition: border-color var(--motion-fast) var(--ease-standard);
      }
      .dp__text:hover:not(:disabled) { border-color: var(--color-text-muted); }
      .dp__text:disabled { opacity: 0.6; cursor: not-allowed; }
      .dp__text[aria-invalid='true'] { border-color: var(--color-danger); }
      .dp__cal {
        position: absolute;
        right: 0;
        top: 0;
        height: var(--control-height);
        width: 2.5rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: transparent;
        border: 0;
        color: var(--color-text-muted);
        cursor: pointer;
        border-radius: var(--radius-md);
      }
      .dp__cal:hover:not(:disabled) { color: var(--color-text); }
      .dp__cal:disabled { opacity: 0.6; cursor: not-allowed; }
      /* Natives Feld unsichtbar (nur sein Kalender-Popup erscheint via showPicker). */
      .dp__native {
        position: absolute;
        right: 0.5rem;
        bottom: 0;
        width: 1px;
        height: 1px;
        opacity: 0;
        pointer-events: none;
        border: 0;
        padding: 0;
      }
      .dp__hint { font-size: var(--fs-xs); color: var(--color-text-muted); }
      .dp__error { font-size: var(--fs-xs); color: var(--color-danger); }
    `,
  ],
})
export class DatepickerComponent implements ControlValueAccessor {
  private readonly i18n = inject(I18nService);

  @Input() label = '';
  @Input() ariaLabel = '';
  @Input() hint = '';
  @Input() error = '';
  @Input() required = false;
  @Input() min = '';
  @Input() max = '';
  @Input() id = `app-datepicker-${nextId++}`;

  private readonly native = viewChild<ElementRef<HTMLInputElement>>('native');

  /** ISO-Wert (`YYYY-MM-DD`), CVA-Quelle. */
  readonly value = signal('');
  /** Sichtbarer (locale-formatierter) Text — beim Tippen unverändert übernommen. */
  readonly display = signal('');
  readonly disabled = signal(false);

  readonly placeholder = computed(() =>
    this.i18n.locale() === 'de' ? 'TT.MM.JJJJ' : 'MM/DD/YYYY',
  );

  private onChange: (value: string) => void = () => {};
  onTouched: () => void = () => {};

  get describedBy(): string | null {
    if (this.error) return `${this.id}-error`;
    if (this.hint) return `${this.id}-hint`;
    return null;
  }

  // Anzeige folgt der Eingabe; Commit (parse → ISO) erst bei Blur.
  onText(text: string): void {
    this.display.set(text);
  }

  onBlur(): void {
    this.onTouched();
    const iso = this.parse(this.display());
    if (iso) {
      this.commit(iso);
    } else if (!this.display().trim()) {
      this.commit('');
    } else {
      // Ungültig → letzten gültigen Wert wieder anzeigen.
      this.display.set(this.format(this.value()));
    }
  }

  onNative(iso: string): void {
    this.commit(iso);
  }

  openPicker(): void {
    const el = this.native()?.nativeElement;
    if (!el) return;
    const withPicker = el as HTMLInputElement & { showPicker?: () => void };
    if (typeof withPicker.showPicker === 'function') {
      withPicker.showPicker();
    } else {
      el.focus();
      el.click();
    }
  }

  private commit(iso: string): void {
    this.value.set(iso);
    this.display.set(this.format(iso));
    this.onChange(iso);
  }

  /** ISO → locale-Anzeige. */
  private format(iso: string): string {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? '');
    if (!m) return '';
    const [, y, mo, d] = m;
    return this.i18n.locale() === 'de' ? `${d}.${mo}.${y}` : `${mo}/${d}/${y}`;
  }

  /** Locale-Text → ISO (oder `''`). Akzeptiert `. / -` als Trenner; 2-stellige Jahre → 20xx. */
  private parse(text: string): string {
    const parts = text.trim().split(/[./\-\s]+/).filter(Boolean);
    if (parts.length !== 3) return '';
    const [a, b, y] = parts;
    const day = this.i18n.locale() === 'de' ? a : b;
    const month = this.i18n.locale() === 'de' ? b : a;
    let yyyy = Number(y);
    const dd = Number(day);
    const mm = Number(month);
    if (!dd || !mm || !yyyy) return '';
    if (yyyy < 100) yyyy += 2000;
    if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return '';
    const iso = `${String(yyyy).padStart(4, '0')}-${String(mm).padStart(2, '0')}-${String(dd).padStart(2, '0')}`;
    const dt = new Date(iso + 'T00:00:00');
    return Number.isNaN(dt.getTime()) ? '' : iso;
  }

  writeValue(value: string | null): void {
    const iso = value ?? '';
    this.value.set(iso);
    this.display.set(this.format(iso));
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
