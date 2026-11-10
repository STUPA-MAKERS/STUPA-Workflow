import { render, screen } from '@testing-library/angular';
import { MyApplicationsNoneComponent } from './my-applications-none.component';

describe('MyApplicationsNoneComponent', () => {
  afterEach(() => localStorage.clear());

  it('says that no Antrag is open', async () => {
    localStorage.setItem('ap.locale', 'de');
    await render(MyApplicationsNoneComponent);
    expect(screen.getByText('Kein Antrag geöffnet')).toBeInTheDocument();
  });
});
