import { signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { I18nMap } from '@core/api/models';
import { ContentLangState } from '@shared/ui/content-lang-switch/content-lang.state';
import { runAxe } from '../../../../testing/a11y';
import { I18nInputComponent } from './i18n-input.component';

/** A content language state that the spec sets. */
function stateFor(lang: string): ContentLangState {
  return { lang: signal(lang) } as unknown as ContentLangState;
}

describe('I18nInputComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.removeItem('ap.locale'));

  it('shows the German text without a content language state', async () => {
    const value = signal<I18nMap>({ de: 'Sitzung', en: 'Meeting' });
    const { container, fixture } = await render(`<app-i18n-input [(value)]="value" placeholder="Frage" />`, {
      imports: [I18nInputComponent],
      componentProperties: { value },
    });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
    expect(screen.getByLabelText('Bezeichnung (DE)')).toHaveValue('Sitzung');
    expect(screen.getByLabelText('Bezeichnung (DE)')).toHaveAttribute('placeholder', 'Frage');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the language of the editor, with the fallback text as placeholder', async () => {
    const state = stateFor('fr');
    const value = signal<I18nMap>({ de: 'Sitzung', en: 'Meeting' });
    const { fixture } = await render(`<app-i18n-input [(value)]="value" label="Titel" />`, {
      imports: [I18nInputComponent],
      componentProperties: { value },
      providers: [{ provide: ContentLangState, useValue: state }],
    });
    const fr = screen.getByLabelText('Titel (FR)');
    expect(fr).toHaveValue('');
    expect(fr).toHaveAttribute('placeholder', 'Meeting');
    await userEvent.type(fr, 'Séance');
    expect(value()).toEqual({ de: 'Sitzung', en: 'Meeting', fr: 'Séance' });
    await userEvent.clear(fr);
    expect(value()).toEqual({ de: 'Sitzung', en: 'Meeting' });

    state.lang.set('en');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const en = screen.getByLabelText('Titel (EN)');
    expect(en).toHaveValue('Meeting');
    await userEvent.clear(en);
    expect(value()).toEqual({ de: 'Sitzung', en: '' });
    expect(en).toHaveAttribute('placeholder', 'Sitzung');
  });

  /**
   * The kit field names itself by its visible label; the accessible name is for a field without
   * one.
   */
  it('labels a short field with its code', async () => {
    await render(`<app-i18n-input [short]="true" label="Text" />`, {
      imports: [I18nInputComponent],
      providers: [{ provide: ContentLangState, useValue: stateFor('en') }],
    });
    expect(screen.getByRole('textbox', { name: 'EN' })).toBeInTheDocument();
  });

  it('does not join a form of the page, so the field needs no name', async () => {
    await render(`<form><app-i18n-input [value]="{ de: 'a', en: 'b' }" /></form>`, {
      imports: [I18nInputComponent, (await import('@angular/forms')).FormsModule],
    });
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
  });
});
