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
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';
import { authInterceptor } from '@core/auth/auth.interceptor';
import { AuthService } from '@core/auth/auth.service';
import { lazyMockApiInterceptor } from '@core/api/mock-api.lazy';
import { cacheInterceptor } from '@core/cache/cache.interceptor';
import { provideDetailPrefetch } from '@core/cache/detail-prefetch';
import {
  loadingInterceptor,
  ThemeService,
  UI_KIT_AVATAR_SOURCE,
} from '@stupa-makers/ui-kit';
import { provideRouteMotion, watchUAVisualTransitions } from '@stupa-makers/ui-kit/shell';
import { IS_INSTALLED_APP, lockInstalledAppZoom, SwUpdateService } from '@stupa-makers/ui-kit/pwa';
import { USE_MOCK_API } from '@core/api/api.config';
import { LIVE_VOTE_SOURCE } from '@core/ws/live-vote.source';
import { MockLiveVoteSource } from '@core/ws/mock-live-vote.source';
import { WsService } from '@core/ws/ws.service';
import { I18nService } from '@core/i18n/i18n.service';
import { provideAppUiKit } from '@core/i18n/ui-kit-intl';
import { BrandingService } from '@core/branding/branding.service';
import { guardTouchContextMenu } from '@core/touch/touch-context-menu';
import { AvatarService } from '@shared/ui/avatar/avatar.service';
import { routes } from './app.routes';
import { provideServiceWorker } from '@angular/service-worker';

/**
 * The root providers of the app.
 *
 * A long press on a row link opens no link menu of the browser (Android). A back gesture that the
 * browser animated gets no second view transition. English lives in a lazy chunk, so the app waits
 * for it and the first paint is not German.
 *
 * Interceptor order: loading (outermost, measures the full duration) → cache → auth
 * (credentials and bearer) → mock response. The cache sits inside the loading interceptor,
 * because a served-from-cache answer still counts as a completed request for the loading
 * bar, and the auth layer must run for the revalidation that follows.
 *
 * Only the dev or demo build puts the mock interceptor into the chain. In a prod build
 * `isDevMode()` returns false, so the app never registers it, and no input at runtime can
 * activate it and spoof a session or data: not the `?mock=1` query flag, not the
 * `useMockApi` localStorage key, not the `__USE_MOCK_API__` global. The `isDevMode()` guard
 * inside the interceptor stays as defense in depth. The mock loads on its first request
 * (`lazyMockApiInterceptor`), so it is not part of the initial bundle.
 *
 * The person avatars of the kit load the Gravatar image through the API proxy. The service
 * worker (`ngsw-config.json`) caches the app shell and the assets, not `/api`.
 */
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(
      routes,
      withComponentInputBinding(),
      withInMemoryScrolling({ scrollPositionRestoration: 'enabled', anchorScrolling: 'enabled' }),
      provideRouteMotion(),
    ),
    provideHttpClient(
      withInterceptors(
        isDevMode()
          ? [loadingInterceptor, cacheInterceptor, authInterceptor, lazyMockApiInterceptor]
          : [loadingInterceptor, cacheInterceptor, authInterceptor],
      ),
    ),
    provideDetailPrefetch(),
    {
      provide: LIVE_VOTE_SOURCE,
      useFactory: () => (inject(USE_MOCK_API) ? inject(MockLiveVoteSource) : inject(WsService)),
    },
    provideAppUiKit(),
    { provide: UI_KIT_AVATAR_SOURCE, useExisting: AvatarService },
    provideAppInitializer(() => {
      inject(ThemeService).init();
      const i18n = inject(I18nService);
      inject(BrandingService).init();
      inject(AuthService).ensureLoaded().subscribe();
      inject(SwUpdateService).init();
      guardTouchContextMenu(inject(DOCUMENT));
      lockInstalledAppZoom(inject(DOCUMENT), inject(IS_INSTALLED_APP)());
      watchUAVisualTransitions();
      return i18n.ready();
    }),
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
