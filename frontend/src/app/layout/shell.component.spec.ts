import { Component, signal } from '@angular/core';
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
import { BrandingService } from '@core/branding/branding.service';
import type { Principal } from '@core/api/models';
import { createLocationMock, provideLocationMock } from '../../testing/location-mock';

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
  // Mock `LOCATION` through DI. A code path that reloads must never touch the
  // real jsdom location, which is immutable.
  const location = createLocationMock();
  const view = await render(ShellComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideLocationMock(location),
    ],
  });
  const auth = view.fixture.debugElement.injector.get(AuthService);
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  // The shell loads the active site config for the footer at start. In real mode
  // (USE_MOCK_API=false) the request goes out, so flush it with neutral data here.
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
  return { ...view, auth, http, location };
}

/** Authenticate the principal so the nav becomes visible. */
function login(auth: AuthService, http: HttpTestingController, principal: Principal): void {
  auth.ensureLoaded().subscribe();
  http.expectOne('/api/auth/me').flush(principal);
}

/**
 * Footer content comes from the branding service, which loads the PUBLIC site config at
 * app start. A shell test therefore states the branding directly instead of answering an
 * HTTP request the shell no longer makes.
 */
function brandingStub(
  over: {
    copyright?: Record<string, string> | null;
    legalLinks?: { label: Record<string, string>; url: string }[];
  } = {},
) {
  return {
    appName: signal('STUPA'),
    homeHeading: signal('Willkommen'),
    copyright: signal(over.copyright ?? null),
    legalLinks: signal(over.legalLinks ?? []),
    init: () => undefined,
  };
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
    // The member lacks admin.config, so the admin link stays hidden.
    expect(screen.queryByRole('link', { name: /Verwaltung/ })).not.toBeInTheDocument();
    // The header shows an icon, not the name: a full display name took more room than
    // anything else there and moved the nav as the name got longer. The name is still
    // reachable — it is the trigger's accessible name and it heads the menu.
    expect(screen.queryByText('Mia Member')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Mia Member/ })).toBeInTheDocument();
    http.verify();
  });

  it('names the signed-in account at the head of the menu it opens', async () => {
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();

    await userEvent.click(screen.getByRole('button', { name: /Mia Member/ }));
    fixture.detectChanges();
    expect(screen.getByText('Mia Member')).toBeInTheDocument();
    http.verify();
  });

  it('logs out via the account action', async () => {
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();

    const spy = jest.spyOn(auth, 'logout').mockImplementation(() => undefined);
    // Logout lives in the account popout, so click the name button first.
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
    // A language change reloads the page to get the server i18n in the new language.
    // jsdom cannot reload, so the test stubs the call.
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

    // The wrapping label gives the language dropdown its accessible name.
    expect(screen.getByRole('combobox', { name: /Sprache|language/i })).toBeInTheDocument();

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
        provideLocationMock(createLocationMock()),
        {
          provide: BrandingService,
          useValue: brandingStub({
            copyright: { de: '© Verfasste Studierendenschaft' },
            legalLinks: [{ label: { de: 'Impressum' }, url: 'https://example.org/impressum' }],
          }),
        },
      ],
    });
    view.fixture.detectChanges();
    const link = screen.getByRole('link', { name: 'Impressum' });
    expect(link).toHaveAttribute('href', 'https://example.org/impressum');
    expect(screen.getByText('© Verfasste Studierendenschaft')).toBeInTheDocument();
    view.fixture.debugElement.injector.get(HttpTestingController).verify();
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

  it('keeps language and appearance out of the header row when signed in', async () => {
    // They are settings, not navigation. Two more controls in the header made it cramped
    // on a desktop and pushed the theme toggle clean off a phone screen.
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();

    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Erscheinungsbild|appearance/i }),
    ).not.toBeInTheDocument();
    http.verify();
  });

  it('offers language and appearance inside the account popout', async () => {
    const { fixture, auth, http } = await setup();
    const theme = fixture.debugElement.injector.get(ThemeService);
    login(auth, http, MEMBER);
    fixture.detectChanges();

    await userEvent.click(screen.getByRole('button', { name: /Mia Member/ }));
    fixture.detectChanges();

    expect(screen.getByRole('combobox', { name: /Sprache|language/i })).toBeInTheDocument();
    const before = theme.resolved();
    await userEvent.click(
      screen.getByRole('menuitemcheckbox', { name: /Erscheinungsbild|appearance/i }),
    );
    expect(theme.resolved()).not.toBe(before);
    http.verify();
  });

  it('still offers both inline when nobody is signed in', async () => {
    // There is no account menu to hold them then, and the header is nearly empty anyway.
    const { fixture, http } = await setup();
    fixture.detectChanges();

    expect(screen.getByRole('combobox', { name: /Sprache|language/i })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Erscheinungsbild|appearance/i }),
    ).toBeInTheDocument();
    http.verify();
  });

  it('puts the search trigger to the left of the account control', async () => {
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();

    const account = screen.getByRole('button', { name: /Mia Member/ });
    const search = screen.getByRole('button', { name: /Suche öffnen|Open search/i });
    // `DOCUMENT_POSITION_PRECEDING` = the search button comes before the account control.
    expect(account.compareDocumentPosition(search) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    http.verify();
  });

  it('shows a magnifier on the search trigger, not the filter funnel', async () => {
    // The funnel is the filter button of the list pages. Searching is not filtering.
    const { fixture, auth, http } = await setup();
    login(auth, http, MEMBER);
    fixture.detectChanges();

    const search = screen.getByRole('button', { name: /Suche öffnen|Open search/i });
    expect(search.querySelector('.fa-magnifying-glass')).toBeTruthy();
    expect(search.querySelector('.fa-filter')).toBeNull();
    http.verify();
  });

  it('drops the wordmark for the bare mark, so a narrow header has both to choose from', async () => {
    // The swap itself is a media query; what a test can hold is that both images exist
    // and that the mark is the one file that does not depend on the theme.
    const { fixture, http } = await setup();
    fixture.detectChanges();

    const brand = document.querySelector('.header__brand');
    expect(brand?.querySelector('.header__logo')).toBeTruthy();
    expect(brand?.querySelector('.header__mark')?.getAttribute('src')).toBe(
      'assets/logos/stupa-mark.svg',
    );
    http.verify();
  });

  it('resolves the wide layout from the deepest active route data', async () => {
    const view = await render(ShellComponent, {
      providers: [
        provideRouter(wideRoutes),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        provideLocationMock(createLocationMock()),
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

    await router.navigateByUrl('/narrow');
    view.fixture.detectChanges();
    expect(cmp.wide()).toBe(false);
    http.verify();
  });

  it('keeps the default footer when the branding config is unavailable', async () => {
    // The branding service swallows a failed load and keeps its empty defaults, so the
    // shell sees exactly this and falls back to the built-in footer.
    const view = await render(ShellComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        provideLocationMock(createLocationMock()),
        { provide: BrandingService, useValue: brandingStub() },
      ],
    });
    view.fixture.detectChanges();
    const cmp = view.fixture.componentInstance as ShellComponent;
    expect(cmp.footerLinks()).toEqual([]);
    expect(cmp.footerCopyright()).toBe('');
    view.fixture.debugElement.injector.get(HttpTestingController).verify();
  });

  it('falls back to empty footer state when the config omits links and copyright', async () => {
    const view = await render(ShellComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        provideLocationMock(createLocationMock()),
        { provide: BrandingService, useValue: brandingStub({ copyright: {}, legalLinks: [] }) },
      ],
    });
    view.fixture.detectChanges();
    const cmp = view.fixture.componentInstance as ShellComponent;
    expect(cmp.footerLinks()).toEqual([]);
    expect(cmp.footerCopyright()).toBe('');
    view.fixture.debugElement.injector.get(HttpTestingController).verify();
  });

  it('reloadForLocale reloads when window is available', async () => {
    const { fixture, http, location } = await setup();
    const cmp = fixture.componentInstance as unknown as { reloadForLocale: () => void };
    cmp.reloadForLocale();
    expect(location.reload).toHaveBeenCalled();
    http.verify();
  });
});
