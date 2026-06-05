import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideFormly } from '../formly.providers';

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

async function renderFields(
  fields: FormlyFieldConfig[],
  model: Record<string, unknown> = {},
): Promise<HostComponent> {
  const { fixture } = await render(HostComponent, {
    providers: [provideFormly()],
    componentProperties: { fields, model },
  });
  return fixture.componentInstance;
}

describe('Formly field types', () => {
  it('textarea: renders label and binds input to the model', async () => {
    const host = await renderFields([
      { key: 'note', type: 'textarea', props: { label: 'Notiz' } },
    ]);
    const ta = screen.getByLabelText(/Notiz/);
    await userEvent.type(ta, 'Hallo');
    expect(host.model['note']).toBe('Hallo');
  });

  it('select: renders options and updates the model', async () => {
    const host = await renderFields([
      {
        key: 'cat',
        type: 'select',
        props: {
          label: 'Kategorie',
          options: [
            { value: 'a', label: 'Alpha' },
            { value: 'b', label: 'Beta' },
          ],
        },
      },
    ]);
    await userEvent.selectOptions(screen.getByLabelText(/Kategorie/), 'b');
    expect(host.model['cat']).toBe('b');
  });

  it('checkbox: toggles a boolean', async () => {
    const host = await renderFields([
      { key: 'agree', type: 'checkbox', props: { label: 'Einverstanden' } },
    ]);
    await userEvent.click(screen.getByLabelText(/Einverstanden/));
    expect(host.model['agree']).toBe(true);
  });

  it('multicheckbox: maintains a string array of selected values', async () => {
    const host = await renderFields([
      {
        key: 'tags',
        type: 'multicheckbox',
        props: {
          label: 'Tags',
          options: [
            { value: 'x', label: 'Xeno' },
            { value: 'y', label: 'Ypsilon' },
          ],
        },
      },
    ]);
    await userEvent.click(screen.getByLabelText(/Xeno/));
    await userEvent.click(screen.getByLabelText(/Ypsilon/));
    await userEvent.click(screen.getByLabelText(/Xeno/));
    expect(host.model['tags']).toEqual(['y']);
  });

  it('display: shows static markdown text and computed values', async () => {
    await renderFields([
      { key: 'info', type: 'display', props: { label: 'Info', text: 'Bitte beachten.' } },
      { key: 'total', type: 'display', props: { label: 'Summe', computed: true } },
    ]);
    expect(screen.getByText('Bitte beachten.')).toBeInTheDocument();
    // computed without a value renders the em-dash placeholder.
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
