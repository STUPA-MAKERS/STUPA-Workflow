import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideFormly } from './formly.providers';

@Component({
  standalone: true,
  imports: [ReactiveFormsModule, FormlyForm],
  template: `<formly-form [form]="form" [fields]="fields" [model]="model" />`,
})
class HostComponent {
  form = new FormGroup({});
  model: Record<string, unknown> = {};
  fields: FormlyFieldConfig[] = [
    { key: 'title', type: 'input', props: { label: 'Titel', required: true } },
  ];
}

describe('Formly UI-Kit bridge', () => {
  it('renders the registered `input` type using the UI-Kit field', async () => {
    await render(HostComponent, { providers: [provideFormly()] });
    const input = screen.getByLabelText(/Titel/);
    await userEvent.type(input, 'Hallo');
    expect(input).toHaveValue('Hallo');
  });
});
