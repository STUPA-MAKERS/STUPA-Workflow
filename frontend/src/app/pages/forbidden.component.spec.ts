import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { ForbiddenComponent } from './forbidden.component';

describe('ForbiddenComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the code, the heading, the reason and the way to the dashboard', async () => {
    await render(ForbiddenComponent, { providers: [provideRouter([])] });
    expect(screen.getByText('403')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Kein Zugriff' })).toBeInTheDocument();
    expect(
      screen.getByText('Für diesen Bereich fehlt dir die erforderliche Berechtigung.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Zum Dashboard' })).toHaveAttribute('href', '/dashboard');
  });

  it('marks the heading with the lock icon', async () => {
    const { container } = await render(ForbiddenComponent, { providers: [provideRouter([])] });
    expect(container.querySelector('app-icon.err__icon')).not.toBeNull();
  });
});
