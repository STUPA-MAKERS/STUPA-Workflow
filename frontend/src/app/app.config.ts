import { DOCUMENT } from '@angular/common';
import {
  type ApplicationConfig,
  inject,
  isDevMode,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
  provideZoneChangeDetection,
} from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  provideRouter,
  withComponentInputBinding,
  withInMemoryScrolling,
  withViewTransitions,
} from '@angular/router';
import { onRouteViewTransition, watchUAVisualTransitions } from '@core/motion/motion';
import { authInterceptor } from '@core/auth/auth.interceptor';
import { AuthService } from '@core/auth/auth.service';
import { lazyMockApiInterceptor } from '@core/api/mock-api.lazy';
import { cacheInterceptor } from '@core/cache/cache.interceptor';
import { provideDetailPrefetch } from '@core/cache/detail-prefetch';
import { loadingInterceptor } from '@core/loading/loading.interceptor';
import { LoadingService } from '@core/loading/loading.service';
import { USE_MOCK_API } from '@core/api/api.config';
import {
  UI_KIT_AVATAR_SOURCE,
  UI_KIT_INTL,
  UI_KIT_LOADING,
  uiKitIntlFromLang,
} from '@stupa-makers/ui-kit';
import { LIVE_VOTE_SOURCE } from '@core/ws/live-vote.source';
import { MockLiveVoteSource } from '@core/ws/mock-live-vote.source';
import { WsService } from '@core/ws/ws.service';
import { ThemeService } from '@core/theme/theme.service';
import { I18nService } from '@core/i18n/i18n.service';
import { BrandingService } from '@core/branding/branding.service';
import { SwUpdateService } from '@core/pwa/sw-update.service';
import { guardTouchContextMenu } from '@core/touch/touch-context-menu';
import { AvatarService } from '@shared/ui/avatar/avatar.service';
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
      withViewTransitions({
        skipInitialTransition: true,
        onViewTransitionCreated: onRouteViewTransition,
      }),
    ),
    // Order: loading (outermost, measures the full duration) → auth (credentials and
    // bearer) → mock response.
    //
    // Security: only the dev or demo build puts the mock interceptor into the chain. In a
    // prod build `isDevMode()` returns false, so the app never registers it. No input at
    // runtime can activate it and spoof a session or data. This covers the `?mock=1` query
    // flag, the `useMockApi` localStorage key and the `__USE_MOCK_API__` global. The
    // `isDevMode()` guard inside the interceptor stays as defense in depth. The mock
    // loads on its first request (`lazyMockApiInterceptor`), so it is not part of the
    // initial bundle.
    provideHttpClient(
      withInterceptors(
        isDevMode()
          // The cache sits INSIDE the loading interceptor: a served-from-cache answer
          // still counts as a completed request for the loading bar, and the auth layer
          // must run for the revalidation that follows.
          ? [loadingInterceptor, cacheInterceptor, authInterceptor, lazyMockApiInterceptor]
          : [loadingInterceptor, cacheInterceptor, authInterceptor],
      ),
    ),
    provideDetailPrefetch(),
    {
      provide: LIVE_VOTE_SOURCE,
      useFactory: () => (inject(USE_MOCK_API) ? inject(MockLiveVoteSource) : inject(WsService)),
    },
    {
      provide: UI_KIT_INTL,
      useFactory: () => {
        const i18n = inject(I18nService);
        return uiKitIntlFromLang(i18n.locale, undefined, i18n.formatLocale);
      },
    },
    { provide: UI_KIT_LOADING, useFactory: () => ({ visible: inject(LoadingService).visible }) },
    // The person avatars of the kit load the Gravatar image through the API proxy.
    { provide: UI_KIT_AVATAR_SOURCE, useExisting: AvatarService },
    provideAppInitializer(() => {
      inject(ThemeService).init();
      const i18n = inject(I18nService); // the constructor default sets document.lang
      inject(BrandingService).init(); // site-config app name: tab title, header, home
      inject(AuthService).ensureLoaded().subscribe();
      inject(SwUpdateService).init();
      // A long press on a row link opens no link menu of the browser (Android).
      guardTouchContextMenu(inject(DOCUMENT));
      // A back gesture that the browser animated gets no second transition from us.
      watchUAVisualTransitions();
      // EN lives in a lazy chunk. Wait for it, so the first paint is not German.
      return i18n.ready();
    }),
    // ngsw-config.json caches the app shell and the assets. It does not cache /api.
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
