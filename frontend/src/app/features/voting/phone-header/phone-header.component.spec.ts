import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { VotePhoneHeaderComponent } from './phone-header.component';

describe('VotePhoneHeaderComponent', () => {
  it('shows the way back, the title and the meeting line', async () => {
    await render(VotePhoneHeaderComponent, {
      providers: [provideRouter([])],
      inputs: { back: ['/meetings', 'm1'], subtitle: 'TOP 3 · 34. Sitzung' },
    });
    expect(screen.getByRole('link', { name: 'Zurück' })).toHaveAttribute('href', '/meetings/m1');
    expect(screen.getByText('Abstimmung')).toBeInTheDocument();
    expect(screen.getByText('TOP 3 · 34. Sitzung')).toHaveAttribute('title', 'TOP 3 · 34. Sitzung');
  });

  it('leaves the line out without a meeting', async () => {
    const { container } = await render(VotePhoneHeaderComponent, {
      providers: [provideRouter([])],
      inputs: { back: '/voting' },
    });
    expect(container.querySelector('.ph__sub')).toBeNull();
  });
});
