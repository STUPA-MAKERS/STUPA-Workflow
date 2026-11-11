import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ThemeService } from '@stupa-makers/ui-kit';
import { createLocationMock, provideLocationMock } from '../../../testing/location-mock';
import { PublicHeaderComponent } from './public-header.component';

async function setup() {
  localStorage.setItem('ap.locale', 'de');
  const location = createLocationMock();
  const view = await render(PublicHeaderComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideLocationMock(location),
    ],
  });
  const injector = view.fixture.debugElement.injector;
  return {
    ...view,
    location,
    auth: injector.get(AuthService),
    http: injector.get(HttpTestingController),
    theme: injector.get(ThemeService),
    i18n: injector.get(I18nService),
  };
}

describe('PublicHeaderComponent', () => {
  afterEach(() => localStorage.clear());

  it('links the wordmark to the public start page and swaps it with the theme', async () => {
    const { fixture, theme, container } = await setup();
    theme.setPreference('light');
    fixture.detectChanges();
    const brand = container.querySelector('a.pub__brand') as HTMLAnchorElement;
    expect(brand).toHaveAttribute('href', '/');
    const logo = container.querySelector('img.pub__logo') as HTMLImageElement;
    expect(logo.getAttribute('src')).toBe('assets/logos/stupa-wordmark-light.svg');
    theme.setPreference('dark');
    fixture.detectChanges();
    expect(logo.getAttribute('src')).toBe('assets/logos/stupa-wordmark-dark.svg');
  });

  it('links the sign-in to the login page', async () => {
    await setup();
    expect(screen.getByRole('link', { name: 'Anmelden' })).toHaveAttribute('href', '/login');
  });

  it('shows Abmelden in place of Anmelden for an e-mail session (F/applications/applications/000588)', async () => {
    const { auth, http, fixture, location } = await setup();
    auth.markApplicantSession();
    fixture.detectChanges();
    expect(screen.queryByRole('link', { name: 'Anmelden' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    http.expectOne('/api/auth/logout').flush({ logout_url: null });
    expect(location.assign).toHaveBeenCalledWith('/');
    expect(auth.applicantSession()).toBe(false);
  });

  it('hides the sign-in for a principal who is signed in', async () => {
    const { auth, http, fixture } = await setup();
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush({ sub: '1', roles: [], permissions: [], groups: [] });
    fixture.detectChanges();
    expect(screen.queryByRole('link', { name: 'Anmelden' })).not.toBeInTheDocument();
  });

  /** §000593 "Dunkles Design" has one switch, in the menu "Barrierefreiheit". */
  it('has no theme button of its own', async () => {
    await setup();
    expect(screen.queryByRole('button', { name: 'Erscheinungsbild wechseln' })).toBeNull();
  });

  it('switches the language with a reload', async () => {
    const { i18n, location } = await setup();
    expect(document.querySelector('select')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Sprache wechseln: DE' }));
    await userEvent.click(screen.getByRole('option', { name: 'English' }));
    expect(i18n.locale()).toBe('en');
    expect(location.reload).toHaveBeenCalled();
  });

  it('offers the help menu with the handbook', async () => {
    const { fixture } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Hilfe' }));
    fixture.detectChanges();
    expect(screen.getByRole('link', { name: /Handbuch im Wiki/ })).toHaveAttribute('target', '_blank');
  });

  /** Spec 000647: "Barrierefreiheit" is its own button, before "Hilfe". */
  it('offers the accessibility menu before the help menu, with the statement', async () => {
    const { fixture } = await setup();
    const a11y = screen.getByRole('button', { name: 'Barrierefreiheit' });
    const help = screen.getByRole('button', { name: 'Hilfe' });
    expect(a11y.compareDocumentPosition(help) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(a11y);
    fixture.detectChanges();
    expect(screen.getByRole('link', { name: 'Erklärung zur Barrierefreiheit' })).toHaveAttribute('href', '/accessibility');
  });
});
