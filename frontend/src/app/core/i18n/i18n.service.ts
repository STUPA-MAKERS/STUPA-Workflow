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
 * UI i18n (DE/EN). Locale source: persisted choice → browser → DEFAULT_LOCALE.
 * Missing keys of the active locale fall back to DE. Configurable DB texts
 * (`*_i18n`) are not part of this service.
 */
@Injectable({ providedIn: 'root' })
export class I18nService {
  private readonly _locale = signal<Locale>(this.resolveInitialLocale());

  /** Active locale (signal, read-only to the outside). */
  readonly locale = this._locale.asReadonly();
  readonly locales = SUPPORTED_LOCALES;

  /** Active translation table (for template bindings via the `t` pipe). */
  readonly dictionary = computed(() => CATALOG[this._locale()]);

  constructor() {
    // Sync `<html lang>` with the resolved locale from the first paint (a11y/SEO)
    // — not only on the first manual language switch.
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

  /** Translates a key; fallback chain: active locale → DE → the key itself. */
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
      /* storage blocked — ignore */
    }
  }
}
