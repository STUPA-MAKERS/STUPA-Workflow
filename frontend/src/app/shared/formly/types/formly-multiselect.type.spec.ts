import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { provideFormly } from '../formly.providers';

@Component({
  standalone: true,
  imports: [ReactiveFormsModule, FormlyForm],
  template: `<form [formGroup]="form"><formly-form [form]="form" [fields]="fields" [model]="model" /></form>`,
})
class HostComponent {
  form = new FormGroup({});
  model: Record<string, unknown> = {};
  fields: FormlyFieldConfig[] = [];
}

const OPTIONS = [
  { value: 'party', label: 'Party' },
  { value: 'ersti', label: 'Erstsemester' },
  { value: 'kultur', label: 'Kultur' },
];

async function renderField(props: Record<string, unknown> = {}, model: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const view = await render(HostComponent, {
    providers: [provideFormly()],
    componentProperties: {
      fields: [{ key: 'cat', type: 'multiselect', props: { label: 'Kategorie', options: OPTIONS, ...props } }],
      model,
    },
  });
  return { ...view, host: view.fixture.componentInstance };
}

const trigger = () => screen.getByRole('button', { name: /Kategorie/ });

describe('FormlyMultiSelectType', () => {
  it('shows the chosen labels in the order of the options', async () => {
    await renderField({}, { cat: ['ersti', 'party'] });
    expect(trigger()).toHaveAccessibleName('Kategorie Party, Erstsemester');
    expect(trigger()).toHaveAttribute('aria-expanded', 'false');
    expect(trigger()).toHaveAttribute('aria-haspopup', 'dialog');
  });

  it('shows the placeholder when nothing is chosen', async () => {
    await renderField({ required: true });
    expect(trigger().querySelector('.msel__value--empty')).not.toBeNull();
    expect(trigger()).toHaveTextContent('Bitte wählen');
  });

  it('opens the choices in a sheet; each click applies at once', async () => {
    const { host, detectChanges } = await renderField({}, { cat: ['kultur'] });
    await userEvent.click(trigger());
    detectChanges();
    const sheet = screen.getByRole('dialog', { name: 'Kategorie' });
    expect(within(sheet).getByRole('checkbox', { name: 'Kultur' })).toBeChecked();
    await userEvent.click(within(sheet).getByRole('checkbox', { name: 'Erstsemester' }));
    await userEvent.click(within(sheet).getByRole('checkbox', { name: 'Party' }));
    await userEvent.click(within(sheet).getByRole('checkbox', { name: 'Kultur' }));
    expect(host.model['cat']).toEqual(['party', 'ersti']);
    await userEvent.keyboard('{Escape}');
    detectChanges();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger()).toHaveAccessibleName('Kategorie Party, Erstsemester');
  });

  it('opens from the bottom on a phone', async () => {
    const spy = jest
      .spyOn(window, 'matchMedia')
      .mockImplementation((query: string) => ({ matches: query.includes('max-width'), addEventListener: jest.fn(), removeEventListener: jest.fn() }) as unknown as MediaQueryList);
    const { detectChanges } = await renderField();
    await userEvent.click(trigger());
    detectChanges();
    expect(screen.getByRole('dialog')).toHaveClass('ss--bottom');
    spy.mockRestore();
  });

  it('shows the hint, and the error once touched', async () => {
    const { host, detectChanges } = await renderField({ required: true, description: 'Mehrere möglich' });
    expect(screen.getByText('Mehrere möglich')).toBeInTheDocument();
    expect(trigger()).toHaveAttribute('aria-describedby', expect.stringMatching(/-hint$/));
    host.form.get('cat')?.markAsTouched();
    host.form.get('cat')?.setErrors({ required: true });
    detectChanges();
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(trigger()).toHaveAttribute('aria-invalid', 'true');
  });

  it('has no a11y violations', async () => {
    const { container } = await renderField({}, { cat: ['party'] });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
