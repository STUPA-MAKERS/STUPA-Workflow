import { Injectable, computed, signal } from '@angular/core';
import {
  CATALOG,
  DEFAULT_LOCALE,
  type Locale,
  SUPPORTED_LOCALES,
  type TranslationKey,
} from './translations';

const STORAGE_KEY = 'ap.locale';

/**
 * The `Intl` locale tag behind each UI locale.
 *
 * The UI locale (`de` / `en`) is a translation-catalogue key. It is NOT a format
 * locale: bare `en` makes `Intl` use US order (`07/01/2026`, `7:50 PM`), which an
 * international student in Europe reads as 7 January. EN therefore formats as
 * `en-GB` — `01/07/2026` and a 24 h clock, like DE. Amounts do not move: EUR under
 * `en-GB` still prints `€1,500.00`.
 */
const FORMAT_LOCALES: Record<Locale, string> = { de: 'de-DE', en: 'en-GB' };

/**
 * Map a UI locale to its `Intl` tag. THE single mapping point — every
 * `Intl.DateTimeFormat` / `Intl.NumberFormat` / `toLocale*` call goes through this
 * function or through {@link I18nService.formatLocale}. Never pass a bare UI locale
 * to `Intl`.
 *
 * Code inside an injection context should read `I18nService.formatLocale()`. This
 * function serves the pure display helpers, which take the UI locale as an argument.
 */
export function toFormatLocale(locale: string): string {
  return locale === 'en' ? FORMAT_LOCALES.en : FORMAT_LOCALES.de;
}

/**
 * UI i18n (DE and EN). Locale source: persisted choice → browser →
 * DEFAULT_LOCALE. A key that the active locale misses falls back to DE. This
 * service does not cover the configurable DB texts (`*_i18n`).
 */
@Injectable({ providedIn: 'root' })
export class I18nService {
  private readonly _locale = signal<Locale>(this.resolveInitialLocale());

  /**
   * Active locale, read-only to the outside. This is the translation-key locale
   * (`de` / `en`). Do NOT give it to `Intl` — use {@link formatLocale}.
   */
  readonly locale = this._locale.asReadonly();
  readonly locales = SUPPORTED_LOCALES;

  /** `Intl` tag of the active locale (`de-DE` / `en-GB`). See {@link toFormatLocale}. */
  readonly formatLocale = computed(() => FORMAT_LOCALES[this._locale()]);

  /** Active translation table (for template bindings via the `t` pipe). */
  readonly dictionary = computed(() => CATALOG[this._locale()]);

  constructor() {
    // Sync `<html lang>` with the resolved locale from the first paint (a11y and
    // SEO), not only at the first manual language switch.
    if (typeof document !== 'undefined') {
      document.documentElement.lang = this._locale();
    }
  }

  setLocale(locale: Locale): void {
    if (!SUPPORTED_LOCALES.includes(locale)) return;
    this._locale.set(locale);
    this.persist(locale);
    document.documentElement.lang = locale;
  }

  /** Translate a key. Fallback chain: active locale → DE → the key itself. */
  translate(key: TranslationKey, params?: Record<string, string | number>): string {
    const active = CATALOG[this._locale()];
    const raw = active[key] ?? CATALOG[DEFAULT_LOCALE][key] ?? key;
    return params ? this.interpolate(raw, params) : raw;
  }

  private interpolate(text: string, params: Record<string, string | number>): string {
    return text.replace(/\{(\w+)\}/g, (match, name: string) =>
      name in params ? String(params[name]) : match,
    );
  }

  private resolveInitialLocale(): Locale {
    const stored = this.readStored();
    if (stored) return stored;
    const nav =
      typeof navigator !== 'undefined' ? navigator.language.slice(0, 2).toLowerCase() : '';
    return SUPPORTED_LOCALES.includes(nav as Locale) ? (nav as Locale) : DEFAULT_LOCALE;
  }

  private readStored(): Locale | null {
    try {
      const v = localStorage.getItem(STORAGE_KEY);
      return v && SUPPORTED_LOCALES.includes(v as Locale) ? (v as Locale) : null;
    } catch {
      return null;
    }
  }

  private persist(locale: Locale): void {
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* Storage is blocked. Ignore the error. */
    }
  }
}
