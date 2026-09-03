import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { TestBed } from '@angular/core/testing';
import { FormlyConfig, FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { de } from '@core/i18n/translations';
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

/**
 * Read the registered validation messages. Formly applies the config when it builds a
 * form, so the messages need one rendered form.
 */
async function validationMessages(): Promise<(name: string) => string> {
  await render(HostComponent, { providers: [provideFormly()] });
  const config = TestBed.inject(FormlyConfig);
  return (name: string): string => {
    const message = config.getValidatorMessage(name);
    return typeof message === 'string' ? message : String(message({}, {}));
  };
}

describe('Formly validation messages', () => {
  afterEach(() => localStorage.removeItem('ap.locale'));

  it('takes every message from the translation catalog', async () => {
    const message = await validationMessages();
    expect(message('required')).toBe(de['formly.validation.required']);
    expect(message('email')).toBe(de['formly.validation.email']);
    expect(message('min')).toBe(de['formly.validation.min']);
    expect(message('max')).toBe(de['formly.validation.max']);
    expect(message('minlength')).toBe(de['formly.validation.minlength']);
    expect(message('maxlength')).toBe(de['formly.validation.maxlength']);
    expect(message('pattern')).toBe(de['formly.validation.pattern']);
  });

  it('reads English in an English session', async () => {
    localStorage.setItem('ap.locale', 'en');
    const message = await validationMessages();
    expect(message('required')).toBe('This field is required.');
    expect(message('email')).toBe('Enter a valid email address.');
  });
});
