import { Component } from '@angular/core';
import { Router, provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ShellComponent } from './shell.component';
import { ThemeService } from '@core/theme/theme.service';
import { I18nService } from '@core/i18n/i18n.service';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Principal } from '@core/api/models';

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['application.read', 'vote.cast'],
  groups: [],
};

@Component({ standalone: true, template: 'page' })
class StubPage {}

/** Routes used to exercise the `wide` route-data resolution. */
const wideRoutes = [
  { path: 'narrow', component: StubPage },
  {
    path: 'budget',
    component: StubPage,
    children: [{ path: 'wide', component: StubPage, data: { wide: true } }],
  },
];

async function setup() {
  const view = await render(ShellComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const auth = view.fixture.debugElement.injector.get(AuthService);
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  // Shell lädt beim Start die aktive Site-Config für die Fußzeile (#82). Im
  // Real-Modus (USE_MOCK_API=false) geht der Request raus — hier neutral flushen.
  http
    .match((r) => r.url.endsWith('/admin/site-config'))
    .forEach((req) =>
      req.flush({
        version: 1,
        active: { logos: {}, footerColumns: [], copyright: {}, legalLinks: [], freetexts: {} },
        draft: { logos: {}, footerColumns: [], copyright: {}, legalLinks: [], freetexts: {} },
        hasDraftChanges: false,
      }),
    );
  return { ...view, auth, http };
}

/** Authentifiziert den Principal und triggert die Nav-Sichtbarkeit. */
function login(auth: AuthService, http: HttpTestingController, principal: Principal): void {
  auth.ensureLoaded().subscribe();
  http.expectOne('/api/auth/me').flush(principal);
}

describe('ShellComponent', () => {
  beforeEach(() => localStorage.clear());

  it('shows only a sign-in action and no nav when anonymous', async () => {
    const { fixture, http } = await setup();
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: /Anmelden|Sign in/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Dashboard/ })).not.toBeInTheDocument();
    http.verify();
  });

  it('renders RBAC-permitted nav links and hides the rest when signed in', async () => {
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();

    expect(screen.getByRole('link', { name: /Dashboard/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Anträge/ })).toBeInTheDocument();
    // member lacks admin.config → Verwaltung hidden
    expect(screen.queryByRole('link', { name: /Verwaltung/ })).not.toBeInTheDocument();
    expect(screen.getByText('Mia Member')).toBeInTheDocument();
    http.verify();
  });

  it('logs out via the account action', async () => {
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();

    const spy = jest.spyOn(auth, 'logout').mockImplementation(() => undefined);
    // Logout liegt jetzt im Konto-Popout (#51): erst den Namen anklicken.
    await userEvent.click(screen.getByRole('button', { name: /Mia Member/ }));
    await userEvent.click(screen.getByRole('menuitem', { name: /Abmelden|Sign out/ }));
    expect(spy).toHaveBeenCalled();
    http.verify();
  });

  it('toggles the theme via the toggle button', async () => {
    const { fixture, http } = await setup();
    const theme = fixture.debugElement.injector.get(ThemeService);
    const before = theme.resolved();
    await userEvent.click(screen.getByRole('button', { name: /Erscheinungsbild|appearance/ }));
    expect(theme.resolved()).not.toBe(before);
    http.verify();
  });

  it('switches locale through the language selector and reloads the view', async () => {
    // Sprachwechsel lädt neu (server-i18n in neuer Sprache) — in jsdom gestubbt.
    const reload = jest
      .spyOn(
        ShellComponent.prototype as unknown as { reloadForLocale: () => void },
        'reloadForLocale',
      )
      .mockImplementation(() => {});
    const { fixture, http } = await setup();
    const i18n = fixture.debugElement.injector.get(I18nService);
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('de');
    await userEvent.selectOptions(select, 'en');
    expect(i18n.locale()).toBe('en');
    expect(reload).toHaveBeenCalled();
    reload.mockRestore();
    http.verify();
  });

  it('shows the persisted locale as the selected option on load', async () => {
    localStorage.setItem('ap.locale', 'en');
    const { http } = await setup();
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('en');
    localStorage.clear();
    http.verify();
  });

  it('exposes accessible header controls (labelled select, aria-pressed toggle)', async () => {
    const { fixture, http } = await setup();
    const theme = fixture.debugElement.injector.get(ThemeService);
    theme.setPreference('light');
    fixture.detectChanges();

    // Language dropdown has an accessible name from the wrapping label.
    expect(screen.getByRole('combobox', { name: /Sprache|language/i })).toBeInTheDocument();

    // Theme toggle mirrors the resolved theme via aria-pressed.
    const toggle = screen.getByRole('button', { name: /Erscheinungsbild|appearance/i });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    http.verify();
  });

  it('renders maintained legal links and copyright in the footer (#82)', async () => {
    const view = await render(ShellComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http.expectOne((r) => r.url.endsWith('/admin/site-config')).flush({
      version: 2,
      active: {
        logos: {},
        footerColumns: [],
        copyright: { de: '© Verfasste Studierendenschaft' },
        legalLinks: [{ label: { de: 'Impressum' }, url: 'https://example.org/impressum' }],
        freetexts: {},
      },
      draft: { logos: {}, footerColumns: [], copyright: {}, legalLinks: [], freetexts: {} },
      hasDraftChanges: false,
    });
    view.fixture.detectChanges();
    const link = screen.getByRole('link', { name: 'Impressum' });
    expect(link).toHaveAttribute('href', 'https://example.org/impressum');
    expect(screen.getByText('© Verfasste Studierendenschaft')).toBeInTheDocument();
    http.verify();
  });

  it('uses a theme-dependent wordmark and swaps it when the theme changes', async () => {
    const { fixture, container, http } = await setup();
    const theme = fixture.debugElement.injector.get(ThemeService);
    theme.setPreference('light');
    fixture.detectChanges();
    const logo = () => container.querySelector('.header__logo') as HTMLImageElement;
    expect(logo().getAttribute('src')).toBe('assets/logos/stupa-wordmark-light.svg');

    theme.setPreference('dark');
    fixture.detectChanges();
    expect(logo().getAttribute('src')).toBe('assets/logos/stupa-wordmark-dark.svg');
    http.verify();
  });

  it('points the brand link at home when anonymous and the dashboard when signed in', async () => {
    const { fixture, auth, container, http } = await setup();
    fixture.detectChanges();
    const brand = () => container.querySelector('.header__brand') as HTMLAnchorElement;
    expect(brand().getAttribute('href')).toBe('/');

    login(auth, http, MEMBER);
    fixture.detectChanges();
    expect(brand().getAttribute('href')).toBe('/dashboard');
    http.verify();
  });

  it('starts the OIDC login from the sign-in button when anonymous', async () => {
    const { fixture, auth, http } = await setup();
    fixture.detectChanges();
    const spy = jest.spyOn(auth, 'login').mockImplementation(() => undefined);
    await userEvent.click(screen.getByRole('button', { name: /Anmelden|Sign in/ }));
    expect(spy).toHaveBeenCalled();
    http.verify();
  });

  it('does not reload the view when the locale is unchanged', async () => {
    const reload = jest
      .spyOn(
        ShellComponent.prototype as unknown as { reloadForLocale: () => void },
        'reloadForLocale',
      )
      .mockImplementation(() => {});
    const { http } = await setup();
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    // Re-selecting the already-active locale is a no-op (no reload).
    await userEvent.selectOptions(select, 'de');
    expect(reload).not.toHaveBeenCalled();
    reload.mockRestore();
    http.verify();
  });

  it('opens and closes the mobile nav drawer, closing it on Escape', async () => {
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();
    const cmp = fixture.componentInstance as ShellComponent;

    expect(cmp.mobileNavOpen()).toBe(false);
    cmp.toggleMobileNav();
    expect(cmp.mobileNavOpen()).toBe(true);
    // Escape closes the drawer (and the account menu).
    cmp.onEscape();
    expect(cmp.mobileNavOpen()).toBe(false);
    http.verify();
  });

  it('opens and closes the account menu and closes it on logout/escape', async () => {
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();
    const cmp = fixture.componentInstance as ShellComponent;
    const logoutSpy = jest.spyOn(auth, 'logout').mockImplementation(() => undefined);

    cmp.toggleAccountMenu();
    expect(cmp.accountMenuOpen()).toBe(true);
    cmp.toggleAccountMenu();
    expect(cmp.accountMenuOpen()).toBe(false);

    cmp.toggleAccountMenu();
    cmp.logout();
    expect(cmp.accountMenuOpen()).toBe(false);
    expect(logoutSpy).toHaveBeenCalled();

    cmp.toggleAccountMenu();
    cmp.onEscape();
    expect(cmp.accountMenuOpen()).toBe(false);
    http.verify();
  });

  it('resolves the wide layout from the deepest active route data', async () => {
    const view = await render(ShellComponent, {
      providers: [
        provideRouter(wideRoutes),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    const router = view.fixture.debugElement.injector.get(Router);
    http
      .match((r) => r.url.endsWith('/admin/site-config'))
      .forEach((req) =>
        req.flush({
          version: 1,
          active: { logos: {}, footerColumns: [], copyright: {}, legalLinks: [], freetexts: {} },
          draft: { logos: {}, footerColumns: [], copyright: {}, legalLinks: [], freetexts: {} },
          hasDraftChanges: false,
        }),
      );
    const cmp = view.fixture.componentInstance as ShellComponent;

    await router.navigateByUrl('/narrow');
    view.fixture.detectChanges();
    expect(cmp.wide()).toBe(false);

    await router.navigateByUrl('/budget/wide');
    view.fixture.detectChanges();
    expect(cmp.wide()).toBe(true);

    // Navigating back to a narrow route clears the wide flag.
    await router.navigateByUrl('/narrow');
    view.fixture.detectChanges();
    expect(cmp.wide()).toBe(false);
    http.verify();
  });

  it('keeps the default footer when the site-config request errors', async () => {
    const view = await render(ShellComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http
      .expectOne((r) => r.url.endsWith('/admin/site-config'))
      .flush(null, { status: 500, statusText: 'Server Error' });
    view.fixture.detectChanges();
    const cmp = view.fixture.componentInstance as ShellComponent;
    // Error path → no maintained links/copyright, defaults shown.
    expect(cmp.footerLinks()).toEqual([]);
    expect(cmp.footerCopyright()).toBe('');
    http.verify();
  });

  it('falls back to empty footer state when the active config omits links and copyright', async () => {
    const view = await render(ShellComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    // active without legalLinks/copyright → the `?? []` / `?? null` fallbacks fire.
    http.expectOne((r) => r.url.endsWith('/admin/site-config')).flush({
      version: 1,
      active: { logos: {}, footerColumns: [], freetexts: {} },
      draft: { logos: {}, footerColumns: [], copyright: {}, legalLinks: [], freetexts: {} },
      hasDraftChanges: false,
    });
    view.fixture.detectChanges();
    const cmp = view.fixture.componentInstance as ShellComponent;
    expect(cmp.footerLinks()).toEqual([]);
    expect(cmp.footerCopyright()).toBe('');
    http.verify();
  });

  it('reloadForLocale reloads when window is available', async () => {
    const { fixture, http } = await setup();
    const cmp = fixture.componentInstance as unknown as { reloadForLocale: () => void };
    const reloadFn = jest.fn();
    const original = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...original, reload: reloadFn },
    });
    cmp.reloadForLocale();
    expect(reloadFn).toHaveBeenCalled();
    Object.defineProperty(window, 'location', { configurable: true, value: original });
    http.verify();
  });
});
