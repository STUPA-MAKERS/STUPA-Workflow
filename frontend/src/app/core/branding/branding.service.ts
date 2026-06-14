import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';

/**
 * App-Name aus der aktiven (auth-freien) Site-Config (#brand-name).
 *
 * Single Source of Truth für den konfigurierbaren App-Namen: lädt die öffentliche
 * Branding-Config einmal beim App-Start und stellt den Namen als Signal bereit, das
 * Header (aria-label) und Startseite (H1) lesen. Setzt zusätzlich `document.title`.
 *
 * **Fallback:** ist der Name in der Config leer (oder noch nicht geladen), greift die
 * bestehende i18n — `app.title` für den vollen Namen, `home.heading` für die H1 —, so
 * dass nie ein leerer Titel/Heading erscheint. Das PWA-Manifest (name/short_name) wird
 * separat dynamisch vom Backend ausgeliefert.
 */
@Injectable({ providedIn: 'root' })
export class BrandingService {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly title = inject(Title);

  /** Konfigurierter voller Name (leer ⇒ Fallback). */
  private readonly _configuredName = signal('');

  /**
   * Voller App-Name: Config-Wert, sonst i18n `app.title`. Reagiert auf Sprachwechsel
   * (über den i18n-Fallback) und auf das Laden der Config.
   */
  readonly appName = computed(
    () => this._configuredName().trim() || this.i18n.translate('app.title'),
  );

  /**
   * Startseiten-Überschrift (H1): Config-Wert, sonst i18n `home.heading`. Per Vorgabe
   * ersetzt der konfigurierte Name die GESAMTE Überschrift (ohne „Workflow"-Zusatz).
   */
  readonly homeHeading = computed(
    () => this._configuredName().trim() || this.i18n.translate('home.heading'),
  );

  constructor() {
    // Browser-Tab-Titel an den (config- oder i18n-basierten) App-Namen koppeln.
    effect(() => this.title.setTitle(this.appName()));
  }

  /** Einmal beim App-Start aufrufen: aktive Branding-Config laden (best-effort). */
  init(): void {
    this.api.publicSiteConfig().subscribe({
      next: (cfg) => this._configuredName.set(cfg.branding?.appName ?? ''),
      error: () => {
        /* leer lassen → i18n-/Default-Fallback bleibt */
      },
    });
  }
}
