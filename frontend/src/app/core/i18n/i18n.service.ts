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
 * UI-i18n (DE/EN). Locale-Quelle: persistierte Wahl → Browser → DEFAULT_LOCALE.
 * Fehlende Keys der aktiven Locale fallen auf DE zurück (requirements §5).
 * Konfigurierbare DB-Texte (`*_i18n`) sind nicht Teil dieses Service.
 */
@Injectable({ providedIn: 'root' })
export class I18nService {
  private readonly _locale = signal<Locale>(this.resolveInitialLocale());

  /** Aktive Locale (Signal, read-only nach außen). */
  readonly locale = this._locale.asReadonly();
  readonly locales = SUPPORTED_LOCALES;

  /** Aktive Übersetzungstabelle (für Template-Bindings via `t`-Pipe). */
  readonly dictionary = computed(() => CATALOG[this._locale()]);

  setLocale(locale: Locale): void {
    if (!SUPPORTED_LOCALES.includes(locale)) return;
    this._locale.set(locale);
    this.persist(locale);
    document.documentElement.lang = locale;
  }

  /** Übersetzt einen Key; Fallback-Kette: aktive Locale → DE → Key selbst. */
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
      /* storage gesperrt — ignorieren */
    }
  }
}
