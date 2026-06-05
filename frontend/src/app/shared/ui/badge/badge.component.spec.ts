import { render, screen } from '@testing-library/angular';
import { BadgeComponent } from './badge.component';

describe('BadgeComponent', () => {
  it('renders content with the default neutral variant', async () => {
    await render(`<app-badge>Entwurf</app-badge>`, { imports: [BadgeComponent] });
    const badge = screen.getByText('Entwurf');
    expect(badge).toHaveClass('badge--neutral');
  });

  it('applies the requested variant class', async () => {
    await render(`<app-badge variant="success">Angenommen</app-badge>`, {
      imports: [BadgeComponent],
    });
    expect(screen.getByText('Angenommen')).toHaveClass('badge--success');
  });
});
