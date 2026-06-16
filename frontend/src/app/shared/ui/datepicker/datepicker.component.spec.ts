import { Component } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { fireEvent, render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { I18nService } from '@core/i18n/i18n.service';
import { DatepickerComponent } from './datepicker.component';

function textInput(): HTMLInputElement {
  return screen.getByLabelText('Stichtag') as HTMLInputElement;
}

function nativeInput(): HTMLInputElement {
  return document.querySelector('input[type="date"]') as HTMLInputElement;
}

describe('DatepickerComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

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

  it('clears the model when the field is blanked on blur', async () => {
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
    const input = textInput();
    fireEvent.input(input, { target: { value: '   ' } });
    fireEvent.blur(input);
    expect(fixture.componentInstance.v).toBe('');
    expect(input.value).toBe('');
  });

  it('restores the last valid value when an unparseable date is entered', async () => {
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
    const input = textInput();
    fireEvent.input(input, { target: { value: 'gibberish' } });
    fireEvent.blur(input);
    // Unparseable → model unchanged, display reverts to the last valid value.
    expect(fixture.componentInstance.v).toBe('2026-06-07');
    expect(input.value).toBe('07.06.2026');
  });

  it('rejects out-of-range months/days and reverts to the last valid value', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    const { fixture } = await render(Host);
    const input = textInput();
    fireEvent.input(input, { target: { value: '40.13.2026' } });
    fireEvent.blur(input);
    expect(fixture.componentInstance.v).toBe('');
    expect(input.value).toBe('');
  });

  it('rejects three non-numeric parts (NaN components) and reverts', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    const { fixture } = await render(Host);
    const input = textInput();
    // Splits into 3 parts but none are valid numbers → !dd/!mm/!yyyy guard.
    fireEvent.input(input, { target: { value: 'aa.bb.cc' } });
    fireEvent.blur(input);
    expect(fixture.componentInstance.v).toBe('');
  });

  it('parses 2-digit years as 20xx and accepts / and - separators', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    const { fixture } = await render(Host);
    const input = textInput();
    fireEvent.input(input, { target: { value: '5/9/24' } });
    fireEvent.blur(input);
    expect(fixture.componentInstance.v).toBe('2024-09-05');
  });

  it('commits a date chosen via the native (calendar) control', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    const { fixture } = await render(Host);
    const native = nativeInput();
    fireEvent.change(native, { target: { value: '2026-03-15' } });
    expect(fixture.componentInstance.v).toBe('2026-03-15');
    expect(textInput().value).toBe('15.03.2026');
  });

  it('opens the native calendar via showPicker when available', async () => {
    const showPicker = jest.fn();
    const original = (HTMLInputElement.prototype as { showPicker?: () => void }).showPicker;
    (HTMLInputElement.prototype as { showPicker?: () => void }).showPicker = showPicker;
    try {
      await render(`<app-datepicker label="Stichtag" />`, { imports: [DatepickerComponent] });
      await userEvent.click(screen.getByRole('button'));
      expect(showPicker).toHaveBeenCalledTimes(1);
    } finally {
      (HTMLInputElement.prototype as { showPicker?: () => void }).showPicker = original;
    }
  });

  it('falls back to focus + click when showPicker is unavailable', async () => {
    const original = (HTMLInputElement.prototype as { showPicker?: () => void }).showPicker;
    delete (HTMLInputElement.prototype as { showPicker?: () => void }).showPicker;
    const clickSpy = jest.spyOn(HTMLInputElement.prototype, 'click');
    const focusSpy = jest.spyOn(HTMLInputElement.prototype, 'focus');
    try {
      await render(`<app-datepicker label="Stichtag" />`, { imports: [DatepickerComponent] });
      clickSpy.mockClear();
      focusSpy.mockClear();
      await userEvent.click(screen.getByRole('button', { name: /./ }));
      expect(focusSpy).toHaveBeenCalled();
      expect(clickSpy).toHaveBeenCalled();
    } finally {
      clickSpy.mockRestore();
      focusSpy.mockRestore();
      if (original) (HTMLInputElement.prototype as { showPicker?: () => void }).showPicker = original;
    }
  });

  it('reformats the display when the app locale changes (de → en)', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '2026-06-07';
    }
    const view = await render(Host);
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    expect(textInput().value).toBe('07.06.2026');
    const i18n = view.fixture.debugElement.injector.get(I18nService);
    i18n.setLocale('en');
    view.fixture.detectChanges();
    expect(textInput().value).toBe('06/07/2026');
    expect(textInput().placeholder).toBe('MM/DD/YYYY');
  });

  it('links a hint via aria-describedby when there is no error', async () => {
    await render(`<app-datepicker label="Stichtag" hint="Optional" />`, {
      imports: [DatepickerComponent],
    });
    const describedBy = textInput().getAttribute('aria-describedby');
    expect(describedBy).toMatch(/-hint$/);
    expect(screen.getByText('Optional')).toHaveAttribute('id', describedBy);
  });

  it('links an error via aria-describedby and marks invalid (error wins over hint)', async () => {
    await render(`<app-datepicker label="Stichtag" hint="Optional" error="Pflicht" />`, {
      imports: [DatepickerComponent],
    });
    expect(textInput()).toHaveAttribute('aria-invalid', 'true');
    const describedBy = textInput().getAttribute('aria-describedby');
    expect(describedBy).toMatch(/-error$/);
    expect(screen.getByRole('alert')).toHaveAttribute('id', describedBy);
  });

  it('has no aria-describedby when neither hint nor error are set', async () => {
    await render(`<app-datepicker label="Stichtag" />`, { imports: [DatepickerComponent] });
    expect(textInput()).not.toHaveAttribute('aria-describedby');
  });

  it('shows an empty display when written a null value (writeValue(null))', async () => {
    @Component({
      standalone: true,
      imports: [DatepickerComponent, ReactiveFormsModule],
      template: `<app-datepicker label="Stichtag" [formControl]="ctrl" />`,
    })
    class Host {
      ctrl = new FormControl<string | null>('2026-06-07');
    }
    const { fixture } = await render(Host);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(textInput().value).toBe('07.06.2026');
    fixture.componentInstance.ctrl.setValue(null);
    fixture.detectChanges();
    expect(textInput().value).toBe('');
  });

  it('parses and formats in EN locale order (MM/DD/YYYY)', async () => {
    localStorage.setItem('ap.locale', 'en');
    @Component({
      standalone: true,
      imports: [DatepickerComponent, FormsModule],
      template: `<app-datepicker label="Stichtag" [(ngModel)]="v" />`,
    })
    class Host {
      v = '';
    }
    const { fixture } = await render(Host);
    const input = textInput();
    // EN order: month/day/year.
    fireEvent.input(input, { target: { value: '12/24/2026' } });
    fireEvent.blur(input);
    expect(fixture.componentInstance.v).toBe('2026-12-24');
    expect(input.value).toBe('12/24/2026');
  });

  it('openPicker is a no-op without a native element reference', async () => {
    const view = await render(`<app-datepicker label="Stichtag" />`, {
      imports: [DatepickerComponent],
    });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as DatepickerComponent;
    // Force the viewChild signal to resolve to undefined → early return path.
    (cmp as unknown as { native: () => undefined }).native = () => undefined;
    expect(() => cmp.openPicker()).not.toThrow();
  });

  it('uses ariaLabel and the required marker when no visible label is set', async () => {
    await render(`<app-datepicker ariaLabel="Frist" [required]="true" />`, {
      imports: [DatepickerComponent],
    });
    const input = screen.getByLabelText('Frist') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute('required');
  });
});
