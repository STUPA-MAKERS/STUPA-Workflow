import { Component } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { fireEvent, render, screen } from '@testing-library/angular';
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

  it('links a hint via aria-describedby when there is no error', async () => {
    await render(`<app-select label="X" hint="Wähle eines" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    const box = screen.getByRole('combobox');
    expect(box).not.toHaveAttribute('aria-invalid');
    const describedBy = box.getAttribute('aria-describedby');
    expect(describedBy).toMatch(/-hint$/);
    expect(screen.getByText('Wähle eines')).toHaveAttribute('id', describedBy);
  });

  it('has no aria-describedby when neither hint nor error is present', async () => {
    await render(`<app-select label="X" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    expect(screen.getByRole('combobox')).not.toHaveAttribute('aria-describedby');
  });

  it('hides the hint when an error is also present (error wins)', async () => {
    await render(`<app-select label="X" hint="Hinweis" error="Fehler" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    expect(screen.queryByText('Hinweis')).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent('Fehler');
  });

  it('renders a placeholder option and the required marker', async () => {
    await render(`<app-select label="Status" placeholder="Bitte wählen" [required]="true" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    const placeholder = screen.getByRole('option', { name: 'Bitte wählen' }) as HTMLOptionElement;
    expect(placeholder).toBeInTheDocument();
    // Required → placeholder is disabled (cannot re-select the empty option).
    expect(placeholder.disabled).toBe(true);
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('honours per-option disabled flags', async () => {
    const opts: SelectOption[] = [
      { value: 'a', label: 'Alpha' },
      { value: 'b', label: 'Beta', disabled: true },
    ];
    await render(`<app-select label="X" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts },
    });
    expect((screen.getByRole('option', { name: 'Beta' }) as HTMLOptionElement).disabled).toBe(true);
    expect((screen.getByRole('option', { name: 'Alpha' }) as HTMLOptionElement).disabled).toBe(false);
  });

  it('writes a null model value as an empty selection (writeValue null)', async () => {
    const view = await render(`<app-select ariaLabel="X" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as SelectComponent;
    cmp.writeValue('b');
    expect(cmp.value()).toBe('b');
    cmp.writeValue(null);
    expect(cmp.value()).toBe('');
  });

  it('marks the control touched on blur (registerOnTouched)', async () => {
    const onTouched = jest.fn();
    const view = await render(`<app-select ariaLabel="X" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as SelectComponent;
    cmp.registerOnTouched(onTouched);
    fireEvent.blur(screen.getByRole('combobox'));
    expect(onTouched).toHaveBeenCalled();
  });

  it('default onChange/onTouched callbacks are safe no-ops before registration', async () => {
    const view = await render(`<app-select ariaLabel="X" [options]="opts" />`, {
      imports: [SelectComponent],
      componentProperties: { opts: OPTS },
    });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as SelectComponent;
    const onChange = (cmp as unknown as { onChange: (v: string) => void }).onChange;
    expect(() => onChange('a')).not.toThrow();
    expect(() => cmp.onTouched()).not.toThrow();
  });
});
