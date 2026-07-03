import { Injectable, Injector, computed, effect, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';

/**
 * App name from the active (auth-free) site config.
 *
 * Single source of truth for the configurable app name: loads the public
 * branding config once at app start and exposes the name as a signal that the
 * header (aria-label) and home page (H1) read. Also sets `document.title`.
 *
 * Fallback: if the name in the config is empty (or not yet loaded), the existing
 * i18n applies — `app.title` for the full name, `home.heading` for the H1 — so
 * an empty title/heading never appears. The PWA manifest (name/short_name) is
 * served dynamically by the backend separately.
 */
@Injectable({ providedIn: 'root' })
export class BrandingService {
  // Resolve `ApiClient` (→ HttpClient) in `init()`, not in the field initializer:
  // otherwise the root `BrandingService` pulls HttpClient into every component
  // that injects it, and their specs fail with NG0201 (no HttpClient provider).
  private readonly injector = inject(Injector);
  private readonly i18n = inject(I18nService);
  private readonly title = inject(Title);

  /** Configured full name (empty ⇒ fallback). */
  private readonly _configuredName = signal('');

  /**
   * Full app name: config value, else i18n `app.title`. Reacts to language
   * changes (via the i18n fallback) and to the config being loaded.
   */
  readonly appName = computed(
    () => this._configuredName().trim() || this.i18n.translate('app.title'),
  );

  /**
   * Home heading (H1): config value, else i18n `home.heading`. By design the
   * configured name replaces the ENTIRE heading (without a "Workflow" suffix).
   */
  readonly homeHeading = computed(
    () => this._configuredName().trim() || this.i18n.translate('home.heading'),
  );

  constructor() {
    // Bind the browser tab title to the (config- or i18n-based) app name.
    effect(() => this.title.setTitle(this.appName()));
  }

  /** Call once at app start: load the active branding config (best-effort). */
  init(): void {
    this.injector.get(ApiClient).publicSiteConfig().subscribe({
      next: (cfg) => this._configuredName.set(cfg.branding?.appName ?? ''),
      error: () => {
        /* leave empty → i18n/default fallback stays */
      },
    });
  }
}
