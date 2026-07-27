import { InjectionToken } from '@angular/core';

/**
 * DI handle onto `window.location`.
 *
 * jsdom 26 and later make `location` fully immutable (non-configurable, read-only
 * methods), so a test can no longer mock direct access. App code injects this
 * token instead. A spec overrides it with a provider (`provideLocationMock`, see
 * src/testing).
 */
export const LOCATION = new InjectionToken<Location>('app.location', {
  providedIn: 'root',
  factory: () => window.location,
});
