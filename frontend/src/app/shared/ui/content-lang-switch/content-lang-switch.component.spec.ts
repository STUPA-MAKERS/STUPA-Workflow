import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { I18nService } from '@core/i18n/i18n.service';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { type ContentLang, ContentLangSwitchComponent } from './content-lang-switch.component';

describe('ContentLangSwitchComponent', () => {
  it('shows DE and EN and binds the language both ways', async () => {
    const lang = signal<ContentLang>('de');
    const { container } = await render(
      `<app-content-lang-switch [(value)]="lang" ariaLabel="Sprache der Texte" />`,
      { imports: [ContentLangSwitchComponent], componentProperties: { lang } },
    );
    expect(screen.getByRole('radiogroup', { name: 'Sprache der Texte' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'DE' })).toBeChecked();
    await userEvent.click(screen.getByRole('radio', { name: 'EN' }));
    expect(lang()).toBe('en');
    await userEvent.click(screen.getByRole('radio', { name: 'DE' }));
    expect(lang()).toBe('de');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('lists the active extra languages after DE and EN', async () => {
    const lang = signal<ContentLang>('de');
    const { fixture } = await render(`<app-content-lang-switch [(value)]="lang" ariaLabel="Sprache" />`, {
      imports: [ContentLangSwitchComponent],
      componentProperties: { lang },
    });
    const i18n = TestBed.inject(I18nService) as unknown as { _languages: { set(v: unknown): void } };
    i18n._languages.set([{ code: 'pt-BR', name: 'Português' }]);
    fixture.detectChanges();
    expect(screen.getAllByRole('radio').map((r) => r.textContent?.trim())).toEqual(['DE', 'EN', 'PT-BR']);
    await userEvent.click(screen.getByRole('radio', { name: 'PT-BR' }));
    expect(lang()).toBe('pt-BR');
  });

  it('falls back to German for an empty value', async () => {
    const { fixture } = await render(ContentLangSwitchComponent, {
      inputs: { ariaLabel: 'Sprache', value: 'en' },
    });
    const c = fixture.componentInstance as unknown as { pick(v: string | null): void; value(): ContentLang };
    c.pick(null);
    expect(c.value()).toBe('de');
  });
});
