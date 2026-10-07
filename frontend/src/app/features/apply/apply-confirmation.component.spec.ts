import { signal } from '@angular/core';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService, type FreeTexts } from '@core/branding/branding.service';
import { ApplyConfirmationComponent } from './apply-confirmation.component';

const FULL_ID = '1195a615-3a71-4cfe-9ae0-3ba0c2c4b7e9';
const SHORT_REF = '1195A615';

describe('ApplyConfirmationComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  async function setup(
    loggedIn = false,
    id: string | null = FULL_ID,
    hours?: number,
    linkDays: number | null = null,
    freetexts: FreeTexts = {},
  ) {
    return render(ApplyConfirmationComponent, {
      providers: [
        provideRouter([]),
        ...(hours === undefined
          ? []
          : [
              {
                provide: BrandingService,
                useValue: {
                  confirmTtlHours: signal(hours),
                  linkTtlDays: signal(linkDays),
                  loaded: signal(true),
                  freetexts: signal(freetexts),
                },
              },
            ]),
        { provide: AuthService, useValue: { isAuthenticated: signal(loggedIn) } },
        {
          provide: ActivatedRoute,
          useValue: {
            queryParamMap: of(convertToParamMap(id === null ? {} : { id })),
          },
        },
      ],
    });
  }

  it('asks to confirm the email, shows the 12h-discard note and reference id', async () => {
    await setup();
    expect(screen.getByText(/E\u2011Mail bestätigen/)).toBeInTheDocument();
    expect(screen.getByText(/persönlichen Link/)).toBeInTheDocument();
    expect(screen.getByText(/nach 12 Stunden automatisch verworfen/)).toBeInTheDocument();
    expect(screen.getByText(SHORT_REF)).toBeInTheDocument();
  });

  it('renders the confirmation in English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getByText(/confirm your email/)).toBeInTheDocument();
    expect(screen.getByText(/personal link/)).toBeInTheDocument();
    expect(screen.getByText(/discarded after 12 hours/)).toBeInTheDocument();
    expect(screen.queryByText(/E\u2011Mail bestätigen/)).not.toBeInTheDocument();
  });

  // The backend confirms the address of a signed-in submitter at creation time, so the
  // "confirm your email / discarded after 12 hours" copy is false for that caller.
  it('tells a signed-in submitter the application is submitted and links to the record', async () => {
    await setup(true);
    expect(screen.getByText('Antrag eingereicht')).toBeInTheDocument();
    expect(screen.getByText('Eingereicht')).toBeInTheDocument();
    expect(screen.queryByText(/E\u2011Mail bestätigen/)).not.toBeInTheDocument();
    expect(screen.queryByText(/persönlichen Link/)).not.toBeInTheDocument();
    expect(screen.queryByText(/nach 12 Stunden automatisch verworfen/)).not.toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Antrag öffnen' });
    expect(link).toHaveAttribute('href', `/applications/${FULL_ID}`);
  });

  it('shows the signed-in state in English too', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup(true);
    expect(screen.getByText('Application submitted')).toBeInTheDocument();
    expect(screen.queryByText(/confirm your email/)).not.toBeInTheDocument();
    expect(screen.queryByText(/discarded after 12 hours/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the application' })).toBeInTheDocument();
  });

  it('keeps the anonymous copy and shows no record link when nobody is signed in', async () => {
    await setup(false);
    expect(screen.getByText(/Fast geschafft – E\u2011Mail bestätigen/)).toBeInTheDocument();
    expect(screen.getByText('Bestätigung ausstehend')).toBeInTheDocument();
    expect(screen.getByText(/nach 12 Stunden automatisch verworfen/)).toBeInTheDocument();
    expect(screen.queryByText('Antrag eingereicht')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Antrag öffnen' })).not.toBeInTheDocument();
  });

  // A 36-character UUID is unreadable and [[no-uuids-in-ui]] forbids it on screen. The
  // applicant reads or writes down the short prefix; the full id stays in the URL, in
  // the record link and in the magic-link email.
  it('shortens the anonymous reference to an 8-character uppercase prefix', async () => {
    await setup(false);
    expect(screen.getByText(SHORT_REF)).toBeInTheDocument();
    expect(screen.queryByText(FULL_ID)).not.toBeInTheDocument();
    expect(screen.queryByText(/1195a615-3a71/)).not.toBeInTheDocument();
  });

  it('shortens the signed-in reference but keeps the full id in the record link', async () => {
    await setup(true);
    expect(screen.getByText(SHORT_REF)).toBeInTheDocument();
    expect(screen.queryByText(FULL_ID)).not.toBeInTheDocument();
    expect(screen.queryByText(/1195a615-3a71/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Antrag öffnen' })).toHaveAttribute(
      'href',
      `/applications/${FULL_ID}`,
    );
  });

  it('shows an id shorter than 8 characters as it is', async () => {
    await setup(false, 'ab12');
    expect(screen.getByText('AB12')).toBeInTheDocument();
  });

  // The admin sets the confirmation window; the public site config carries it.
  it('shows the configured confirmation window instead of the default', async () => {
    await setup(false, FULL_ID, 48);
    expect(screen.getByText(/nach 48 Stunden automatisch verworfen/)).toBeInTheDocument();
    expect(screen.queryByText(/nach 12 Stunden/)).not.toBeInTheDocument();
  });

  it('says that the link does not expire when the loaded config has no lifetime', async () => {
    await setup(false, FULL_ID, 12, null);
    expect(screen.getByText('Der Link in der E-Mail ist unbegrenzt gültig.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Zur Startseite' })).toHaveAttribute('href', '/');
  });

  it('names no lifetime of the link before the config loaded', async () => {
    await setup();
    expect(screen.queryByText(/unbegrenzt/)).toBeNull();
    expect(screen.queryByText(/Tage gültig/)).toBeNull();
  });

  it('names the configured lifetime of the link', async () => {
    await setup(false, FULL_ID, 12, 30);
    expect(screen.getByText('Der Link in der E-Mail ist 30 Tage gültig.')).toBeInTheDocument();
    expect(screen.queryByText(/unbegrenzt/)).toBeNull();
  });

  it('shows the status as text and the heading as a level-1 heading', async () => {
    await setup();
    expect(screen.getByRole('heading', { level: 1, name: /E\u2011Mail bestätigen/ })).toBeInTheDocument();
    expect(screen.getByText('Bestätigung ausstehend').tagName).toBe('APP-STATUS-TEXT');
  });

  it('hides the reference line and the record link when the query has no id', async () => {
    await setup(true, null);
    expect(screen.queryByText(/Vorgangsnummer/)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Antrag öffnen' })).toBeNull();
  });

  describe('texts from /admin/branding', () => {
    const TEXTS: FreeTexts = {
      submittedInternal: { de: 'Danke, **intern**.', en: 'Thanks, *internal*.' },
      submittedExternal: { de: 'Bitte [Link](https://x.de) öffnen.\n\n<img src=x onerror=alert(1)>' },
    };

    it('shows the configured internal text as Markdown', async () => {
      const { container } = await setup(true, FULL_ID, 12, null, TEXTS);
      const text = container.querySelector('[data-testid="submitted-text"]') as HTMLElement;
      expect(text.innerHTML).toContain('<strong>intern</strong>');
      expect(screen.queryByText(/E-Mail-Adresse ist über dein Konto/)).toBeNull();
    });

    it('shows the configured external text and never renders raw HTML', async () => {
      const { container } = await setup(false, FULL_ID, 12, null, TEXTS);
      const text = container.querySelector('[data-testid="submitted-text"]') as HTMLElement;
      expect(screen.getByRole('link', { name: 'Link' })).toHaveAttribute('href', 'https://x.de');
      expect(text.querySelector('img')).toBeNull();
      expect(text.textContent).toContain('<img src=x onerror=alert(1)>');
      expect(screen.queryByText(/persönlichen Link/)).toBeNull();
    });

    it('takes the text of the page language', async () => {
      localStorage.setItem('ap.locale', 'en');
      const { container } = await setup(true, FULL_ID, 12, null, TEXTS);
      const text = container.querySelector('[data-testid="submitted-text"]') as HTMLElement;
      expect(text.innerHTML).toContain('<em>internal</em>');
    });

    it('falls back to the built-in text when the language has no text', async () => {
      localStorage.setItem('ap.locale', 'en');
      await setup(false, FULL_ID, 12, null, TEXTS);
      expect(screen.getByText(/personal link/)).toBeInTheDocument();
    });

    it('falls back to the built-in text when the text is blank', async () => {
      await setup(true, FULL_ID, 12, null, { submittedInternal: { de: '   ' } });
      expect(screen.getByText(/E-Mail-Adresse ist über dein Konto/)).toBeInTheDocument();
    });
  });

  it('hides the reference line when the query has no id', async () => {
    await setup(false, null);
    expect(screen.getByText(/Fast geschafft – E\u2011Mail bestätigen/)).toBeInTheDocument();
    expect(screen.queryByText(/Vorgangsnummer/)).not.toBeInTheDocument();
  });
});
