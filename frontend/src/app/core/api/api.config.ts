import { InjectionToken, inject } from '@angular/core';
import { LOCATION } from '../browser/location.token';

/** Base path of the REST API (`web` nginx routes `/api` → `api`). */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL', {
  providedIn: 'root',
  factory: () => '/api',
});

/**
 * Toggles the in-memory mock-backend interceptor.
 *
 * The default is `false`. The FE then talks to the real backend (`/api`). The
 * mock needs an explicit opt-in for dev, harness or tests:
 *   - global flag `window.__USE_MOCK_API__ = true` (set before bootstrap),
 *   - query param `?mock=1`,
 *   - `localStorage['useMockApi'] === '1'`.
 * Unit tests set the token directly with a provider (`{ provide: USE_MOCK_API, … }`).
 */
export const USE_MOCK_API = new InjectionToken<boolean>('USE_MOCK_API', {
  providedIn: 'root',
  factory: () => detectMockFlag(inject(LOCATION)),
});

/** Read the mock opt-in from the global flag, the URL or localStorage (browser only).
 *  `location` comes from DI, so a test needs no jsdom `window.location`. */
export function detectMockFlag(location: Location): boolean {
  if (typeof window === 'undefined') return false; // SSR/prerender → real API
  const w = window as Window & { __USE_MOCK_API__?: boolean };
  if (w.__USE_MOCK_API__ === true) return true;
  try {
    if (new URLSearchParams(location.search).get('mock') === '1') return true;
    if (window.localStorage?.getItem('useMockApi') === '1') return true;
  } catch {
    // localStorage or the URL is unreachable in a sandbox or in SSR → no mock.
  }
  return false;
}
