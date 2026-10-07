import { signal } from '@angular/core';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { of, throwError, type Observable } from 'rxjs';
import type {
  PublicProtocolPage,
  PublicProtocolSummary,
} from '../features/public-protocols/public-protocols.models';
import { PublicProtocolsService } from '../features/public-protocols/public-protocols.service';
import { HomeComponent } from './home.component';

const EMPTY: PublicProtocolPage = { items: [], total: 0, limit: 3, offset: 0 };

function summary(over: Partial<PublicProtocolSummary> = {}): PublicProtocolSummary {
  return {
    id: 'p-1',
    title: '34. Sitzung des Studierendenparlaments',
    date: '2026-09-29',
    semester: 'ss-2026',
    finalizedAt: '2026-10-02T10:00:00Z',
    gremium: { id: 'g-1', name: 'Studierendenparlament', slug: 'stupa' },
    tops: [
      { number: 1, title: 'Begrüßung', nonPublic: false, results: [] },
      { number: 2, title: null, nonPublic: true, results: [] },
      { number: 3, title: 'Haushalt', nonPublic: false, results: ['passed'] },
    ],
    hasPdf: true,
    pdfSize: 1000,
    ...over,
  };
}

function protocolsApi(reply: Observable<PublicProtocolPage> = of(EMPTY)) {
  return { list: jest.fn(() => reply) };
}

function setup(
  auth: { login: jest.Mock } = { login: jest.fn() },
  freetexts: Record<string, Record<string, string>> = {},
  protocols = protocolsApi(),
) {
  return render(HomeComponent, {
    providers: [
      provideRouter([]),
      { provide: AuthService, useValue: auth },
      { provide: BrandingService, useValue: { freetexts: signal(freetexts) } },
      { provide: PublicProtocolsService, useValue: protocols },
    ],
  }).then((view) => ({ ...view, auth, protocols }));
}

describe('HomeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('offers exactly two ways in and nothing else without public protocols', async () => {
    const { protocols } = await setup();
    expect(protocols.list).toHaveBeenCalledWith({ limit: 3 });
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
          { provide: PublicProtocolsService, useValue: protocolsApi() },
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

  describe('public protocols', () => {
    it('adds the protocol card and the strip of the newest protocols', async () => {
      const page: PublicProtocolPage = {
        items: [summary(), summary({ id: 'p-2', title: '6. Sitzung der Fachschaft' })],
        total: 23,
        limit: 3,
        offset: 0,
      };
      await setup(undefined, {}, protocolsApi(of(page)));
      expect(screen.getByRole('link', { name: /^Protokolle/ })).toHaveAttribute('href', '/protokolle');
      expect(screen.getByRole('heading', { name: 'Zuletzt veröffentlicht' })).toBeInTheDocument();
      const first = screen.getByRole('link', { name: /34\. Sitzung des Studierendenparlaments/ });
      expect(first).toHaveAttribute('href', '/protokolle/p-1');
      // Two of the three agenda items are public.
      expect(first).toHaveTextContent('Studierendenparlament · 2 öffentliche TOPs');
      expect(screen.getByRole('link', { name: /Alle 23 Protokolle/ })).toHaveAttribute(
        'href',
        '/protokolle',
      );
      // The login stays.
      expect(screen.getByRole('button', { name: /Gremiumsmitglied anmelden/ })).toBeInTheDocument();
    });

    it('looks as before when the protocols cannot load', async () => {
      await setup(undefined, {}, protocolsApi(throwError(() => new Error('down'))));
      expect(screen.queryByText('Zuletzt veröffentlicht')).toBeNull();
      expect(screen.getAllByRole('link')).toHaveLength(1);
    });
  });
});
