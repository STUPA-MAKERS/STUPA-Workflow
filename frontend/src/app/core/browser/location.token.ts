import { InjectionToken } from '@angular/core';

/**
 * DI handle onto `window.location`: jsdom ≥26 makes `location` fully immutable
 * (non-configurable, methods read-only), so direct access is no longer mockable
 * in tests. App code injects this token instead; specs override it via a
 * provider (`provideLocationMock`, see src/testing).
 */
export const LOCATION = new InjectionToken<Location>('app.location', {
  providedIn: 'root',
  factory: () => window.location,
});
