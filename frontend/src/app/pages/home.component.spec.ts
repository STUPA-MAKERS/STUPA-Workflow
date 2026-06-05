import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { HomeComponent } from './home.component';

describe('HomeComponent', () => {
  it('renders the hero heading and a call-to-action linking to /apply', async () => {
    await render(HomeComponent, { providers: [provideRouter([])] });
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    const cta = screen.getByRole('link', { name: /Antrag/ });
    expect(cta).toHaveAttribute('href', '/apply');
  });
});
