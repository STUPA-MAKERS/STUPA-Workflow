import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { NotFoundComponent } from './not-found.component';

describe('NotFoundComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the code, the heading, the reason and the way to the start page', async () => {
    await render(NotFoundComponent, { providers: [provideRouter([])] });
    expect(screen.getByText('404')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Seite nicht gefunden' })).toBeInTheDocument();
    expect(screen.getByText('Die angeforderte Seite existiert nicht.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Zur Startseite' })).toHaveAttribute('href', '/');
  });

  it('hides the bare code from screen readers, which read the heading instead', async () => {
    await render(NotFoundComponent, { providers: [provideRouter([])] });
    expect(screen.getByText('404')).toHaveAttribute('aria-hidden', 'true');
  });
});
