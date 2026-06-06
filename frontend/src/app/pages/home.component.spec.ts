import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { HomeComponent } from './home.component';

describe('HomeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('renders the hero heading and a call-to-action linking to /apply', async () => {
    await render(HomeComponent, { providers: [provideRouter([])] });
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    const cta = screen.getByRole('link', { name: /Antrag/ });
    expect(cta).toHaveAttribute('href', '/apply');
  });

  it('renders localized card headings (DE) instead of hardcoded text', async () => {
    await render(HomeComponent, { providers: [provideRouter([])] });
    expect(screen.getByRole('heading', { name: 'Anträge' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Live-Vote' })).toBeInTheDocument();
  });

  it('switches the card headings to English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await render(HomeComponent, { providers: [provideRouter([])] });
    expect(screen.getByRole('heading', { name: 'Applications' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Live vote' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Anträge' })).not.toBeInTheDocument();
  });
});
