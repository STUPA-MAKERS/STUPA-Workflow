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
import { ThemeService } from '@core/theme/theme.service';
import { createLocationMock, provideLocationMock, type LocationMock } from '../../../testing/location-mock';
import { AccountMenuComponent, type AccountMenuVariant } from './account-menu.component';

@Component({ standalone: true, template: '' })
class StubPage {}

const ACCOUNT_ROUTES = ['account/notifications', 'account/calendar', 'account/grants'].map((path) => ({
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

async function setup(
  opts: { variant?: AccountMenuVariant; principal?: Principal; location?: LocationMock } = {},
) {
  localStorage.setItem('ap.locale', 'de');
  const location = opts.location ?? createLocationMock();
  const view = await render(AccountMenuComponent, {
    inputs: { variant: opts.variant ?? 'popover' },
    providers: [
      provideRouter(ACCOUNT_ROUTES),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideLocationMock(location),
    ],
  });
  const injector = view.fixture.debugElement.injector;
  const auth = injector.get(AuthService);
  const http = injector.get(HttpTestingController);
  auth.ensureLoaded().subscribe();
  http.expectOne('/api/auth/me').flush(opts.principal ?? MEMBER);
  view.fixture.detectChanges();
  return { ...view, auth, http, location, theme: injector.get(ThemeService), i18n: injector.get(I18nService) };
}

const trigger = () => screen.getByRole('button', { name: 'Konto: Mia Member' });

describe('AccountMenuComponent', () => {
  afterEach(() => localStorage.clear());

  describe('popover', () => {
    it('shows the avatar with the initials and opens the menu on click', async () => {
      const { fixture } = await setup();
      expect(trigger()).toHaveTextContent('MM');
      expect(trigger()).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByText('Angemeldet als')).not.toBeInTheDocument();

      await userEvent.click(trigger());
      fixture.detectChanges();
      expect(trigger()).toHaveAttribute('aria-expanded', 'true');
      const panel = screen.getByRole('region', { name: 'Konto' });
      expect(trigger()).toHaveAttribute('aria-controls', panel.id);
      expect(screen.getByText('Angemeldet als')).toBeInTheDocument();
      expect(screen.getByText('Mia Member')).toBeInTheDocument();
    });

    it('closes again on a second click of the avatar', async () => {
      const { fixture } = await setup();
      await userEvent.click(trigger());
      fixture.detectChanges();
      await userEvent.click(trigger());
      fixture.detectChanges();
      expect(trigger()).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByRole('region', { name: 'Konto' })).not.toBeInTheDocument();
    });

    it('links the account pages', async () => {
      const { fixture } = await setup();
      await userEvent.click(trigger());
      fixture.detectChanges();
      expect(screen.getByRole('link', { name: 'Benachrichtigungen' })).toHaveAttribute(
        'href',
        '/account/notifications',
      );
      expect(screen.getByRole('link', { name: 'Kalender-Abo' })).toHaveAttribute('href', '/account/calendar');
      // API access only with mcp.use.
      expect(screen.queryByRole('link', { name: 'API-Zugang' })).not.toBeInTheDocument();
    });

    it('offers API access with mcp.use', async () => {
      const { fixture } = await setup({ principal: { ...MEMBER, permissions: ['mcp.use'] } });
      await userEvent.click(trigger());
      fixture.detectChanges();
      expect(screen.getByRole('link', { name: 'API-Zugang' })).toHaveAttribute('href', '/account/grants');
    });

    it('closes on Escape and gives the focus back to the avatar', async () => {
      const { fixture } = await setup();
      await userEvent.click(trigger());
      fixture.detectChanges();
      await userEvent.keyboard('{Escape}');
      fixture.detectChanges();
      expect(screen.queryByRole('region', { name: 'Konto' })).not.toBeInTheDocument();
      expect(trigger()).toHaveFocus();
    });

    it('closes on a click outside and stays open on a click inside', async () => {
      const { fixture } = await setup();
      await userEvent.click(trigger());
      fixture.detectChanges();
      await userEvent.click(screen.getByText('Angemeldet als'));
      fixture.detectChanges();
      expect(screen.getByRole('region', { name: 'Konto' })).toBeInTheDocument();

      await userEvent.click(document.body);
      fixture.detectChanges();
      expect(screen.queryByRole('region', { name: 'Konto' })).not.toBeInTheDocument();
    });

    it('closes when the focus leaves it, and leaves the focus where it went', async () => {
      const { fixture, container } = await setup();
      const after = document.createElement('a');
      after.href = '#after';
      after.textContent = 'Danach';
      container.parentElement!.appendChild(after);
      await userEvent.click(trigger());
      fixture.detectChanges();
      screen.getByRole('button', { name: 'Abmelden' }).focus();
      fixture.detectChanges();
      expect(fixture.componentInstance.open()).toBe(true);

      await userEvent.tab();
      fixture.detectChanges();
      expect(fixture.componentInstance.open()).toBe(false);
      expect(screen.queryByRole('region', { name: 'Konto' })).not.toBeInTheDocument();
      expect(after).toHaveFocus();
      after.remove();
    });

    it('stays open while the focus moves inside it', async () => {
      const { fixture } = await setup();
      await userEvent.click(trigger());
      fixture.detectChanges();
      screen.getByRole('link', { name: 'Benachrichtigungen' }).focus();
      await userEvent.tab();
      fixture.detectChanges();
      expect(screen.getByRole('link', { name: 'Kalender-Abo' })).toHaveFocus();
      expect(fixture.componentInstance.open()).toBe(true);
    });

    it('closes when the window is resized', async () => {
      const { fixture } = await setup();
      await userEvent.click(trigger());
      fixture.detectChanges();
      window.dispatchEvent(new Event('resize'));
      fixture.detectChanges();
      expect(screen.queryByRole('region', { name: 'Konto' })).not.toBeInTheDocument();
    });

    it('closes when a link is followed', async () => {
      const { fixture } = await setup();
      await userEvent.click(trigger());
      fixture.detectChanges();
      await userEvent.click(screen.getByRole('link', { name: 'Kalender-Abo' }));
      fixture.detectChanges();
      expect(screen.queryByRole('region', { name: 'Konto' })).not.toBeInTheDocument();
    });

    it('places the menu beside the navigation that holds the avatar', async () => {
      const { fixture, container } = await setup();
      const nav = document.createElement('nav');
      container.parentElement!.appendChild(nav);
      nav.appendChild(container);
      jest.spyOn(nav, 'getBoundingClientRect').mockReturnValue({ right: 96 } as DOMRect);
      jest
        .spyOn(trigger(), 'getBoundingClientRect')
        .mockReturnValue({ right: 70, bottom: window.innerHeight - 16 } as DOMRect);
      await userEvent.click(trigger());
      fixture.detectChanges();
      const panel = screen.getByRole('region', { name: 'Konto' });
      expect(panel.style.left).toBe('104px');
      expect(panel.style.bottom).toBe('16px');
    });
  });

  describe('settings', () => {
    it('switches to dark and back through the switch', async () => {
      const { fixture, theme } = await setup({ variant: 'sheet' });
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
      const { i18n } = await setup({ variant: 'sheet', location });
      const select = screen.getByRole('combobox', { name: 'Sprache' }) as HTMLSelectElement;
      expect(Array.from(select.options).map((o) => o.textContent?.trim())).toEqual(['Deutsch', 'English']);
      expect(select.value).toBe('de');

      await userEvent.selectOptions(select, 'en');
      expect(i18n.locale()).toBe('en');
      expect(location.reload).toHaveBeenCalledTimes(1);
    });

    it('signs out', async () => {
      const { auth } = await setup({ variant: 'sheet' });
      const logout = jest.spyOn(auth, 'logout').mockImplementation(() => undefined);
      await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
      expect(logout).toHaveBeenCalled();
    });
  });

  describe('sheet', () => {
    it('shows the content inline, without the avatar', async () => {
      await setup({ variant: 'sheet' });
      expect(screen.queryByRole('button', { name: /^Konto:/ })).not.toBeInTheDocument();
      expect(screen.getByRole('group', { name: 'Konto' })).toBeInTheDocument();
      expect(screen.getByText('Mia Member')).toBeInTheDocument();
    });

    it('reports a followed link, so the sheet around it closes', async () => {
      const { fixture } = await setup({ variant: 'sheet' });
      const navigated = jest.fn();
      fixture.componentInstance.navigated.subscribe(navigated);
      await userEvent.click(screen.getByRole('link', { name: 'Benachrichtigungen' }));
      expect(navigated).toHaveBeenCalledTimes(1);
    });
  });
});
