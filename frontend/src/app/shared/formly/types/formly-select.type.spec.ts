import { Component } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { de } from '@core/i18n/translations';
import { provideFormly } from '../formly.providers';
import { FormlySelectType } from './formly-select.type';

@Component({
  standalone: true,
  imports: [ReactiveFormsModule, FormlyForm],
  template: `<formly-form [form]="form" [fields]="fields" [model]="model" />`,
})
class HostComponent {
  form = new FormGroup({});
  model: Record<string, unknown> = {};
  fields: FormlyFieldConfig[] = [];
}

async function renderField(
  field: FormlyFieldConfig,
  model: Record<string, unknown> = {},
): Promise<{ host: HostComponent }> {
  const { fixture } = await render(HostComponent, {
    providers: [provideFormly()],
    componentProperties: { fields: [field], model },
  });
  return { host: fixture.componentInstance };
}

/** Let the list render: it opens after one task. */
async function settle(): Promise<void> {
  await new Promise((r) => setTimeout(r));
}

/** Open the select field named `name` and choose the option `option`. */
async function pick(name: RegExp, option: string): Promise<void> {
  await userEvent.click(screen.getByRole('combobox', { name }));
  await settle();
  await userEvent.click(screen.getByRole('option', { name: option }));
}

function makeType(field: Partial<FormlyFieldConfig> & { showError?: boolean }): FormlySelectType {
  const cmp = new FormlySelectType();
  const showError = field.showError ?? false;
  cmp.field = {
    ...field,
    options: { showError: () => showError },
  } as unknown as FormlySelectType['field'];
  return cmp;
}

describe('FormlySelectType (rendered)', () => {
  it('renders options and updates the model', async () => {
    const { host } = await renderField({
      key: 'cat',
      type: 'select',
      props: {
        label: 'Kategorie',
        options: [
          { value: 'a', label: 'Alpha' },
          { value: 'b', label: 'Beta' },
        ],
      },
    });
    expect(document.querySelector('select')).toBeNull();
    await pick(/Kategorie/, 'Beta');
    expect(host.model['cat']).toBe('b');
  });

  it('renders the required marker and the default prompt, with no row to clear', async () => {
    // Formly defaults props.placeholder to '': the field shows the default prompt.
    const { host } = await renderField(
      {
        key: 'c',
        type: 'select',
        props: { label: 'Pflicht', required: true, options: [{ value: 'a', label: 'Alpha' }] },
      },
      { c: 'a' },
    );
    expect(screen.getByText('*')).toBeInTheDocument();
    const field = screen.getByRole('combobox', { name: 'Pflicht' });
    expect(field).toHaveAttribute('aria-required', 'true');
    await userEvent.click(field);
    await settle();
    const list = screen.getByRole('listbox');
    expect(within(list).getAllByRole('option').map((o) => o.textContent?.trim())).toEqual([
      'Alpha',
    ]);
    expect(host.model['c']).toBe('a');
  });

  it('shows the default prompt in the field while no option is chosen', async () => {
    await renderField({
      key: 'c',
      type: 'select',
      props: { label: 'Leer', options: [{ value: 'a', label: 'Alpha' }] },
    });
    expect(screen.getByRole('combobox', { name: 'Leer' })).toHaveTextContent(
      de['formly.select.placeholder'],
    );
    await userEvent.click(screen.getByRole('combobox', { name: 'Leer' }));
    await settle();
    expect(screen.queryByRole('option', { name: de['formly.select.placeholder'] })).toBeNull();
  });

  it('falls back to the default prompt when placeholder is genuinely undefined', async () => {
    // Render the type directly, without the formly prop init, so props.placeholder
    // stays undefined and the default-placeholder fallback of the template fires.
    await render(FormlySelectType, {
      componentInputs: {
        field: {
          formControl: new FormControl(''),
          props: { label: 'P', options: [] },
          options: { showError: () => false },
        } as never,
      },
    });
    expect(screen.getByRole('combobox')).toHaveTextContent(de['formly.select.placeholder']);
  });

  it('uses a custom placeholder when provided', async () => {
    await renderField({
      key: 'c',
      type: 'select',
      props: { label: 'P', placeholder: 'Auswahl treffen', options: [] },
    });
    expect(screen.getByRole('combobox')).toHaveTextContent('Auswahl treffen');
  });

  it('shows the hint when there is a description and no error', async () => {
    await renderField({
      key: 'c',
      type: 'select',
      props: { label: 'Mit Hinweis', description: 'Pflichtwahl.', options: [] },
    });
    expect(screen.getByText('Pflichtwahl.')).toBeInTheDocument();
    expect(screen.getByLabelText(/Mit Hinweis/).getAttribute('aria-describedby')).toMatch(/-hint$/);
  });

  it('shows the default error message and aria when invalid (validation.show)', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'c',
            type: 'select',
            props: { label: 'Err', required: true, description: 'desc', options: [] },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(de['formly.select.error']);
    const sel = screen.getByLabelText(/Err/);
    expect(sel.getAttribute('aria-invalid')).toBe('true');
    expect(sel.getAttribute('aria-describedby')).toMatch(/-error$/);
    expect(screen.queryByText('desc')).not.toBeInTheDocument();
  });

  it('shows a custom errorText when supplied', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'c',
            type: 'select',
            props: { label: 'Err2', required: true, errorText: 'Wähle etwas!', options: [] },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Wähle etwas!');
  });
});

describe('FormlySelectType (getters)', () => {
  it('controlId falls back to "app-select" when the field has no id', () => {
    expect(makeType({ props: {} }).controlId).toBe('app-select');
  });

  it('controlId uses the field id when set', () => {
    expect(makeType({ id: 'sel-3', props: {} }).controlId).toBe('sel-3');
  });

  it('optionList returns props.options, or [] when absent', () => {
    expect(makeType({ props: { options: [{ value: 'x', label: 'X' }] } }).optionList).toEqual([
      { value: 'x', label: 'X' },
    ]);
    expect(makeType({ props: {} }).optionList).toEqual([]);
  });

});

describe('FormlySelectType (English locale)', () => {
  // The German texts are fallbacks in the catalog, not literals in the template.
  // An English session must therefore read English.
  beforeEach(() => localStorage.setItem('ap.locale', 'en'));
  afterEach(() => localStorage.removeItem('ap.locale'));

  it('renders the default prompt and the default error in English', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'c',
            type: 'select',
            props: { label: 'Err', required: true, options: [] },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Please select an option.');
  });

  it('renders the default select prompt in English', async () => {
    await render(FormlySelectType, {
      componentInputs: {
        field: {
          formControl: new FormControl(''),
          props: { label: 'P', options: [] },
          options: { showError: () => false },
        } as never,
      },
    });
    expect(screen.getByRole('combobox')).toHaveTextContent('Please select …');
  });
});
