import { InjectionToken } from '@angular/core';

/** Basis-Pfad der REST-API (deployment.md: `web`-nginx routet `/api` → `api`). */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL', {
  providedIn: 'root',
  factory: () => '/api',
});

/** Schaltet den In-Memory-Mock-Backend-Interceptor (Skelett-Betrieb ohne API). */
export const USE_MOCK_API = new InjectionToken<boolean>('USE_MOCK_API', {
  providedIn: 'root',
  factory: () => true,
});
