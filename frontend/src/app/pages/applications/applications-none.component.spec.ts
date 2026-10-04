import { render, screen } from '@testing-library/angular';
import { ApplicationsNoneComponent } from './applications-none.component';

describe('ApplicationsNoneComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('says that no application is open', async () => {
    await render(ApplicationsNoneComponent);
    expect(screen.getByText('Kein Antrag geöffnet')).toBeInTheDocument();
  });
});
