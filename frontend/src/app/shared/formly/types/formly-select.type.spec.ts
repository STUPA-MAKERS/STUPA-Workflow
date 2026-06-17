import { Component } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
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
    await userEvent.selectOptions(screen.getByLabelText(/Kategorie/), 'b');
    expect(host.model['cat']).toBe('b');
  });

  it('renders the required marker and a disabled placeholder option', async () => {
    // Through formly, props.placeholder defaults to '' so the disabled prompt is
    // empty — the realistic integration behaviour.
    await renderField({
      key: 'c',
      type: 'select',
      props: { label: 'Pflicht', required: true, options: [] },
    });
    expect(screen.getByText('*')).toBeInTheDocument();
    const placeholderOpt = screen.getAllByRole('option').find((o) => o.hasAttribute('disabled'));
    expect(placeholderOpt).toBeTruthy();
  });

  it('falls back to the default prompt when placeholder is genuinely undefined', async () => {
    // Render the type directly (no formly prop init) so props.placeholder is
    // undefined → the `?? 'Bitte wählen …'` template fallback fires.
    await render(FormlySelectType, {
      componentInputs: {
        field: {
          formControl: new FormControl(''),
          props: { label: 'P', options: [] },
          options: { showError: () => false },
        } as never,
      },
    });
    const placeholderOpt = screen.getAllByRole('option').find((o) => o.hasAttribute('disabled'));
    expect(placeholderOpt?.textContent?.trim()).toBe('Bitte wählen …');
  });

  it('uses a custom placeholder when provided', async () => {
    await renderField({
      key: 'c',
      type: 'select',
      props: { label: 'P', placeholder: 'Auswahl treffen', options: [] },
    });
    const placeholderOpt = screen.getAllByRole('option').find((o) => o.hasAttribute('disabled'));
    expect(placeholderOpt?.textContent?.trim()).toBe('Auswahl treffen');
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
    expect(alert).toHaveTextContent('Bitte eine Option wählen.');
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

  it('describedBy → error id when showError is true', () => {
    expect(makeType({ id: 's', props: { description: 'd' }, showError: true }).describedBy).toBe(
      's-error',
    );
  });

  it('describedBy → hint id when description present and no error', () => {
    expect(makeType({ id: 's', props: { description: 'd' }, showError: false }).describedBy).toBe(
      's-hint',
    );
  });

  it('describedBy → null with no error and no description', () => {
    expect(makeType({ id: 's', props: {}, showError: false }).describedBy).toBeNull();
  });
});
