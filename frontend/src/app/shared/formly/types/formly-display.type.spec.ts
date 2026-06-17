import { Component } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import { provideFormly } from '../formly.providers';
import { FormlyDisplayType } from './formly-display.type';

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
): Promise<void> {
  await render(HostComponent, {
    providers: [provideFormly()],
    componentProperties: { fields: [field], model },
  });
}

function makeType(props: Record<string, unknown>, value?: unknown): FormlyDisplayType {
  const cmp = new FormlyDisplayType();
  cmp.field = {
    props,
    formControl: new FormControl(value),
    options: { showError: () => false },
  } as unknown as FormlyDisplayType['field'];
  return cmp;
}

describe('FormlyDisplayType (rendered)', () => {
  it('shows static markdown text', async () => {
    await renderField({ key: 'info', type: 'display', props: { label: 'Info', text: 'Beachten.' } });
    expect(screen.getByText('Beachten.')).toBeInTheDocument();
    expect(screen.getByText('Info')).toBeInTheDocument();
  });

  it('renders the em-dash placeholder for an empty computed value', async () => {
    await renderField({ key: 'total', type: 'display', props: { label: 'Summe', computed: true } });
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('renders a computed value when present', async () => {
    await renderField(
      { key: 'total', type: 'display', props: { computed: true } },
      { total: 42 },
    );
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders a heading with title and subtitle', async () => {
    await renderField({
      type: 'display',
      props: { heading: true, label: 'Abschnitt', description: 'Untertitel' },
    });
    expect(screen.getByRole('heading', { name: 'Abschnitt' })).toBeInTheDocument();
    expect(screen.getByText('Untertitel')).toBeInTheDocument();
  });

  it('renders a heading using text when there is no label', async () => {
    await renderField({ type: 'display', props: { heading: true, text: 'Nur Text' } });
    expect(screen.getByRole('heading', { name: 'Nur Text' })).toBeInTheDocument();
  });

  it('renders a value block without a label when none is set', async () => {
    await renderField({ key: 'info', type: 'display', props: { text: 'Ohne Label' } });
    expect(screen.getByText('Ohne Label')).toBeInTheDocument();
    expect(screen.queryByText('Info')).not.toBeInTheDocument();
  });
});

describe('FormlyDisplayType (getters)', () => {
  it('isComputed reflects props.computed (truthy/falsy)', () => {
    expect(makeType({ computed: true }).isComputed).toBe(true);
    expect(makeType({}).isComputed).toBe(false);
  });

  it('isHeading reflects props.heading (truthy/falsy)', () => {
    expect(makeType({ heading: true }).isHeading).toBe(true);
    expect(makeType({}).isHeading).toBe(false);
  });

  it('text: computed null/undefined/empty all render the em-dash', () => {
    expect(makeType({ computed: true }, null).text).toBe('—');
    expect(makeType({ computed: true }, undefined).text).toBe('—');
    expect(makeType({ computed: true }, '').text).toBe('—');
  });

  it('text: computed non-empty value is stringified', () => {
    expect(makeType({ computed: true }, 0).text).toBe('0');
    expect(makeType({ computed: true }, 'hi').text).toBe('hi');
  });

  it('text: non-computed returns props.text or empty string', () => {
    expect(makeType({ text: 'Statisch' }).text).toBe('Statisch');
    expect(makeType({}).text).toBe('');
  });
});
