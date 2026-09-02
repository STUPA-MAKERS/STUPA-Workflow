import { render, screen } from '@testing-library/angular';
import { EmptyStateComponent } from './empty-state.component';

describe('EmptyStateComponent', () => {
  it('shows the heading as the page heading', async () => {
    await render(EmptyStateComponent, {
      inputs: { heading: 'Antrag nicht gefunden' },
    });
    expect(
      screen.getByRole('heading', { level: 1, name: 'Antrag nicht gefunden' }),
    ).toBeInTheDocument();
  });

  it('omits the body when there is nothing useful to add', async () => {
    const { container } = await render(EmptyStateComponent, {
      inputs: { heading: 'Nichts da' },
    });
    expect(container.querySelector('.es__body')).toBeNull();
  });

  it('shows a code instead of the icon when one is given', async () => {
    const { container } = await render(EmptyStateComponent, {
      inputs: { heading: 'Seite nicht gefunden', code: '404' },
    });
    expect(screen.getByText('404')).toBeInTheDocument();
    // The code replaces the glyph rather than sitting next to it.
    expect(container.querySelector('.es__icon')).toBeNull();
  });

  it('falls back to the icon when there is no code', async () => {
    const { container } = await render(EmptyStateComponent, {
      inputs: { heading: 'Leer' },
    });
    expect(container.querySelector('.es__icon')).toBeTruthy();
  });
});
