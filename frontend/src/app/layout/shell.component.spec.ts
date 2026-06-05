import { provideRouter } from '@angular/router';
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
    await userEvent.click(screen.getByRole('button', { name: /Abmelden|Sign out/ }));
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

  it('switches locale through the language selector', async () => {
    const { fixture, http } = await setup();
    const i18n = fixture.debugElement.injector.get(I18nService);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'en');
    expect(i18n.locale()).toBe('en');
    http.verify();
  });
});
