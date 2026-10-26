import { HttpClient } from '@angular/common/http';
import { Injectable, Injector, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import {
  CATALOG,
  DEFAULT_LOCALE,
  type Locale,
  SUPPORTED_LOCALES,
  type TranslationKey,
  loadCatalog,
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
  return FORMAT_LOCALES[baseLocale(locale)];
}

/** An active extra UI language: its BCP 47 code and its native name. */
export interface UiLanguage {
  code: string;
  name: string;
}

/** `GET /i18n`: the resolved UI locale, the active extra languages and the overrides. */
export interface I18nBundle {
  locale: string;
  languages: UiLanguage[];
  /** Locale → key → text, for each locale of the fallback chain of `locale`. */
  overrides: Record<string, Record<string, string>>;
}

/**
 * The built-in locale whose catalog, server labels and formats a UI locale uses: DE for DE,
 * EN for EN and for every extra language.
 */
export function baseLocale(uiLocale: string): Locale {
  return uiLocale === DEFAULT_LOCALE ? DEFAULT_LOCALE : 'en';
}

/**
 * The locales whose texts `uiLocale` shows, the first one first: DE alone, EN then DE, an
 * extra language then EN then DE. The server resolves the same chain.
 */
export function fallbackChain(uiLocale: string): string[] {
  if (uiLocale === DEFAULT_LOCALE) return [DEFAULT_LOCALE];
  if (uiLocale === 'en') return ['en', DEFAULT_LOCALE];
  return [uiLocale, 'en', DEFAULT_LOCALE];
}

/** A stored or requested UI locale: a BCP 47 tag such as `fr` or `pt-BR`. */
const LOCALE_TAG = /^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$/;

/**
 * UI i18n: the built-in DE and EN catalogs, the overrides of the admin page and the extra
 * languages.
 *
 * - `uiLocale` is the language that the reader chose: `de`, `en` or an active extra
 *   language. Source: persisted choice → browser → DEFAULT_LOCALE; `GET /i18n` confirms it,
 *   and an unknown or inactive one becomes DE.
 * - `locale` is its built-in base (`de` / `en`, see {@link baseLocale}). The formats and the
 *   ui-kit strings follow it, because they exist in DE and EN only. The configurable DB
 *   texts (`*_i18n`) and the `lang` of an API call follow `uiLocale`, because an editor can
 *   write a text in an extra language.
 * - A text comes from the first locale of {@link fallbackChain} that has it, an override
 *   before the built-in text of the same locale. A key that no locale has shows as itself.
 */
@Injectable({ providedIn: 'root' })
export class I18nService {
  /**
   * Resolves `HttpClient` in `ready()`, not in a field initializer, because every component
   * injects this service, and their specs would fail with NG0201 (no HttpClient provider).
   */
  private readonly injector = inject(Injector);

  /** The persisted or browser locale, before `GET /i18n` confirms it. */
  private readonly requested = this.resolveInitialLocale();

  private readonly _uiLocale = signal<string>(
    SUPPORTED_LOCALES.includes(this.requested as Locale) ? this.requested : DEFAULT_LOCALE,
  );

  /** The UI language of the reader: `de`, `en` or an extra language. Not for `Intl`. */
  readonly uiLocale = this._uiLocale.asReadonly();

  /**
   * The built-in base of the UI locale (`de` / `en`), read-only to the outside. This is the
   * locale of the formats. Do NOT give it to `Intl` — use {@link formatLocale}. A DB text
   * resolves with {@link uiLocale}.
   */
  readonly locale = computed<Locale>(() => baseLocale(this._uiLocale()));

  /** `Intl` tag of the active locale (`de-DE` / `en-GB`). See {@link toFormatLocale}. */
  readonly formatLocale = computed(() => FORMAT_LOCALES[this.locale()]);

  private readonly _languages = signal<UiLanguage[]>([]);

  /** The active extra languages, in the order of the server. */
  readonly extraLanguages = this._languages.asReadonly();

  /**
   * Every selectable UI locale: DE, EN, then the active extra languages. The content editors
   * offer the same languages.
   */
  readonly locales = computed<string[]>(() => [
    ...SUPPORTED_LOCALES,
    ...this._languages().map((l) => l.code),
  ]);

  /** Locale → key → override text. */
  private readonly _overrides = signal<Record<string, Record<string, string>>>({});

  /**
   * `<html lang>` follows the resolved locale from the first paint (a11y and SEO), not only after
   * the first manual language switch.
   */
  constructor() {
    if (typeof document !== 'undefined') {
      document.documentElement.lang = this._uiLocale();
    }
  }

  /**
   * Load the overrides, the extra languages and the catalog of the active locale. The app
   * initializer waits for it, so the first paint is in the right language. A failed load
   * resolves too: the app then shows the built-in texts, and DE for an extra language.
   */
  async ready(): Promise<void> {
    await Promise.all([this.loadBundle(), this.load(this.locale())]);
    await this.load(this.locale());
  }

  setLocale(locale: string): void {
    if (!this.locales().includes(locale)) return;
    this._uiLocale.set(locale);
    this.persist(locale);
    document.documentElement.lang = locale;
    void this.load(this.locale());
  }

  /**
   * Put the overrides of `locale` that the admin page just saved in place, so the page and the
   * app show them without a reload. A locale outside the active chain changes nothing visible.
   */
  applyOverrides(locale: string, overrides: Record<string, string>): void {
    this._overrides.update((all) => ({ ...all, [locale]: overrides }));
  }

  /** The built-in text of `key` in `locale` (DE or EN), without overrides; `null` if none. */
  builtIn(key: TranslationKey, locale: Locale): string | null {
    return CATALOG[locale][key] ?? null;
  }

  private async loadBundle(): Promise<void> {
    const http = this.injector.get(HttpClient, null);
    if (!http) return;
    const base = this.injector.get(API_BASE_URL);
    try {
      const bundle = await firstValueFrom(
        http.get<I18nBundle>(`${base}/i18n`, { params: { locale: this.requested } }),
      );
      this._languages.set(bundle.languages);
      this._overrides.set(bundle.overrides);
      if (bundle.locale !== this._uiLocale()) {
        this._uiLocale.set(bundle.locale);
        document.documentElement.lang = bundle.locale;
      }
    } catch {
      /* The built-in texts apply. */
    }
  }

  private load(locale: Locale): Promise<void> {
    return loadCatalog(locale).then(
      () => undefined,
      () => undefined,
    );
  }

  /**
   * The native name of a language: "Deutsch", "English", or the name of an extra language.
   * An unknown code shows as its code in capitals.
   */
  languageName(code: string): string {
    if (code === DEFAULT_LOCALE) return this.translate('shell.lang.de');
    if (code === 'en') return this.translate('shell.lang.en');
    return this._languages().find((l) => l.code === code)?.name ?? code.toUpperCase();
  }

  /** Translate a key. Fallback chain: see {@link fallbackChain}, then the key itself. */
  translate(key: TranslationKey, params?: Record<string, string | number>): string {
    const overrides = this._overrides();
    const catalogs = CATALOG as Record<string, Partial<Record<TranslationKey, string>> | undefined>;
    let raw: string = key;
    for (const loc of fallbackChain(this._uiLocale())) {
      const text = overrides[loc]?.[key] ?? catalogs[loc]?.[key];
      if (text !== undefined) {
        raw = text;
        break;
      }
    }
    return params ? this.interpolate(raw, params) : raw;
  }

  private interpolate(text: string, params: Record<string, string | number>): string {
    return text.replace(/\{(\w+)\}/g, (match, name: string) =>
      name in params ? String(params[name]) : match,
    );
  }

  private resolveInitialLocale(): string {
    const stored = this.readStored();
    if (stored) return stored;
    const nav =
      typeof navigator !== 'undefined' ? navigator.language.slice(0, 2).toLowerCase() : '';
    return LOCALE_TAG.test(nav) ? nav : DEFAULT_LOCALE;
  }

  private readStored(): string | null {
    try {
      const v = localStorage.getItem(STORAGE_KEY);
      return v && LOCALE_TAG.test(v) ? v : null;
    } catch {
      return null;
    }
  }

  private persist(locale: string): void {
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* Storage is blocked. Ignore the error. */
    }
  }
}
