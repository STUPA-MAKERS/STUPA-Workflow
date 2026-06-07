import { Component } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { CheckboxComponent } from './checkbox.component';

describe('CheckboxComponent', () => {
  it('renders projected label bound to the native checkbox', async () => {
    await render(`<app-checkbox>Aktiv</app-checkbox>`, { imports: [CheckboxComponent] });
    const box = screen.getByRole('checkbox', { name: 'Aktiv' });
    expect(box).toBeInTheDocument();
    expect(box).not.toBeChecked();
  });

  it('writes the model value into the checked state', async () => {
    @Component({
      standalone: true,
      imports: [CheckboxComponent, FormsModule],
      template: `<app-checkbox [(ngModel)]="on">X</app-checkbox>`,
    })
    class Host {
      on = true;
    }
    const { fixture } = await render(Host);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('emits model changes when toggled', async () => {
    @Component({
      standalone: true,
      imports: [CheckboxComponent, FormsModule],
      template: `<app-checkbox [(ngModel)]="on">X</app-checkbox>`,
    })
    class Host {
      on = false;
    }
    const { fixture } = await render(Host);
    await userEvent.click(screen.getByRole('checkbox'));
    expect(fixture.componentInstance.on).toBe(true);
  });

  it('disables the native control via the CVA', async () => {
    @Component({
      standalone: true,
      imports: [CheckboxComponent, ReactiveFormsModule],
      template: `<app-checkbox [formControl]="ctrl">X</app-checkbox>`,
    })
    class Host {
      ctrl = new FormControl({ value: false, disabled: true });
    }
    await render(Host);
    expect(screen.getByRole('checkbox')).toBeDisabled();
  });

  it('associates a hint via aria-describedby', async () => {
    await render(`<app-checkbox hint="Mehr Infos">X</app-checkbox>`, {
      imports: [CheckboxComponent],
    });
    const box = screen.getByRole('checkbox');
    const describedBy = box.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(screen.getByText('Mehr Infos')).toHaveAttribute('id', describedBy);
  });
});
