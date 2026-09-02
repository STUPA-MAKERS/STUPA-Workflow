import {
  type ApplicationConfig,
  inject,
  isDevMode,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
  provideZoneChangeDetection,
} from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';
import { authInterceptor } from '@core/auth/auth.interceptor';
import { AuthService } from '@core/auth/auth.service';
import { mockApiInterceptor } from '@core/api/mock-api.interceptor';
import { cacheInterceptor } from '@core/cache/cache.interceptor';
import { loadingInterceptor } from '@core/loading/loading.interceptor';
import { LoadingService } from '@core/loading/loading.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { UI_KIT_INTL, UI_KIT_LOADING, uiKitIntlFromLang } from '@stupa-makers/ui-kit';
import { LIVE_VOTE_SOURCE } from '@core/ws/live-vote.source';
import { MockLiveVoteSource } from '@core/ws/mock-live-vote.source';
import { WsService } from '@core/ws/ws.service';
import { ThemeService } from '@core/theme/theme.service';
import { I18nService } from '@core/i18n/i18n.service';
import { BrandingService } from '@core/branding/branding.service';
import { SwUpdateService } from '@core/pwa/sw-update.service';
import { provideFormly } from '@shared/formly/formly.providers';
import { routes } from './app.routes';
import { provideServiceWorker } from '@angular/service-worker';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(
      routes,
      withComponentInputBinding(),
      withInMemoryScrolling({ scrollPositionRestoration: 'enabled', anchorScrolling: 'enabled' }),
    ),
    // Order: loading (outermost, measures the full duration) → auth (credentials and
    // bearer) → mock response.
    //
    // Security: only the dev or demo build puts the mock interceptor into the chain. In a
    // prod build `isDevMode()` returns false, so the app never registers it. No input at
    // runtime can activate it and spoof a session or data. This covers the `?mock=1` query
    // flag, the `useMockApi` localStorage key and the `__USE_MOCK_API__` global. The
    // `isDevMode()` guard inside the interceptor stays as defense in depth.
    provideHttpClient(
      withInterceptors(
        isDevMode()
          // The cache sits INSIDE the loading interceptor: a served-from-cache answer
          // still counts as a completed request for the overlay, and the auth layer
          // must run for the revalidation that follows.
          ? [loadingInterceptor, cacheInterceptor, authInterceptor, mockApiInterceptor]
          : [loadingInterceptor, cacheInterceptor, authInterceptor],
      ),
    ),
    {
      provide: LIVE_VOTE_SOURCE,
      useFactory: () => (inject(USE_MOCK_API) ? inject(MockLiveVoteSource) : inject(WsService)),
    },
    provideFormly(),
    { provide: UI_KIT_INTL, useFactory: () => uiKitIntlFromLang(inject(I18nService).locale) },
    { provide: UI_KIT_LOADING, useFactory: () => ({ visible: inject(LoadingService).visible }) },
    provideAppInitializer(() => {
      inject(ThemeService).init();
      inject(I18nService); // the constructor default sets document.lang
      inject(BrandingService).init(); // site-config app name: tab title, header, home
      inject(AuthService).ensureLoaded().subscribe();
      inject(SwUpdateService).init();
    }),
    // ngsw-config.json caches the app shell and the assets. It does not cache /api.
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
