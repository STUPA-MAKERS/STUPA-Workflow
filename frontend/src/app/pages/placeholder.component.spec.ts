import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { PlaceholderComponent } from './placeholder.component';

describe('PlaceholderComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('renders the title key from route data and the localized badge/body', async () => {
    await render(PlaceholderComponent, {
      providers: [{ provide: ActivatedRoute, useValue: { data: of({ title: 'nav.budget' }) } }],
    });
    expect(screen.getByRole('heading', { name: 'Budget' })).toBeInTheDocument();
    expect(screen.getByText('In Arbeit')).toBeInTheDocument();
    expect(screen.getByText(/in einem späteren Task/)).toBeInTheDocument();
  });

  it('passes an unknown (non-key) title through unchanged', async () => {
    await render(PlaceholderComponent, {
      providers: [{ provide: ActivatedRoute, useValue: { data: of({ title: 'Budget' }) } }],
    });
    expect(screen.getByRole('heading', { name: 'Budget' })).toBeInTheDocument();
  });

  it('falls back to the localized default title when route data has none', async () => {
    await render(PlaceholderComponent, {
      providers: [{ provide: ActivatedRoute, useValue: { data: of({}) } }],
    });
    expect(screen.getByRole('heading', { name: 'Bereich' })).toBeInTheDocument();
  });

  it('localizes badge and fallback title in English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await render(PlaceholderComponent, {
      providers: [{ provide: ActivatedRoute, useValue: { data: of({}) } }],
    });
    expect(screen.getByRole('heading', { name: 'Section' })).toBeInTheDocument();
    expect(screen.getByText('In progress')).toBeInTheDocument();
  });
});
