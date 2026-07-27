import { Injectable, Injector, computed, effect, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';

/**
 * App name from the active site config, which needs no authentication.
 *
 * This service is the single source of truth for the configurable app name. It
 * loads the public branding config once at app start. It exposes the name as a
 * signal that the header (aria-label) and the home page (H1) read. It also sets
 * `document.title`.
 *
 * Fallback: when the config name is empty or not yet loaded, the existing i18n
 * texts apply. `app.title` gives the full name and `home.heading` gives the H1.
 * An empty title or heading therefore never appears. The backend serves the PWA
 * manifest (name/short_name) dynamically and separately.
 */
@Injectable({ providedIn: 'root' })
export class BrandingService {
  // Resolve `ApiClient` (→ HttpClient) in `init()`, not in the field initializer.
  // Otherwise the root `BrandingService` pulls HttpClient into every component
  // that injects it, and their specs fail with NG0201 (no HttpClient provider).
  private readonly injector = inject(Injector);
  private readonly i18n = inject(I18nService);
  private readonly title = inject(Title);

  /** Configured full name (empty ⇒ fallback). */
  private readonly _configuredName = signal('');

  /**
   * Full app name: the config value, else i18n `app.title`. The value reacts to
   * a language change through the i18n fallback and to the config load.
   */
  readonly appName = computed(
    () => this._configuredName().trim() || this.i18n.translate('app.title'),
  );

  /**
   * Home heading (H1): the config value, else i18n `home.heading`. By design the
   * configured name replaces the WHOLE heading. It gets no "Workflow" suffix.
   */
  readonly homeHeading = computed(
    () => this._configuredName().trim() || this.i18n.translate('home.heading'),
  );

  constructor() {
    effect(() => this.title.setTitle(this.appName()));
  }

  /** Call once at app start. Loads the active branding config and ignores failures. */
  init(): void {
    this.injector.get(ApiClient).publicSiteConfig().subscribe({
      next: (cfg) => this._configuredName.set(cfg.branding?.appName ?? ''),
      error: () => {
        /* Keep the name empty so the i18n default fallback stays. */
      },
    });
  }
}
