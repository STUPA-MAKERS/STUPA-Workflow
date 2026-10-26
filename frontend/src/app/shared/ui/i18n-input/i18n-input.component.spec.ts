import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { I18nService } from '@core/i18n/i18n.service';
import type { I18nMap } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { I18nInputComponent } from './i18n-input.component';

/** Give the service one active extra language, as the bundle of the server does. */
function withFrench(): void {
  const i18n = TestBed.inject(I18nService) as unknown as { _languages: { set(v: unknown): void } };
  i18n._languages.set([{ code: 'fr', name: 'Français' }]);
}

describe('I18nInputComponent', () => {
  it('shows one field per language with the default label', async () => {
    const value = signal<I18nMap>({ de: 'Sitzung', en: 'Meeting' });
    const { container, fixture } = await render(`<app-i18n-input [(value)]="value" />`, {
      imports: [I18nInputComponent],
      componentProperties: { value },
    });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByLabelText('Bezeichnung (DE)')).toHaveValue('Sitzung');
    expect(screen.getByLabelText('Bezeichnung (EN)')).toHaveValue('Meeting');
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('adds a field for each active extra language and writes the map', async () => {
    const value = signal<I18nMap>({ de: 'Sitzung', en: 'Meeting' });
    const { fixture } = await render(`<app-i18n-input [(value)]="value" label="Titel" />`, {
      imports: [I18nInputComponent],
      componentProperties: { value },
    });
    withFrench();
    fixture.detectChanges();
    const fr = screen.getByLabelText('Titel (FR)');
    await userEvent.type(fr, 'Séance');
    expect(value()).toEqual({ de: 'Sitzung', en: 'Meeting', fr: 'Séance' });
    await userEvent.clear(fr);
    expect(value()).toEqual({ de: 'Sitzung', en: 'Meeting' });
    await userEvent.clear(screen.getByLabelText('Titel (EN)'));
    expect(value()).toEqual({ de: 'Sitzung', en: '' });
  });

  /**
   * The kit field names itself by its visible label; the accessible name is for a field without
   * one.
   */
  it('labels a short field with its code and puts the placeholder on German', async () => {
    await render(`<app-i18n-input [short]="true" label="Text" placeholder="Frage" />`, {
      imports: [I18nInputComponent],
    });
    expect(screen.getByRole('textbox', { name: 'DE' })).toHaveAttribute('placeholder', 'Frage');
    expect(screen.getByRole('textbox', { name: 'EN' })).not.toHaveAttribute('placeholder', 'Frage');
  });

  it('does not join a form of the page, so the fields need no name', async () => {
    await render(`<form><app-i18n-input [value]="{ de: 'a', en: 'b' }" /></form>`, {
      imports: [I18nInputComponent, (await import('@angular/forms')).FormsModule],
    });
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
  });
});
