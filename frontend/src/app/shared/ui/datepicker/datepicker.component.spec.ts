import { Component } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DatepickerComponent } from './datepicker.component';

function textInput(): HTMLInputElement {
  return screen.getByLabelText('Stichtag') as HTMLInputElement;
}

function nativeInput(): HTMLInputElement {
  return document.querySelector('input[type="date"]') as HTMLInputElement;
}

describe('DatepickerComponent', () => {
  it('renders a localized text input (not a native date input)', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    await render(Host);
    expect(textInput().type).toBe('text');
    // Default locale (de) → placeholder shows the locale order.
    expect(textInput().placeholder).toBe('TT.MM.JJJJ');
  });

  it('writes the model value as a localized display string', async () => {
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
    expect(textInput().value).toBe('07.06.2026');
  });

  it('parses typed input into an ISO model value on blur', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    const { fixture } = await render(Host);
    await userEvent.type(textInput(), '24.12.2026');
    await userEvent.tab(); // blur → commit
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
    expect(textInput()).toBeDisabled();
  });

  it('passes min/max bounds to the native (calendar) control', async () => {
    await render(`<app-datepicker label="Stichtag" min="2026-01-01" max="2026-12-31" />`, {
      imports: [DatepickerComponent],
    });
    expect(nativeInput()).toHaveAttribute('min', '2026-01-01');
    expect(nativeInput()).toHaveAttribute('max', '2026-12-31');
  });
});
