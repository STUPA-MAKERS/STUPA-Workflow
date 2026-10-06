import { render, screen } from '@testing-library/angular';
import { VotingNoneComponent } from './voting-none.component';

describe('VotingNoneComponent', () => {
  it('shows only the empty sheet without the list page', async () => {
    const { container } = await render(VotingNoneComponent);
    expect(container.querySelector('.none')).toBeInTheDocument();
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
  });
});
