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
    // Order: loading (outermost, measures full duration) → auth (credentials/bearer)
    // → mock response.
    //
    // Security: the mock interceptor is wired into the chain only in the dev/demo
    // build. In prod builds `isDevMode()` is false, so it is never registered — no
    // runtime-attackable input (?mock=1, localStorage['useMockApi'],
    // __USE_MOCK_API__) can activate it (session/data spoofing). The extra runtime
    // guard in the interceptor (isDevMode()) remains as defence in depth.
    provideHttpClient(
      withInterceptors(
        isDevMode()
          ? [loadingInterceptor, authInterceptor, mockApiInterceptor]
          : [loadingInterceptor, authInterceptor],
      ),
    ),
    // Live-vote source: the in-memory simulation in mock mode, otherwise the real
    // WebSocket (WsService).
    {
      provide: LIVE_VOTE_SOURCE,
      useFactory: () => (inject(USE_MOCK_API) ? inject(MockLiveVoteSource) : inject(WsService)),
    },
    provideFormly(),
    // Bind the UI-kit library (@stupa-makers/ui-kit) to app services: i18n follows
    // the app locale (identical DE/EN strings), loading overlay follows LoadingService.
    { provide: UI_KIT_INTL, useFactory: () => uiKitIntlFromLang(inject(I18nService).locale) },
    { provide: UI_KIT_LOADING, useFactory: () => ({ visible: inject(LoadingService).visible }) },
    provideAppInitializer(() => {
      inject(ThemeService).init();
      inject(I18nService); // initializes document.lang via the constructor default
      inject(BrandingService).init(); // app name from site config → tab title/header/home
      inject(AuthService).ensureLoaded().subscribe();
      inject(SwUpdateService).init();
    }),
    // PWA: service worker only in the prod build (ngsw-config.json caches the app
    // shell + assets; /api is not cached). Registered once the app is stable.
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
