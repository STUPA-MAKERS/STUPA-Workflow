import { render, screen } from '@testing-library/angular';
import { CardComponent } from './card.component';

describe('CardComponent', () => {
  it('renders heading and projected body', async () => {
    await render(`<app-card heading="Antrag"><p>Inhalt</p></app-card>`, {
      imports: [CardComponent],
    });
    expect(screen.getByRole('heading', { name: 'Antrag' })).toBeInTheDocument();
    expect(screen.getByText('Inhalt')).toBeInTheDocument();
  });

  it('omits the title when no heading is given', async () => {
    await render(`<app-card><p>Nur Body</p></app-card>`, { imports: [CardComponent] });
    expect(screen.queryByRole('heading')).toBeNull();
  });
});
