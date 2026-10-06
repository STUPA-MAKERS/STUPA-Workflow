import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { createLocationMock, provideLocationMock } from '../../../testing/location-mock';
import { LanguageSelectComponent } from './language-select.component';

async function setup(display: 'code' | 'name' = 'code') {
  const location = createLocationMock();
  await render(LanguageSelectComponent, {
    inputs: { label: 'Sprache', display },
    providers: [provideLocationMock(location)],
  });
  return { reload: location.reload };
}

describe('LanguageSelectComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.removeItem('ap.locale'));

  it('shows the code with a globe, and never a native select (D8)', async () => {
    await setup('code');
    expect(screen.getByRole('button', { name: 'Sprache: DE' })).toBeInTheDocument();
    expect(document.querySelector('select')).toBeNull();
  });

  it('shows the native name in the name mode', async () => {
    await setup('name');
    expect(screen.getByRole('button', { name: 'Sprache: Deutsch' })).toBeInTheDocument();
  });

  it('switches the language through the app list and reloads the view', async () => {
    const { reload } = await setup('code');
    await userEvent.click(screen.getByRole('button', { name: 'Sprache: DE' }));
    await userEvent.click(screen.getByRole('option', { name: 'English' }));
    expect(localStorage.getItem('ap.locale')).toBe('en');
    expect(reload).toHaveBeenCalled();
  });

  it('does nothing when the current language is chosen again', async () => {
    const { reload } = await setup('code');
    await userEvent.click(screen.getByRole('button', { name: 'Sprache: DE' }));
    await userEvent.click(screen.getByRole('option', { name: 'Deutsch' }));
    expect(reload).not.toHaveBeenCalled();
  });
});
