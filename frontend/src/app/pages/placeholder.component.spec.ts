import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { PlaceholderComponent } from './placeholder.component';

describe('PlaceholderComponent', () => {
  it('renders the title from route data', async () => {
    await render(PlaceholderComponent, {
      providers: [{ provide: ActivatedRoute, useValue: { data: of({ title: 'Budget' }) } }],
    });
    expect(screen.getByRole('heading', { name: 'Budget' })).toBeInTheDocument();
    expect(screen.getByText('In Arbeit')).toBeInTheDocument();
  });

  it('falls back to the default title when route data has none', async () => {
    await render(PlaceholderComponent, {
      providers: [{ provide: ActivatedRoute, useValue: { data: of({}) } }],
    });
    expect(screen.getByRole('heading', { name: 'Bereich' })).toBeInTheDocument();
  });
});
