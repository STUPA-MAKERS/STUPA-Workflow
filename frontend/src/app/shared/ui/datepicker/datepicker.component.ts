import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  Input,
  computed,
  effect,
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
  templateUrl: './datepicker.component.html',
  styleUrl: './datepicker.component.scss',
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

  constructor() {
    // Anzeige folgt der App-Sprache (#datepicker-locale): ein Sprachwechsel
    // formatiert den sichtbaren Wert sofort um (TT.MM.JJJJ ↔ MM/DD/YYYY) —
    // vorher blieb das alte Format bis zum nächsten writeValue/Commit stehen.
    effect(() => {
      this.i18n.locale();
      this.display.set(this.format(this.value()));
    });
  }

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
