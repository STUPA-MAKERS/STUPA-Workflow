import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { LoadMoreComponent } from './load-more.component';

describe('LoadMoreComponent', () => {
  it('loads the next page from its button', async () => {
    const more = jest.fn();
    const { container } = await render(`<app-load-more label="Mehr laden" (more)="more()" />`, {
      imports: [LoadMoreComponent],
      componentProperties: { more },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Mehr laden' }));
    expect(more).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.lm__sentinel')).toHaveAttribute('aria-hidden', 'true');
  });
});
