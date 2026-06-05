import { render, screen } from '@testing-library/angular';
import { I18nService } from './i18n.service';
import { TranslatePipe } from './translate.pipe';

describe('TranslatePipe', () => {
  it('renders the active-locale translation and reacts to switches', async () => {
    const { fixture } = await render(`<span>{{ 'action.login' | t }}</span>`, {
      imports: [TranslatePipe],
    });
    const i18n = fixture.debugElement.injector.get(I18nService);
    i18n.setLocale('de');
    fixture.detectChanges();
    expect(screen.getByText('Anmelden')).toBeInTheDocument();

    i18n.setLocale('en');
    fixture.detectChanges();
    expect(screen.getByText('Sign in')).toBeInTheDocument();
  });
});
