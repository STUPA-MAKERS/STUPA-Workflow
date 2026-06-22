import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { HomeComponent } from './home.component';

describe('HomeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('renders the apply heading and a call-to-action linking to /apply', async () => {
    await render(HomeComponent, { providers: [provideRouter([])] });
    expect(
      screen.getByRole('heading', { level: 1, name: 'Antrag stellen' }),
    ).toBeInTheDocument();
    const cta = screen.getByRole('link', { name: /Antrag/ });
    expect(cta).toHaveAttribute('href', '/apply');
  });

  it('shows the returning-applicant magic-link note and no feature cards', async () => {
    await render(HomeComponent, { providers: [provideRouter([])] });
    expect(screen.getByText(/Bestätigungs-E-Mail/)).toBeInTheDocument();
    // Die früheren Marketing-Karten (Anträge/Live-Vote/Budget) sind entfernt.
    expect(screen.queryByRole('heading', { name: 'Live-Vote' })).not.toBeInTheDocument();
  });

  it('localizes the heading and the note to English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await render(HomeComponent, { providers: [provideRouter([])] });
    expect(
      screen.getByRole('heading', { level: 1, name: 'Submit an application' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/confirmation email/)).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { level: 1, name: 'Antrag stellen' }),
    ).not.toBeInTheDocument();
  });
});
