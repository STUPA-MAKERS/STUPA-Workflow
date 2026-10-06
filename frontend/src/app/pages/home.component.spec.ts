import { signal } from '@angular/core';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { HomeComponent } from './home.component';

function setup(
  auth: { login: jest.Mock } = { login: jest.fn() },
  freetexts: Record<string, Record<string, string>> = {},
) {
  return render(HomeComponent, {
    providers: [
      provideRouter([]),
      { provide: AuthService, useValue: auth },
      { provide: BrandingService, useValue: { freetexts: signal(freetexts) } },
    ],
  }).then((view) => ({ ...view, auth }));
}

describe('HomeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('offers exactly two ways in and nothing else', async () => {
    await setup();
    // The apply choice is a router link; the login choice is a button, because the OIDC
    // redirect leaves the SPA and has no route of its own.
    const apply = screen.getByRole('link', { name: /Antrag stellen/ });
    expect(apply).toHaveAttribute('href', '/apply');
    expect(screen.getByRole('button', { name: /Gremiumsmitglied anmelden/ })).toBeInTheDocument();
    // Nothing else competes with them: one link and one button in the body.
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  it('shows the configured welcome text below the heading, in the active language', async () => {
    await setup(undefined, { welcome: { de: 'Hier stellst du Anträge an den StuPa.', en: 'Apply here.' } });
    expect(screen.getByText('Hier stellst du Anträge an den StuPa.')).toBeInTheDocument();
  });

  it('shows no welcome line without a configured text', async () => {
    const { container } = await setup(undefined, { welcome: { de: '   ' } });
    expect(container.querySelector('.home__welcome')).toBeNull();
  });

  it('starts the OIDC login from the member choice', async () => {
    const { auth } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /Gremiumsmitglied anmelden/ }));
    expect(auth.login).toHaveBeenCalled();
  });

  it('keeps the returning-applicant magic-link note', async () => {
    await setup();
    expect(screen.getByText(/Bestätigungs-E-Mail/)).toBeInTheDocument();
  });

  it('localizes both choices and the note to English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Welcome' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Submit an application/ })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Sign in as a committee member/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/confirmation email/)).toBeInTheDocument();
  });

  describe('refused login', () => {
    async function withQuery(q: Record<string, string>) {
      return render(HomeComponent, {
        providers: [
          provideRouter([]),
          { provide: AuthService, useValue: { login: jest.fn() } },
          { provide: BrandingService, useValue: { freetexts: signal({}) } },
          {
            provide: ActivatedRoute,
            useValue: { snapshot: { queryParamMap: convertToParamMap(q) } },
          },
        ],
      });
    }

    it('says why the login of a merged account was refused', async () => {
      await withQuery({ loginError: 'account_merged' });
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Dieses Konto wurde zusammengeführt und ist gesperrt.',
      );
    });

    it('ignores an unknown reason', async () => {
      await withQuery({ loginError: 'anything' });
      expect(screen.queryByRole('alert')).toBeNull();
    });
  });
});
