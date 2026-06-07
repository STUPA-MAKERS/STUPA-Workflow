import { of } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { FormFieldDef } from '@core/api/models';
import { AdminApiService } from '../admin-api.service';
import { FormBuilderComponent } from './form-builder.component';

async function setup() {
  const createFormVersion = jest.fn(() => of({ id: 'fv1' }));
  const api = { createFormVersion };
  const view = await render(FormBuilderComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, createFormVersion };
}

describe('FormBuilderComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('starts empty and disables save', async () => {
    await setup();
    expect(screen.getByText('Noch keine Felder. Füge ein erstes Feld hinzu.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Als Form-Version speichern' })).toBeDisabled();
  });

  it('builds a valid field and saves a normalized FormFieldDef', async () => {
    const { createFormVersion } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Feld hinzufügen' }));

    const key = screen.getByRole('textbox', { name: 'Schlüssel' });
    await userEvent.type(key, 'title');
    const labelDe = screen.getAllByRole('textbox', { name: 'Bezeichnung (DE)' })[0];
    await userEvent.type(labelDe, 'Titel');

    const save = screen.getByRole('button', { name: 'Als Form-Version speichern' });
    expect(save).toBeEnabled();
    await userEvent.click(save);

    expect(createFormVersion).toHaveBeenCalledTimes(1);
    const fields = createFormVersion.mock.calls[0][1] as FormFieldDef[];
    expect(fields).toEqual([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }]);
  });

  it('flags a select field with no usable options as invalid', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Feld hinzufügen' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Schlüssel' }), 'choice');
    await userEvent.type(screen.getAllByRole('textbox', { name: 'Bezeichnung (DE)' })[0], 'Auswahl');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Typ' }), 'select');
    // blank option (value '' / label '') ⇒ still valid per schema (options present),
    // but removing it leaves no options ⇒ invalid.
    const optionBlock = screen.getByRole('group', { name: 'Auswahloptionen' });
    await userEvent.click(within(optionBlock).getByRole('button', { name: 'Entfernen' }));
    expect(screen.getByText("options are required for type 'select'")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Als Form-Version speichern' })).toBeDisabled();
  });

  it('warns on duplicate field keys', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Feld hinzufügen' }));
    await userEvent.click(screen.getByRole('button', { name: 'Feld hinzufügen' }));
    const keys = screen.getAllByRole('textbox', { name: 'Schlüssel' });
    await userEvent.type(keys[0], 'dup');
    await userEvent.type(keys[1], 'dup');
    expect(screen.getByText(/Doppelte Feld-Schlüssel: dup/)).toBeInTheDocument();
  });

  it('exercises field/option/logic/validation mutators', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;

    c.addField();
    c.addField();
    c.move(0, -1); // out of bounds → no-op
    c.move(0, 1); // swap
    expect(c.fields()).toHaveLength(2);

    c.onTypeChange(0, 'select');
    c.addOption(0);
    expect(c.fields()[0].options.length).toBeGreaterThan(1);
    c.removeOption(0, 0);
    c.onTypeChange(0, 'computed');
    expect(c.fields()[0].compute).toBeDefined();

    c.onLogicInput(0, 'visibleIf', '{bad json');
    c.onLogicInput(0, 'visibleIf', '{"var":"x"}');
    expect(c.fields()[0].visibleIf).toEqual({ var: 'x' });
    c.onLogicInput(0, 'visibleIf', '');
    expect(c.fields()[0].visibleIf).toBeUndefined();
    expect(c.logicRaw(0, 'compute', { var: 'y' })).toBe('{"var":"y"}');

    c.setVal(0, 'min', '5');
    expect(c.fields()[0].validation.min).toBe(5);
    c.setVal(0, 'min', '');
    c.setVal(0, 'pattern', '^x$');

    c.removeField(1);
    expect(c.fields()).toHaveLength(1);

    c.save(); // computed field has compute set but key empty → invalid → error path
  });
});
