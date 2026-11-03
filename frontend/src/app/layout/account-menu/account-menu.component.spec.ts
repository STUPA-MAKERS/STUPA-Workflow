import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Principal } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { provideAppUiKit } from '@core/i18n/ui-kit-intl';
import { ThemeService } from '@stupa-makers/ui-kit';
import type { AccountMenuVariant } from '@stupa-makers/ui-kit/shell';
import { createLocationMock, provideLocationMock, type LocationMock } from '../../../testing/location-mock';
import { AppAccountMenuComponent } from './account-menu.component';

@Component({ standalone: true, template: '' })
class StubPage {}

const ACCOUNT_ROUTES = ['account/notifications', 'account/grants'].map((path) => ({
  path,
  component: StubPage,
}));

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: [],
  groups: [],
};

/** The wiring of the kit account menu to the session, the languages and the theme of the app. */
async function setup(
  opts: { variant?: AccountMenuVariant; principal?: Principal; location?: LocationMock } = {},
) {
  localStorage.setItem('ap.locale', 'de');
  const location = opts.location ?? createLocationMock();
  const view = await render(AppAccountMenuComponent, {
    inputs: { variant: opts.variant ?? 'sheet' },
    providers: [
      provideRouter(ACCOUNT_ROUTES),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideAppUiKit(),
      provideLocationMock(location),
    ],
  });
  const injector = view.fixture.debugElement.injector;
  const auth = injector.get(AuthService);
  auth.ensureLoaded().subscribe();
  injector.get(HttpTestingController).expectOne('/api/auth/me').flush(opts.principal ?? MEMBER);
  view.fixture.detectChanges();
  return { ...view, auth, location, theme: injector.get(ThemeService), i18n: injector.get(I18nService) };
}

describe('AppAccountMenuComponent', () => {
  afterEach(() => localStorage.clear());

  it('shows the name of the principal and opens the popover from the avatar', async () => {
    const { fixture } = await setup({ variant: 'popover' });
    await userEvent.click(screen.getByRole('button', { name: 'Konto: Mia Member' }));
    fixture.detectChanges();
    expect(screen.getByRole('region', { name: 'Konto' })).toBeInTheDocument();
    expect(screen.getByText('Mia Member')).toBeInTheDocument();
  });

  /** API access shows only with mcp.use. */
  it('links the account pages', async () => {
    await setup();
    expect(screen.getByRole('link', { name: 'Benachrichtigungen' })).toHaveAttribute(
      'href',
      '/account/notifications',
    );
    expect(screen.queryByRole('link', { name: 'API-Zugang' })).not.toBeInTheDocument();
  });

  it('offers API access with mcp.use', async () => {
    await setup({ principal: { ...MEMBER, permissions: ['mcp.use'] } });
    expect(screen.getByRole('link', { name: 'API-Zugang' })).toHaveAttribute('href', '/account/grants');
  });

  it('switches to dark and back through the switch', async () => {
    const { fixture, theme } = await setup();
    theme.setPreference('light');
    fixture.detectChanges();
    const sw = screen.getByRole('switch', { name: 'Dunkles Design' });
    expect(sw).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(sw);
    fixture.detectChanges();
    expect(theme.preference()).toBe('dark');
    expect(sw).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(sw);
    expect(theme.preference()).toBe('light');
  });

  it('names each language in its own language and switches with a reload', async () => {
    const location = createLocationMock();
    const { i18n } = await setup({ location });
    await userEvent.click(screen.getByRole('button', { name: 'Sprache: Deutsch' }));
    const options = screen.getAllByRole('option');
    expect(options.map((o) => o.textContent?.trim())).toEqual(['Deutsch', 'English']);
    await userEvent.click(screen.getByRole('option', { name: 'English' }));
    expect(i18n.locale()).toBe('en');
    expect(location.reload).toHaveBeenCalledTimes(1);
  });

  it('signs out', async () => {
    const { auth } = await setup();
    const logout = jest.spyOn(auth, 'logout').mockImplementation(() => undefined);
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    expect(logout).toHaveBeenCalled();
  });

  it('reports a followed link, so the sheet around it closes', async () => {
    const { fixture } = await setup();
    const navigated = jest.fn();
    fixture.componentInstance.navigated.subscribe(navigated);
    await userEvent.click(screen.getByRole('link', { name: 'Benachrichtigungen' }));
    expect(navigated).toHaveBeenCalledTimes(1);
  });
});
