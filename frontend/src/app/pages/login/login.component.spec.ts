import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { AltchaService } from '../../features/apply/altcha.service';
import { LoginComponent } from './login.component';

async function setup(request: jest.Mock = jest.fn(() => of(undefined)), query: Record<string, string> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const auth = { login: jest.fn() };
  const view = await render(LoginComponent, {
    providers: [
      provideRouter([]),
      { provide: ApiClient, useValue: { requestEmailLogin: request } },
      { provide: AuthService, useValue: auth },
      { provide: AltchaService, useValue: { solve: jest.fn(() => Promise.resolve('sol')) } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(query) } } },
    ],
  });
  return { ...view, comp: view.fixture.componentInstance, auth, request };
}

/** F/public/public-pages/000589. */
describe('LoginComponent', () => {
  afterEach(() => localStorage.clear());

  it('offers the account login and the e-mail link, the account named by login.accountName', async () => {
    const { auth } = await setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Anmelden' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Mit STUPA-Konto' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Per E-Mail-Link' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Mit SSO anmelden/ }));
    expect(auth.login).toHaveBeenCalled();
  });

  it('sends only a well-formed address with a solved ALTCHA', async () => {
    const { comp, request } = await setup();
    comp.email.set('kein-at');
    comp.altchaSolution.set('sol');
    comp.send();
    expect(request).not.toHaveBeenCalled();
    comp.email.set('lena@example.org');
    comp.altchaSolution.set(null);
    comp.send();
    expect(request).not.toHaveBeenCalled();
    comp.onAltchaUnavailable();
    comp.send();
    expect(request).toHaveBeenCalledWith({ email: 'lena@example.org', altcha: null });
  });

  it('shows the same confirmation for every answer 202 and goes back for another address', async () => {
    const { comp, fixture, request } = await setup();
    comp.email.set(' lena@example.org ');
    comp.onAltchaSolved('sol');
    comp.send();
    fixture.detectChanges();
    expect(request).toHaveBeenCalledWith({ email: 'lena@example.org', altcha: 'sol' });
    expect(screen.getByRole('heading', { name: 'Schau in dein Postfach' })).toBeInTheDocument();
    expect(screen.getByText(/lena@example\.org/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Andere Adresse eingeben' }));
    expect(comp.phase()).toBe('form');
    expect(comp.altchaSolution()).toBeNull();
  });

  it('names a failed request and asks for a new ALTCHA', async () => {
    const { comp, fixture } = await setup(jest.fn(() => throwError(() => ({ status: 429 }))));
    comp.email.set('lena@example.org');
    comp.onAltchaSolved('sol');
    comp.send();
    fixture.detectChanges();
    expect(comp.phase()).toBe('error');
    expect(comp.altchaSolution()).toBeNull();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('says why after an invalid link', async () => {
    await setup(undefined, { link: 'invalid' });
    expect(screen.getByText(/Dieser Link ist abgelaufen/)).toBeInTheDocument();
  });
});
