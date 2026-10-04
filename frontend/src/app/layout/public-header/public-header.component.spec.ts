import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ThemeService } from '@core/theme/theme.service';
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

  it('starts the sign-in', async () => {
    const { location } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));
    expect(location.assign).toHaveBeenCalledWith('/api/auth/login');
  });

  it('hides the sign-in for a principal who is signed in', async () => {
    const { auth, http, fixture } = await setup();
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush({ sub: '1', roles: [], permissions: [], groups: [] });
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Anmelden' })).not.toBeInTheDocument();
  });

  it('toggles the appearance and says which state it is in', async () => {
    const { fixture, theme } = await setup();
    theme.setPreference('light');
    fixture.detectChanges();
    const toggle = screen.getByRole('button', { name: 'Erscheinungsbild wechseln' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(toggle);
    expect(theme.resolved()).toBe('dark');
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
  });

  it('switches the language with a reload', async () => {
    const { i18n, location } = await setup();
    const select = screen.getByRole('combobox', { name: 'Sprache wechseln' }) as HTMLSelectElement;
    expect(select.value).toBe('de');
    await userEvent.selectOptions(select, 'en');
    expect(i18n.locale()).toBe('en');
    expect(location.reload).toHaveBeenCalled();
  });
});
