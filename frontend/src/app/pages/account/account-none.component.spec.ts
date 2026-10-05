import { render, screen } from '@testing-library/angular';
import { AccountNoneComponent } from './account-none.component';

describe('AccountNoneComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('says that no account page is open', async () => {
    await render(AccountNoneComponent);
    expect(screen.getByRole('heading', { name: 'Keine Seite geöffnet' })).toBeInTheDocument();
    expect(screen.getByText('Wähle links einen Bereich deines Kontos.')).toBeInTheDocument();
  });
});
