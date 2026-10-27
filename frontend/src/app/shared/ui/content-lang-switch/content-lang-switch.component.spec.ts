import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { I18nService } from '@core/i18n/i18n.service';
import { runAxe } from '../../../../testing/a11y';
import { type ContentLang, ContentLangSwitchComponent } from './content-lang-switch.component';
import { ContentLangState } from './content-lang.state';

/** Give the service active extra languages, as the bundle of the server does. */
function withExtras(): void {
  const i18n = TestBed.inject(I18nService) as unknown as { _languages: { set(v: unknown): void } };
  i18n._languages.set([
    { code: 'fr', name: 'Français' },
    { code: 'pt-BR', name: 'Português' },
  ]);
}

describe('ContentLangSwitchComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.removeItem('ap.locale'));

  it('is a dropdown with the native names and binds the language both ways', async () => {
    const lang = signal<ContentLang>('de');
    const { container, fixture } = await render(
      `<app-content-lang-switch [(value)]="lang" ariaLabel="Sprache der Texte" />`,
      { imports: [ContentLangSwitchComponent], componentProperties: { lang } },
    );
    withExtras();
    fixture.detectChanges();
    expect(document.querySelector('select')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Sprache der Texte: Deutsch' }));
    expect(screen.getAllByRole('option').map((o) => o.textContent?.trim())).toEqual([
      'Deutsch',
      'English',
      'Français',
      'Português',
    ]);
    await userEvent.click(screen.getByRole('option', { name: 'Português' }));
    expect(lang()).toBe('pt-BR');
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Sprache der Texte: Português' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('falls back to German for an empty value', async () => {
    const { fixture } = await render(ContentLangSwitchComponent, {
      inputs: { ariaLabel: 'Sprache', value: 'en' },
    });
    const c = fixture.componentInstance as unknown as { pick(v: string | null): void; value(): ContentLang };
    c.pick(null);
    expect(c.value()).toBe('de');
  });

  it('the state of an editor starts with the language of the page', () => {
    TestBed.configureTestingModule({ providers: [ContentLangState] });
    expect(TestBed.inject(ContentLangState).lang()).toBe('de');
  });
});
