import { Component } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { de } from '@core/i18n/translations';
import { provideFormly } from '../formly.providers';
import { FormlyDateRangeType } from './formly-daterange.type';

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
  props: Record<string, unknown>,
  model: Record<string, unknown> = {},
): Promise<{ host: HostComponent; detect: () => void }> {
  const { fixture } = await render(HostComponent, {
    providers: [provideFormly()],
    componentProperties: { fields: [{ key: 'range', type: 'daterange', props }], model },
  });
  return { host: fixture.componentInstance, detect: () => fixture.detectChanges() };
}

describe('FormlyDateRangeType (value)', () => {
  function makeType(value: unknown = null): { cmp: FormlyDateRangeType; control: FormControl } {
    const control = new FormControl(value);
    const field = {
      formControl: control,
      props: {},
      options: { showError: () => false },
    } as unknown as FormlyDateRangeType['field'];
    return { cmp: Object.assign(Object.create(FormlyDateRangeType.prototype), { field }), control };
  }

  it('range returns {} for null/non-object, the object otherwise', () => {
    expect(makeType(null).cmp.range).toEqual({});
    expect(makeType('nope').cmp.range).toEqual({});
    expect(makeType({ from: '2026-01-01' }).cmp.range).toEqual({ from: '2026-01-01' });
  });

  it('patch sets from/to on the control and marks it dirty/touched', () => {
    const { cmp, control } = makeType({ from: '2026-01-01' });
    cmp.patch('to', '2026-01-03');
    expect(control.value).toEqual({ from: '2026-01-01', to: '2026-01-03' });
    expect(control.dirty).toBe(true);
    expect(control.touched).toBe(true);
  });

  it('clears the control to null when both ends are emptied', () => {
    const { cmp, control } = makeType({ from: '2026-01-01' });
    cmp.patch('from', '');
    expect(control.value).toBeNull();
  });
});

describe('FormlyDateRangeType (rendered)', () => {
  afterEach(() => localStorage.removeItem('ap.locale'));

  it('renders two kit datepickers in the German format with the legend', async () => {
    await renderField({ label: 'Zeitraum', required: true }, { range: { from: '2026-10-09' } });
    expect(document.querySelectorAll('app-datepicker')).toHaveLength(2);
    expect(document.querySelector('input[type="date"]:not(.dp__native)')).toBeNull();
    expect(screen.getByRole('group', { name: /Zeitraum/ })).toBeInTheDocument();
    expect(await screen.findByDisplayValue('09.10.2026')).toBe(
      screen.getByLabelText(new RegExp(de['formly.daterange.from'])),
    );
    expect(screen.getByLabelText(new RegExp(de['formly.daterange.to']))).toHaveValue('');
  });

  it('writes the typed ends into the model as ISO dates', async () => {
    const { host } = await renderField({ label: 'Zeitraum' });
    await userEvent.type(screen.getByLabelText(/Von/), '09.10.2026');
    await userEvent.tab();
    expect(host.model['range']).toEqual({ from: '2026-10-09' });
    await userEvent.type(screen.getByLabelText(/Bis/), '11.10.2026');
    await userEvent.tab();
    expect(host.model['range']).toEqual({ from: '2026-10-09', to: '2026-10-11' });
    await userEvent.clear(screen.getByLabelText(/Von/));
    await userEvent.tab();
    await userEvent.clear(screen.getByLabelText(/Bis/));
    await userEvent.tab();
    expect(host.model['range']).toBeNull();
  });

  it('shows the hint while there is no error', async () => {
    await renderField({ label: 'Zeitraum', description: 'Freitag bis Sonntag' });
    expect(screen.getByText('Freitag bis Sonntag')).toBeInTheDocument();
    expect(screen.getByRole('group')).toHaveAttribute('aria-describedby');
  });

  it('marks both empty ends as required after a touch', async () => {
    const { host, detect } = await renderField({ label: 'Zeitraum', required: true, description: 'x' });
    host.form.markAllAsTouched();
    detect();
    const alerts = screen.getAllByRole('alert');
    expect(alerts).toHaveLength(2);
    expect(alerts[0]).toHaveTextContent(de['formly.validation.required']);
    expect(screen.queryByText('x')).toBeNull();
  });

  it('names an invalid full range on the end field, and explicit props win', async () => {
    const { host, detect } = await renderField(
      { label: 'Zeitraum', fromLabel: 'Start', toLabel: 'Ende' },
      { range: { from: '2026-10-09', to: '2026-10-11' } },
    );
    const control = host.form.get('range')!;
    control.setErrors({ server: true });
    control.markAsTouched();
    detect();
    expect(screen.getByLabelText(/Start/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(de['formly.daterange.error']);
    expect(screen.getByLabelText(/Ende/)).toBeInTheDocument();
  });

  it('lets an explicit error text win', async () => {
    const { host, detect } = await renderField({ label: 'Zeitraum', errorText: 'Kaputt.' });
    host.form.markAllAsTouched();
    host.form.get('range')!.setErrors({ server: true });
    detect();
    for (const alert of screen.getAllByRole('alert')) expect(alert).toHaveTextContent('Kaputt.');
  });

  it('renders the captions in English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await renderField({ label: 'Period' });
    expect(screen.getByLabelText(/From/)).toBeInTheDocument();
    expect(screen.getByLabelText(/To/)).toBeInTheDocument();
  });
});
