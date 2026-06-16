import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideFormly } from '../formly.providers';
import { FormlyCheckboxType } from './formly-checkbox.type';

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

function makeType(field: Partial<FormlyFieldConfig>): FormlyCheckboxType {
  const cmp = new FormlyCheckboxType();
  cmp.field = {
    ...field,
    options: { showError: () => false },
  } as unknown as FormlyCheckboxType['field'];
  return cmp;
}

describe('FormlyCheckboxType (rendered)', () => {
  it('toggles the boolean model value', async () => {
    const { host } = await renderField({
      key: 'agree',
      type: 'checkbox',
      props: { label: 'Einverstanden' },
    });
    await userEvent.click(screen.getByLabelText(/Einverstanden/));
    expect(host.model['agree']).toBe(true);
  });

  it('renders the required marker', async () => {
    await renderField({
      key: 'agree',
      type: 'checkbox',
      props: { label: 'Pflicht', required: true },
    });
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('shows the hint when there is a description and no error', async () => {
    await renderField({
      key: 'agree',
      type: 'checkbox',
      props: { label: 'X', description: 'Hinweis hier.' },
    });
    expect(screen.getByText('Hinweis hier.')).toBeInTheDocument();
    expect(screen.getByLabelText(/X/).getAttribute('aria-describedby')).toBeNull();
  });

  it('renders the default error message and aria when invalid', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'agree',
            type: 'checkbox',
            props: { label: 'Err', required: true, description: 'desc' },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Bitte bestätigen.');
    const box = screen.getByLabelText(/Err/);
    expect(box.getAttribute('aria-invalid')).toBe('true');
    expect(box.getAttribute('aria-describedby')).toMatch(/-error$/);
    // hint hidden while error shown.
    expect(screen.queryByText('desc')).not.toBeInTheDocument();
  });

  it('renders a custom errorText when supplied', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'agree',
            type: 'checkbox',
            props: { label: 'Err2', required: true, errorText: 'Zustimmung nötig!' },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Zustimmung nötig!');
  });
});

describe('FormlyCheckboxType (getters)', () => {
  it('controlId falls back to "app-checkbox" when the field has no id', () => {
    expect(makeType({ props: {} }).controlId).toBe('app-checkbox');
  });

  it('controlId uses the field id when set', () => {
    expect(makeType({ id: 'cb-9', props: {} }).controlId).toBe('cb-9');
  });
});
