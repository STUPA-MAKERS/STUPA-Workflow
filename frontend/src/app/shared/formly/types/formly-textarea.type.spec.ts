import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideFormly } from '../formly.providers';
import { FormlyTextareaType } from './formly-textarea.type';

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

/** Instantiate the type directly with a stubbed Formly `field` to drive getters. */
function makeType(field: Partial<FormlyFieldConfig> & { showError?: boolean }): FormlyTextareaType {
  const cmp = new FormlyTextareaType();
  const showError = field.showError ?? false;
  cmp.field = {
    ...field,
    options: { showError: () => showError },
  } as unknown as FormlyTextareaType['field'];
  return cmp;
}

describe('FormlyTextareaType (rendered)', () => {
  it('renders label, binds to model and uses the default rows', async () => {
    const { host } = await renderField({
      key: 'note',
      type: 'textarea',
      props: { label: 'Notiz' },
    });
    const ta = screen.getByLabelText(/Notiz/) as HTMLTextAreaElement;
    expect(ta.rows).toBe(4);
    await userEvent.type(ta, 'Hallo');
    expect(host.model['note']).toBe('Hallo');
  });

  it('renders the required marker and a custom rows count', async () => {
    await renderField({
      key: 'note',
      type: 'textarea',
      props: { label: 'Pflicht', required: true, rows: 8 },
    });
    expect(screen.getByText('*')).toBeInTheDocument();
    const ta = screen.getByLabelText(/Pflicht/) as HTMLTextAreaElement;
    expect(ta.rows).toBe(8);
  });

  it('shows the hint when there is a description and no error', async () => {
    await renderField({
      key: 'note',
      type: 'textarea',
      props: { label: 'Mit Hinweis', description: 'Bitte ausführlich.' },
    });
    expect(screen.getByText('Bitte ausführlich.')).toBeInTheDocument();
    const ta = screen.getByLabelText(/Mit Hinweis/);
    expect(ta.getAttribute('aria-describedby')).toMatch(/-hint$/);
    expect(ta.getAttribute('aria-invalid')).toBeNull();
  });

  it('sets the placeholder attribute when provided', async () => {
    await renderField({
      key: 'a',
      type: 'textarea',
      props: { label: 'Mit Platzhalter', placeholder: 'tippen…' },
    });
    expect(screen.getByLabelText(/Mit Platzhalter/)).toHaveAttribute('placeholder', 'tippen…');
  });

  it('omits placeholder and describedBy when bare', async () => {
    await renderField({ key: 'b', type: 'textarea', props: { label: 'Schlicht' } });
    const ta = screen.getByLabelText(/Schlicht/);
    expect(ta.getAttribute('placeholder')).toBeNull();
    expect(ta.getAttribute('aria-describedby')).toBeNull();
  });

  it('renders the error alert with default message when showError is forced', async () => {
    const { fixture } = await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        // validation.show forces showError without needing touch/submit.
        fields: [
          {
            key: 'note',
            type: 'textarea',
            props: { label: 'X', required: true, description: 'desc' },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    fixture.detectChanges();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Ungültige Eingabe');
    const ta = screen.getByLabelText(/X/);
    expect(ta.getAttribute('aria-describedby')).toMatch(/-error$/);
    expect(ta.getAttribute('aria-invalid')).toBe('true');
    expect(screen.queryByText('desc')).not.toBeInTheDocument();
  });

  it('renders a custom errorText when supplied', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'note',
            type: 'textarea',
            props: { label: 'Y', required: true, errorText: 'Pflichtfeld!' },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Pflichtfeld!');
  });
});

describe('FormlyTextareaType (getters)', () => {
  it('controlId falls back to "app-textarea" when the field has no id', () => {
    expect(makeType({ props: {} }).controlId).toBe('app-textarea');
  });

  it('controlId uses the field id when set', () => {
    expect(makeType({ id: 'ta-7', props: {} }).controlId).toBe('ta-7');
  });

  it('describedBy → error id when showError is true', () => {
    expect(makeType({ id: 'x', props: { description: 'd' }, showError: true }).describedBy).toBe(
      'x-error',
    );
  });

  it('describedBy → hint id when there is a description and no error', () => {
    expect(makeType({ id: 'x', props: { description: 'd' }, showError: false }).describedBy).toBe(
      'x-hint',
    );
  });

  it('describedBy → null when no error and no description', () => {
    expect(makeType({ id: 'x', props: {}, showError: false }).describedBy).toBeNull();
  });
});
