import { InjectionToken } from '@angular/core';

/** Basis-Pfad der REST-API (deployment.md: `web`-nginx routet `/api` → `api`). */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL', {
  providedIn: 'root',
  factory: () => '/api',
});

/**
 * Schaltet den In-Memory-Mock-Backend-Interceptor.
 *
 * Default **`false`** (#67): das FE spricht das **echte** Backend (`/api`) an.
 * Der Mock ist nur noch ein **explizites** Opt-in für Dev/Harness/Tests:
 *   - globales Flag `window.__USE_MOCK_API__ = true` (vor dem Bootstrap gesetzt),
 *   - Query-Param `?mock=1`,
 *   - `localStorage['useMockApi'] === '1'`.
 * Unit-Tests setzen den Token direkt per Provider (`{ provide: USE_MOCK_API, … }`).
 */
export const USE_MOCK_API = new InjectionToken<boolean>('USE_MOCK_API', {
  providedIn: 'root',
  factory: detectMockFlag,
});

/** Liest das Mock-Opt-in aus globalem Flag / URL / localStorage (Browser-only). */
function detectMockFlag(): boolean {
  if (typeof window === 'undefined') return false; // SSR/Prerender → echtes API
  const w = window as Window & { __USE_MOCK_API__?: boolean };
  if (w.__USE_MOCK_API__ === true) return true;
  try {
    if (new URLSearchParams(window.location.search).get('mock') === '1') return true;
    if (window.localStorage?.getItem('useMockApi') === '1') return true;
  } catch {
    // localStorage/URL im Sandbox/SSR nicht erreichbar → kein Mock.
  }
  return false;
}
