import { Injectable, computed, signal } from '@angular/core';
import { withViewTransition } from '@core/motion/motion';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'ap.theme';

/**
 * Page background per theme (`--color-bg` of the ui-kit tokens). The browser and the
 * installed PWA colour their bars with the `theme-color` meta tag, so the bars follow the
 * theme. Keep the values in step with `tokens.scss` and `index.html`.
 */
export const THEME_COLOR: Record<ResolvedTheme, string> = {
  light: '#f6f7f5',
  dark: '#101211',
};

/**
 * The manifest per theme. An installed Android app paints its navigation bar with
 * `theme_color` or `background_color` of the manifest (both the bottom bar surface, so
 * the two bars meet without a seam); the status bar follows the meta tag. A
 * manifest has no per-scheme variant, so the service links the dark manifest while the
 * dark theme is in effect. The light one keeps the plain URL of `index.html`.
 */
export const MANIFEST_HREF: Record<ResolvedTheme, string> = {
  light: 'manifest.webmanifest',
  dark: 'manifest.webmanifest?scheme=dark',
};

/**
 * Theme control:
 * - The preference is `system` (follows the OS), `light` or `dark`. It is persisted.
 * - The service writes the effective theme to `data-theme` on <html> and its page
 *   background to every `<meta name="theme-color">`, and links the manifest of that
 *   theme (`MANIFEST_HREF`).
 * - In `system` mode a matchMedia listener picks up an OS change live.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly media = window.matchMedia('(prefers-color-scheme: dark)');
  private readonly _preference = signal<ThemePreference>(this.readStored());
  private readonly _systemDark = signal<boolean>(this.media.matches);
  /** The theme of a page that sets its own default (the beamer), or `null`. */
  private readonly _pageDefault = signal<ResolvedTheme | null>(null);

  readonly preference = this._preference.asReadonly();

  /** The theme that is in effect (`light` or `dark`). */
  readonly resolved = computed<ResolvedTheme>(() => {
    const pref = this._preference();
    if (pref === 'system') return this._pageDefault() ?? (this._systemDark() ? 'dark' : 'light');
    return pref;
  });

  /** Call this once at app start. It adds the OS listener and applies the theme. */
  init(): void {
    this.media.addEventListener('change', this.onSystemChange);
    this.apply();
  }

  /** The whole page cross-fades once instead of each surface changing on its own. */
  setPreference(pref: ThemePreference): void {
    this._preference.set(pref);
    this.persist(pref);
    withViewTransition(() => this.apply());
  }

  /**
   * Set the theme that `system` gives while one page shows, for example dark for the
   * beamer. An explicit choice of the person (`light` or `dark`) still wins. The page
   * calls it again with `null` when it goes, and the OS theme applies again. The
   * service does not persist this value.
   */
  setPageDefault(theme: ResolvedTheme | null): void {
    this._pageDefault.set(theme);
    this.apply();
  }

  /** Switch between light and dark, based on the theme that is visible now. */
  toggle(): void {
    this.setPreference(this.resolved() === 'dark' ? 'light' : 'dark');
  }

  private readonly onSystemChange = (e: MediaQueryListEvent): void => {
    this._systemDark.set(e.matches);
    if (this._preference() === 'system') this.apply();
  };

  /**
   * index.html carries one theme-color tag per OS scheme. An explicit choice in the app overrides
   * the OS, so both tags take the colour of the theme in effect.
   */
  private apply(): void {
    const theme = this.resolved();
    document.documentElement.setAttribute('data-theme', theme);
    document
      .querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')
      .forEach((meta) => meta.setAttribute('content', THEME_COLOR[theme]));
    document
      .querySelector<HTMLLinkElement>('link[rel="manifest"]')
      ?.setAttribute('href', MANIFEST_HREF[theme]);
  }

  private readStored(): ThemePreference {
    try {
      const v = localStorage.getItem(STORAGE_KEY);
      if (v === 'light' || v === 'dark' || v === 'system') return v;
    } catch {
      /* ignore */
    }
    return 'system';
  }

  private persist(pref: ThemePreference): void {
    try {
      localStorage.setItem(STORAGE_KEY, pref);
    } catch {
      /* ignore */
    }
  }
}
