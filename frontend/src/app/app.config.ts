import {
  type ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
  provideZoneChangeDetection,
} from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';
import { authInterceptor } from '@core/auth/auth.interceptor';
import { AuthService } from '@core/auth/auth.service';
import { mockApiInterceptor } from '@core/api/mock-api.interceptor';
import { ThemeService } from '@core/theme/theme.service';
import { I18nService } from '@core/i18n/i18n.service';
import { provideFormly } from '@shared/formly/formly.providers';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(
      routes,
      withComponentInputBinding(),
      withInMemoryScrolling({ scrollPositionRestoration: 'enabled', anchorScrolling: 'enabled' }),
    ),
    // Reihenfolge: auth (Credentials/Bearer) zuerst, dann ggf. Mock-Antwort.
    provideHttpClient(withInterceptors([authInterceptor, mockApiInterceptor])),
    provideFormly(),
    provideAppInitializer(() => {
      inject(ThemeService).init();
      inject(I18nService); // initialisiert document.lang über Konstruktor-Default
      inject(AuthService).loadPrincipal();
    }),
  ],
};
