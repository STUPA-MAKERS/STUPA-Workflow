import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { NotFoundComponent } from './not-found.component';

describe('NotFoundComponent', () => {
  it('shows the 404 heading and a back link', async () => {
    await render(NotFoundComponent, { providers: [provideRouter([])] });
    expect(screen.getByText('404')).toBeInTheDocument();
    expect(screen.getByRole('link')).toHaveAttribute('href', '/');
  });
});
