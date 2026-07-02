import { InjectionToken } from '@angular/core';

/**
 * DI-Handle auf `window.location` (#jest30): jsdom ≥26 macht `location` komplett
 * unveränderlich (nicht konfigurierbar, Methoden read-only), direkte Zugriffe sind
 * damit in Tests nicht mehr mockbar. App-Code injiziert stattdessen dieses Token;
 * Specs überschreiben es per Provider (`provideLocationMock`, s. src/testing).
 */
export const LOCATION = new InjectionToken<Location>('app.location', {
  providedIn: 'root',
  factory: () => window.location,
});
