import { Component } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { SelectComponent, type SelectOption } from './select.component';

const OPTS: SelectOption[] = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
];

describe('SelectComponent', () => {
  it('renders the label and the option list', async () => {
    @Component({
      standalone: true,
      imports: [SelectComponent, FormsModule],
      template: `<app-select label="Gremium" [options]="opts" [(ngModel)]="v" />`,
    })
    class Host {
      opts = OPTS;
      v = '';
    }
    await render(Host);
    expect(screen.getByRole('combobox', { name: 'Gremium' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Alpha' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Beta' })).toBeInTheDocument();
  });

  it('writes the model value into the selected option', async () => {
    @Component({
      standalone: true,
      imports: [SelectComponent, FormsModule],
      template: `<app-select label="X" [options]="opts" [(ngModel)]="v" />`,
    })
    class Host {
      opts = OPTS;
      v = 'b';
    }
    const { fixture } = await render(Host);
    await fixture.whenStable();
    fixture.detectChanges();
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('b');
  });

  it('emits model changes on selection', async () => {
    @Component({
      standalone: true,
      imports: [SelectComponent, FormsModule],
      template: `<app-select label="X" [options]="opts" [(ngModel)]="v" />`,
    })
    class Host {
      opts = OPTS;
      v = 'a';
    }
    const { fixture } = await render(Host);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'b');
    expect(fixture.componentInstance.v).toBe('b');
  });

  it('disables the native control via the CVA', async () => {
    @Component({
      standalone: true,
      imports: [SelectComponent, ReactiveFormsModule],
      template: `<app-select label="X" [options]="opts" [formControl]="ctrl" />`,
    })
    class Host {
      opts = OPTS;
      ctrl = new FormControl({ value: 'a', disabled: true });
    }
    await render(Host);
    expect(screen.getByRole('combobox')).toBeDisabled();
  });

  it('exposes an aria-label when no visible label is set', async () => {
    await render(`<app-select ariaLabel="Rolle" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    expect(screen.getByRole('combobox', { name: 'Rolle' })).toBeInTheDocument();
  });

  it('marks the control invalid and links the error via aria-describedby', async () => {
    await render(`<app-select label="X" error="Pflichtfeld" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    const box = screen.getByRole('combobox');
    expect(box).toHaveAttribute('aria-invalid', 'true');
    const describedBy = box.getAttribute('aria-describedby');
    expect(screen.getByRole('alert')).toHaveAttribute('id', describedBy);
  });
});
