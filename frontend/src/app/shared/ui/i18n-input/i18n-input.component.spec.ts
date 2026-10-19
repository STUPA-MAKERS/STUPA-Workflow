import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { I18nInputComponent } from './i18n-input.component';

describe('I18nInputComponent', () => {
  it('shows the German and the English text with the default labels', async () => {
    const { container, fixture } = await render(`<app-i18n-input de="Sitzung" en="Meeting" />`, {
      imports: [I18nInputComponent],
    });
    await fixture.whenStable();
    fixture.detectChanges();
    const de = screen.getByLabelText('Bezeichnung (DE)');
    const en = screen.getByLabelText('Bezeichnung (EN)');
    expect(de).toHaveValue('Sitzung');
    expect(en).toHaveValue('Meeting');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('emits each language on its own', async () => {
    const deChange = jest.fn();
    const enChange = jest.fn();
    await render(`<app-i18n-input (deChange)="deChange($event)" (enChange)="enChange($event)" />`, {
      imports: [I18nInputComponent],
      componentProperties: { deChange, enChange },
    });
    await userEvent.type(screen.getByLabelText('Bezeichnung (DE)'), 'ab');
    expect(deChange).toHaveBeenLastCalledWith('ab');
    expect(enChange).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText('Bezeichnung (EN)'), 'x');
    expect(enChange).toHaveBeenLastCalledWith('x');
  });

  it('takes the labels and the placeholders of the page', async () => {
    await render(
      `<app-i18n-input deLabel="DE" enLabel="EN" deAriaLabel="Text deutsch" enAriaLabel="Text englisch" dePlaceholder="Frage" />`,
      { imports: [I18nInputComponent] },
    );
    // The kit field names itself by its visible label; the accessible name is for a field without one.
    expect(screen.getByRole('textbox', { name: 'DE' })).toHaveAttribute('placeholder', 'Frage');
    expect(screen.getByRole('textbox', { name: 'EN' })).not.toHaveAttribute('placeholder');
  });

  it('does not join a form of the page, so the fields need no name', async () => {
    await render(`<form><app-i18n-input de="a" en="b" /></form>`, {
      imports: [I18nInputComponent, (await import('@angular/forms')).FormsModule],
    });
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
  });
});
