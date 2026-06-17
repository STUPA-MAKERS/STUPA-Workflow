import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideFormly } from './formly.providers';
import { FormlyInputType } from './formly-input.type';

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

describe('FormlyInputType (rendered branches)', () => {
  it('renders a plain UI-Kit input for text and binds the model', async () => {
    const { host } = await renderField({
      key: 'title',
      type: 'input',
      props: { label: 'Titel', type: 'text', placeholder: 'tippen', hint: 'kurz' },
    });
    const input = screen.getByLabelText(/Titel/);
    await userEvent.type(input, 'Hallo');
    expect(host.model['title']).toBe('Hallo');
  });

  it('defaults the html type to text when props.type is unset', async () => {
    await renderField({ key: 'a', type: 'input', props: { label: 'Default' } });
    expect(screen.getByLabelText(/Default/)).toBeInTheDocument();
  });

  it('renders the datepicker branch for date fields', async () => {
    await renderField({
      key: 'd',
      type: 'input',
      props: { label: 'Datum', type: 'date', min: '2020-01-01', max: '2030-12-31', required: true },
    });
    // app-datepicker renders a date input.
    expect(document.querySelector('app-datepicker')).toBeTruthy();
    expect(screen.getByLabelText(/Datum/)).toBeInTheDocument();
  });

  it('renders the currency branch for currency fields', async () => {
    await renderField({
      key: 'amount',
      type: 'input',
      props: { label: 'Betrag', type: 'currency', placeholder: '0,00' },
    });
    expect(document.querySelector('app-currency-input')).toBeTruthy();
    expect(screen.getByLabelText(/Betrag/)).toBeInTheDocument();
  });

  it('shows an error on the input branch when invalid (validation.show)', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'req',
            type: 'input',
            props: { label: 'Pflicht', type: 'text', required: true, errorText: 'Fehlt!' },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    expect(await screen.findByText('Fehlt!')).toBeInTheDocument();
  });
});

describe('FormlyInputType.asString', () => {
  const cmp = new FormlyInputType();

  it('returns empty string for null and undefined', () => {
    expect(cmp.asString(null)).toBe('');
    expect(cmp.asString(undefined)).toBe('');
  });

  it('stringifies other values (including 0 and numbers)', () => {
    expect(cmp.asString(0)).toBe('0');
    expect(cmp.asString(42)).toBe('42');
    expect(cmp.asString('2024-01-01')).toBe('2024-01-01');
  });
});
