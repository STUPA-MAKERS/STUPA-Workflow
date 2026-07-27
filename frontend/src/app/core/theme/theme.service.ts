import { Injectable, computed, signal } from '@angular/core';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'ap.theme';

/**
 * Theme control:
 * - The preference is `system` (follows the OS), `light` or `dark`. It is persisted.
 * - The service writes the effective theme to `data-theme` on <html>.
 * - In `system` mode a matchMedia listener picks up an OS change live.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly media = window.matchMedia('(prefers-color-scheme: dark)');
  private readonly _preference = signal<ThemePreference>(this.readStored());
  private readonly _systemDark = signal<boolean>(this.media.matches);

  readonly preference = this._preference.asReadonly();

  /** The theme that is in effect (`light` or `dark`). */
  readonly resolved = computed<ResolvedTheme>(() => {
    const pref = this._preference();
    if (pref === 'system') return this._systemDark() ? 'dark' : 'light';
    return pref;
  });

  /** Call this once at app start. It adds the OS listener and applies the theme. */
  init(): void {
    this.media.addEventListener('change', this.onSystemChange);
    this.apply();
  }

  setPreference(pref: ThemePreference): void {
    this._preference.set(pref);
    this.persist(pref);
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

  private apply(): void {
    document.documentElement.setAttribute('data-theme', this.resolved());
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
