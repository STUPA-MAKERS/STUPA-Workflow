import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { fireEvent, render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { By } from '@angular/platform-browser';
import type { Type } from '@angular/core';
import { budgetOptionTree } from '@shared/forms/budget-options';
import { provideFormly } from '../formly.providers';
import { FormlyInputType } from '../formly-input.type';
import { FormlyBudgetSelectType } from './formly-budget-select.type';
import { FormlyCheckboxType } from './formly-checkbox.type';
import { FormlyDateRangeType } from './formly-daterange.type';
import { FormlyDisplayType } from './formly-display.type';
import { FormlyMultiCheckboxType } from './formly-multicheckbox.type';
import { FormlySelectType } from './formly-select.type';
import { FormlyTextareaType } from './formly-textarea.type';
import { pickOption } from '../../../../testing/select';
import { runAxe } from '../../../../testing/a11y';

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
    await pickOption(screen.getByRole('combobox', { name: /Kategorie/ }), 'Beta');
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

  /** A computed field without a value renders the em-dash placeholder. */
  it('display: shows static markdown text and computed values', async () => {
    await renderFields([
      { key: 'info', type: 'display', props: { label: 'Info', text: 'Bitte beachten.' } },
      { key: 'total', type: 'display', props: { label: 'Summe', computed: true } },
    ]);
    expect(screen.getByText('Bitte beachten.')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  /**
   * The test uses single `input` events, because a full re-render per keystroke loses characters.
   * It queries again after each event, because the re-render replaces the previous elements. The
   * first offer is preferred, so the position value is 500 and the total 500.
   */
  it('positions: builds positions/offers, totals preferred values, validates', async () => {
    localStorage.setItem('ap.locale', 'de');
    const host = await renderFields([
      { key: 'costs', type: 'positions', props: { label: 'Kosten', minOffers: 2, minPositions: 1 } },
    ]);
    const form = host.form;
    expect(form.invalid).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: /Position hinzufügen/ }));
    const value = host.model['costs'] as { label: string; offers: unknown[] }[];
    expect(value).toHaveLength(1);
    expect(value[0].offers).toHaveLength(2);

    fireEvent.input(screen.getByLabelText('Position'), { target: { value: 'Catering' } });
    fireEvent.input(screen.getAllByLabelText('Anbieter')[0], { target: { value: 'Anbieter A' } });
    fireEvent.input(screen.getAllByLabelText('Anbieter')[1], { target: { value: 'Anbieter B' } });
    fireEvent.input(screen.getAllByLabelText(/^Betrag/)[0], { target: { value: '500' } });
    fireEvent.input(screen.getAllByLabelText(/^Betrag/)[1], { target: { value: '600' } });

    expect(form.valid).toBe(true);
    const v = host.model['costs'] as { offers: { value: number; preferred: boolean }[] }[];
    const pref = v[0].offers.find((o) => o.preferred);
    expect(pref?.value).toBe(500);
  });

  const OPTIONS = [
    { value: 'a', label: 'Alpha' },
    { value: 'b', label: 'Beta' },
  ];
  const NODES = budgetOptionTree([{ value: 'a', label: { de: 'AStA (VS)' }, key: 'VS', color: '#5fb37a' }], 'de');
  const TYPES: [Type<unknown>, FormlyFieldConfig][] = [
    [FormlyInputType, { key: 'v', type: 'input', props: { label: 'Name' } }],
    [FormlyTextareaType, { key: 'v', type: 'textarea', props: { label: 'Notiz' } }],
    [FormlySelectType, { key: 'v', type: 'select', props: { label: 'Kategorie', options: OPTIONS } }],
    [FormlyBudgetSelectType, { key: 'v', type: 'budget_select', props: { label: 'Kostenstelle', nodes: NODES } }],
    [FormlyCheckboxType, { key: 'v', type: 'checkbox', props: { label: 'Einverstanden' } }],
    [FormlyMultiCheckboxType, { key: 'v', type: 'multicheckbox', props: { label: 'Wahl', options: OPTIONS } }],
    [FormlyDisplayType, { key: 'v', type: 'display', props: { label: 'Info', text: 'Bitte beachten.' } }],
    [FormlyDateRangeType, { key: 'v', type: 'daterange', props: { label: 'Zeitraum' } }],
  ];

  /** § NF/accessibility/conformance/000493: each type, plain and as a touched required field. */
  describe.each(TYPES)('%p', (type, field) => {
    it.each([false, true])('has no axe violations (required and touched: %s)', async (invalid) => {
      const props = { ...field.props, required: invalid };
      const { container, fixture } = await render(HostComponent, {
        providers: [provideFormly()],
        componentProperties: { fields: [{ ...field, props }], model: {} },
      });
      if (invalid) {
        fixture.componentInstance.form.markAllAsTouched();
        fixture.detectChanges();
      }
      expect(fixture.debugElement.query(By.directive(type))).not.toBeNull();
      expect(await runAxe(container)).toHaveNoViolations();
    });
  });
});
