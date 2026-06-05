import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ShellComponent } from './shell.component';
import { ThemeService } from '@core/theme/theme.service';
import { I18nService } from '@core/i18n/i18n.service';

async function setup() {
  return render(ShellComponent, {
    providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
  });
}

describe('ShellComponent', () => {
  beforeEach(() => localStorage.clear());

  it('renders the primary navigation links', async () => {
    await setup();
    expect(screen.getByRole('link', { name: /Dashboard/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Anträge/ })).toBeInTheDocument();
  });

  it('toggles the theme via the toggle button', async () => {
    const { fixture } = await setup();
    const theme = fixture.debugElement.injector.get(ThemeService);
    const before = theme.resolved();
    await userEvent.click(screen.getByRole('button', { name: /Erscheinungsbild|appearance/ }));
    expect(theme.resolved()).not.toBe(before);
  });

  it('switches locale through the language selector', async () => {
    const { fixture } = await setup();
    const i18n = fixture.debugElement.injector.get(I18nService);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'en');
    expect(i18n.locale()).toBe('en');
  });
});
