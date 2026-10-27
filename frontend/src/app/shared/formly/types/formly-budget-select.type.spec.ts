import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { de } from '@core/i18n/translations';
import { budgetOptionTree } from '@shared/forms/budget-options';
import { provideFormly } from '../formly.providers';
import { FormlyBudgetSelectType } from './formly-budget-select.type';

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

const NODES = budgetOptionTree(
  [
    { value: 'a', label: { de: 'AStA (VS)' }, key: 'VS', color: '#5fb37a' },
    { value: 'b', label: { de: 'Kultur (VS-1)' }, key: '1', parentId: 'a' },
  ],
  'de',
);

async function renderField(
  props: Record<string, unknown>,
  model: Record<string, unknown> = {},
  extra: Partial<FormlyFieldConfig> = {},
): Promise<{ host: HostComponent }> {
  const { fixture } = await render(HostComponent, {
    providers: [provideFormly()],
    componentProperties: {
      fields: [{ key: 'ks', type: 'budget_select', props: { nodes: NODES, ...props }, ...extra }],
      model,
    },
  });
  return { host: fixture.componentInstance };
}

/** Let the list render: it opens after one task. */
async function settle(): Promise<void> {
  await new Promise((r) => setTimeout(r));
}

describe('FormlyBudgetSelectType', () => {
  it('shows the tree with swatches and keys and writes the picked id into the model', async () => {
    const { host } = await renderField({ label: 'Kostenstelle', required: true });
    const field = screen.getByRole('button', { name: /Kostenstelle/ });
    expect(field).toHaveTextContent(de['formly.select.placeholder']);
    expect(field).toHaveAttribute('aria-required', 'true');
    await userEvent.click(field);
    await settle();
    const options = screen.getAllByRole('option');
    expect(options.map((o) => o.textContent?.replace(/\s+/g, ''))).toEqual(['VSAStA', '1Kultur']);
    expect(options[0].querySelector('.ccs__swatch')).not.toBeNull();
    await userEvent.click(options[1]);
    expect(host.model['ks']).toBe('b');
    expect(screen.getByRole('button', { name: /Kostenstelle/ })).toHaveTextContent('Kultur');
  });

  it('shows the picked cost centre of the model and the hint', async () => {
    await renderField({ label: 'KS', description: 'Wohin das Geld geht.' }, { ks: 'a' });
    expect(screen.getByRole('button', { name: /KS/ })).toHaveTextContent('AStA');
    expect(screen.getByText('Wohin das Geld geht.')).toBeInTheDocument();
  });

  it('shows the error state and text when invalid', async () => {
    await renderField(
      { label: 'Fehler', required: true, description: 'Hinweis' },
      {},
      { validation: { show: true } },
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(de['formly.select.error']);
    expect(screen.getByRole('button', { name: /Fehler/ })).toHaveAttribute('aria-invalid', 'true');
    expect(screen.queryByText('Hinweis')).not.toBeInTheDocument();
  });

  it('shows a custom errorText', async () => {
    await renderField(
      { label: 'E', required: true, errorText: 'Bitte wählen!' },
      {},
      {
        validation: { show: true },
      },
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('Bitte wählen!');
  });

  it('falls back to an id, no nodes and an empty value', () => {
    const cmp = new FormlyBudgetSelectType();
    cmp.field = {
      props: {},
      formControl: { value: null },
      options: { showError: () => false },
    } as unknown as FormlyBudgetSelectType['field'];
    expect(cmp.controlId).toBe('app-budget-select');
    expect(cmp.nodes).toEqual([]);
    expect(cmp.value).toBe('');
  });
});
