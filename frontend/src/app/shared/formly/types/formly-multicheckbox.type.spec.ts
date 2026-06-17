import { Component } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideFormly } from '../formly.providers';
import { FormlyMultiCheckboxType } from './formly-multicheckbox.type';

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

const OPTIONS = [
  { value: 'x', label: 'Xeno' },
  { value: 'y', label: 'Ypsilon' },
];

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

function makeType(value: unknown): FormlyMultiCheckboxType {
  const cmp = new FormlyMultiCheckboxType();
  cmp.field = {
    formControl: new FormControl(value),
    props: { options: OPTIONS },
    options: { showError: () => false },
  } as unknown as FormlyMultiCheckboxType['field'];
  return cmp;
}

describe('FormlyMultiCheckboxType (rendered)', () => {
  it('maintains a string array of selected values (add/add/remove)', async () => {
    const { host } = await renderField({
      key: 'tags',
      type: 'multicheckbox',
      props: { label: 'Tags', options: OPTIONS },
    });
    await userEvent.click(screen.getByLabelText(/Xeno/));
    await userEvent.click(screen.getByLabelText(/Ypsilon/));
    await userEvent.click(screen.getByLabelText(/Xeno/));
    expect(host.model['tags']).toEqual(['y']);
  });

  it('reflects pre-selected values via isChecked', async () => {
    await renderField(
      { key: 'tags', type: 'multicheckbox', props: { label: 'Tags', options: OPTIONS } },
      { tags: ['y'] },
    );
    expect(screen.getByLabelText(/Xeno/)).not.toBeChecked();
    expect(screen.getByLabelText(/Ypsilon/)).toBeChecked();
  });

  it('renders the required marker', async () => {
    await renderField({
      key: 'tags',
      type: 'multicheckbox',
      props: { label: 'Pflicht', required: true, options: OPTIONS },
    });
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('shows the hint when there is a description and no error', async () => {
    await renderField({
      key: 'tags',
      type: 'multicheckbox',
      props: { label: 'X', description: 'Mehrfachauswahl.', options: OPTIONS },
    });
    expect(screen.getByText('Mehrfachauswahl.')).toBeInTheDocument();
  });

  it('renders the default error message when invalid', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'tags',
            type: 'multicheckbox',
            props: { label: 'Err', required: true, description: 'desc', options: OPTIONS },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Bitte auswählen.');
    expect(screen.queryByText('desc')).not.toBeInTheDocument();
  });

  it('renders a custom errorText when supplied', async () => {
    await render(HostComponent, {
      providers: [provideFormly()],
      componentProperties: {
        model: {},
        fields: [
          {
            key: 'tags',
            type: 'multicheckbox',
            props: { label: 'Err2', required: true, errorText: 'Mind. eine Option!', options: OPTIONS },
            validation: { show: true },
          } as FormlyFieldConfig,
        ],
      },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Mind. eine Option!');
  });
});

describe('FormlyMultiCheckboxType (unit)', () => {
  it('optionList returns [] when props.options is absent', () => {
    const cmp = new FormlyMultiCheckboxType();
    cmp.field = {
      props: {},
      options: { showError: () => false },
    } as unknown as FormlyMultiCheckboxType['field'];
    expect(cmp.optionList).toEqual([]);
  });

  it('isChecked is false when the control value is not an array', () => {
    const cmp = makeType(null);
    expect(cmp.isChecked('x')).toBe(false);
  });

  it('isChecked reflects membership for an array value', () => {
    const cmp = makeType(['x']);
    expect(cmp.isChecked('x')).toBe(true);
    expect(cmp.isChecked('y')).toBe(false);
  });

  it('toggle adds and removes values and marks the control dirty/touched', () => {
    const cmp = makeType(['x']);
    cmp.toggle('y', true);
    expect(cmp.formControl.value).toEqual(['x', 'y']);
    expect(cmp.formControl.dirty).toBe(true);
    expect(cmp.formControl.touched).toBe(true);

    cmp.toggle('x', false);
    expect(cmp.formControl.value).toEqual(['y']);
  });

  it('toggle handles a non-array starting value (treated as empty)', () => {
    const cmp = makeType(undefined);
    cmp.toggle('x', true);
    expect(cmp.formControl.value).toEqual(['x']);
  });
});
