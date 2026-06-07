import { Component } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DatepickerComponent } from './datepicker.component';

function dateInput(): HTMLInputElement {
  return screen.getByLabelText('Stichtag') as HTMLInputElement;
}

describe('DatepickerComponent', () => {
  it('renders a native date input bound to the label', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    await render(Host);
    expect(dateInput().type).toBe('date');
  });

  it('writes the model value into the control', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '2026-06-07';
    }
    const { fixture } = await render(Host);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(dateInput().value).toBe('2026-06-07');
  });

  it('emits model changes when a date is typed', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    const { fixture } = await render(Host);
    await userEvent.type(dateInput(), '2026-12-24');
    expect(fixture.componentInstance.v).toBe('2026-12-24');
  });

  it('disables the control via the CVA', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, ReactiveFormsModule],
      template: `<app-datepicker label="Stichtag" [formControl]="ctrl" />`,
    })
    class Host {
      ctrl = new FormControl({ value: '', disabled: true });
    }
    await render(Host);
    expect(dateInput()).toBeDisabled();
  });

  it('passes min/max bounds to the native control', async () => {
    await render(`<app-datepicker label="Stichtag" min="2026-01-01" max="2026-12-31" />`, {
      imports: [DatepickerComponent],
    });
    expect(dateInput()).toHaveAttribute('min', '2026-01-01');
    expect(dateInput()).toHaveAttribute('max', '2026-12-31');
  });
});
