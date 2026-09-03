import { signal } from '@angular/core';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { ApplyConfirmationComponent } from './apply-confirmation.component';

describe('ApplyConfirmationComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  async function setup(loggedIn = false) {
    return render(ApplyConfirmationComponent, {
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: { isAuthenticated: signal(loggedIn) } },
        {
          provide: ActivatedRoute,
          useValue: { queryParamMap: of(convertToParamMap({ id: 'app-77' })) },
        },
      ],
    });
  }

  it('asks to confirm the email, shows the 12h-discard note and reference id', async () => {
    await setup();
    expect(screen.getByText(/E-Mail bestätigen/)).toBeInTheDocument();
    expect(screen.getByText(/persönlichen Link/)).toBeInTheDocument();
    expect(screen.getByText(/nach 12 Stunden automatisch verworfen/)).toBeInTheDocument();
    expect(screen.getByText('app-77')).toBeInTheDocument();
  });

  it('renders the confirmation in English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getByText(/confirm your email/)).toBeInTheDocument();
    expect(screen.getByText(/personal link/)).toBeInTheDocument();
    expect(screen.getByText(/discarded after 12 hours/)).toBeInTheDocument();
    expect(screen.queryByText(/E-Mail bestätigen/)).not.toBeInTheDocument();
  });

  // The backend confirms the address of a signed-in submitter at creation time, so the
  // "confirm your email / discarded after 12 hours" copy is false for that caller.
  it('tells a signed-in submitter the application is submitted and links to the record', async () => {
    await setup(true);
    expect(screen.getByText('Antrag eingereicht')).toBeInTheDocument();
    expect(screen.getByText('Eingereicht')).toBeInTheDocument();
    expect(screen.queryByText(/E-Mail bestätigen/)).not.toBeInTheDocument();
    expect(screen.queryByText(/persönlichen Link/)).not.toBeInTheDocument();
    expect(screen.queryByText(/nach 12 Stunden automatisch verworfen/)).not.toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Antrag öffnen' });
    expect(link).toHaveAttribute('href', '/applications/app-77');
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
    expect(screen.getByText(/Fast geschafft – E-Mail bestätigen/)).toBeInTheDocument();
    expect(screen.getByText('Bestätigung ausstehend')).toBeInTheDocument();
    expect(screen.getByText(/nach 12 Stunden automatisch verworfen/)).toBeInTheDocument();
    expect(screen.queryByText('Antrag eingereicht')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Antrag öffnen' })).not.toBeInTheDocument();
  });
});
