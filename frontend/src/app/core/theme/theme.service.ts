import { Injectable, computed, signal } from '@angular/core';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'ap.theme';

/**
 * Theme control:
 * - Preference: `system` (follows OS) | `light` | `dark`, persisted.
 * - The effective theme is set as `data-theme` on <html>.
 * - An OS change is picked up live in `system` mode (matchMedia listener).
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly media = window.matchMedia('(prefers-color-scheme: dark)');
  private readonly _preference = signal<ThemePreference>(this.readStored());
  private readonly _systemDark = signal<boolean>(this.media.matches);

  readonly preference = this._preference.asReadonly();

  /** The actually applied theme (`light` | `dark`). */
  readonly resolved = computed<ResolvedTheme>(() => {
    const pref = this._preference();
    if (pref === 'system') return this._systemDark() ? 'dark' : 'light';
    return pref;
  });

  /** Call once at app start: listener + initial apply. */
  init(): void {
    this.media.addEventListener('change', this.onSystemChange);
    this.apply();
  }

  setPreference(pref: ThemePreference): void {
    this._preference.set(pref);
    this.persist(pref);
    this.apply();
  }

  /** Toggles between light and dark (based on what is currently visible). */
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
