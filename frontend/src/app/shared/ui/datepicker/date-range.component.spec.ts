import { Component } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DateRangeComponent, type DateRange } from './date-range.component';

describe('DateRangeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('renders start and end (localized) inputs under the labels', async () => {
    await render(`<app-date-range legend="Zeitraum" startLabel="Von" endLabel="Bis" />`, {
      imports: [DateRangeComponent],
    });
    expect((screen.getByLabelText('Von') as HTMLInputElement).type).toBe('text');
    expect((screen.getByLabelText('Bis') as HTMLInputElement).type).toBe('text');
  });

  it('writes a model range into both controls (localized display)', async () => {
    @Component({
      standalone: true,
      imports: [DateRangeComponent, FormsModule],
      template: `<app-date-range startLabel="Von" endLabel="Bis" [(ngModel)]="range" />`,
    })
    class Host {
      range: DateRange = { start: '2026-01-01', end: '2026-03-31' };
    }
    const { fixture } = await render(Host);
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect((screen.getByLabelText('Von') as HTMLInputElement).value).toBe('01.01.2026');
    expect((screen.getByLabelText('Bis') as HTMLInputElement).value).toBe('31.03.2026');
  });

  it('emits the ISO start when a localized date is typed', async () => {
    @Component({
      standalone: true,
      imports: [DateRangeComponent, FormsModule],
      template: `<app-date-range startLabel="Von" endLabel="Bis" [(ngModel)]="range" />`,
    })
    class Host {
      range: DateRange = { start: '', end: '' };
    }
    const { fixture } = await render(Host);
    await userEvent.type(screen.getByLabelText('Von'), '10.05.2026');
    await userEvent.tab(); // blur → commit
    expect(fixture.componentInstance.range.start).toBe('2026-05-10');
  });

  it('emits the ISO end when the end date is typed', async () => {
    @Component({
      standalone: true,
      imports: [DateRangeComponent, FormsModule],
      template: `<app-date-range startLabel="Von" endLabel="Bis" [(ngModel)]="range" />`,
    })
    class Host {
      range: DateRange = { start: '', end: '' };
    }
    const { fixture } = await render(Host);
    await userEvent.type(screen.getByLabelText('Bis'), '20.06.2026');
    await userEvent.tab(); // blur → commit
    expect(fixture.componentInstance.range.end).toBe('2026-06-20');
    // Start is still empty → emitted as part of the range object.
    expect(fixture.componentInstance.range.start).toBe('');
  });

  it('renders an optional legend', async () => {
    await render(`<app-date-range legend="Zeitraum" startLabel="Von" endLabel="Bis" />`, {
      imports: [DateRangeComponent],
    });
    expect(screen.getByText('Zeitraum')).toBeInTheDocument();
  });

  it('omits the legend when none is provided', async () => {
    const { container } = await render(`<app-date-range startLabel="Von" endLabel="Bis" />`, {
      imports: [DateRangeComponent],
    });
    expect(container.querySelector('legend')).toBeNull();
  });

  it('records the disabled state via setDisabledState (CVA)', async () => {
    @Component({
      standalone: true,
      imports: [DateRangeComponent, ReactiveFormsModule],
      template: `<app-date-range startLabel="Von" endLabel="Bis" [formControl]="ctrl" />`,
    })
    class Host {
      ctrl = new FormControl<DateRange>(
        { value: { start: '', end: '' }, disabled: true },
      );
    }
    const view = await render(Host);
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as DateRangeComponent;
    // setDisabledState flips the component's disabled signal.
    expect(cmp.disabled()).toBe(true);
    // NOTE: the template does not currently propagate `disabled` to the inner
    // app-datepicker controls — see reported behavior gap.
  });

  it('handles a null model (writeValue(null)) as empty start/end', async () => {
    @Component({
      standalone: true,
      imports: [DateRangeComponent, ReactiveFormsModule],
      template: `<app-date-range startLabel="Von" endLabel="Bis" [formControl]="ctrl" />`,
    })
    class Host {
      ctrl = new FormControl<DateRange | null>({ start: '2026-01-01', end: '2026-02-01' });
    }
    const { fixture } = await render(Host);
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect((screen.getByLabelText('Von') as HTMLInputElement).value).toBe('01.01.2026');
    fixture.componentInstance.ctrl.setValue(null);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect((screen.getByLabelText('Von') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Bis') as HTMLInputElement).value).toBe('');
  });

  it('default onChange/onTouched callbacks are safe no-ops before registration', async () => {
    const view = await render(`<app-date-range startLabel="Von" endLabel="Bis" />`, {
      imports: [DateRangeComponent],
    });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as DateRangeComponent;
    // Exercise the default no-op initializers directly.
    expect(() => cmp.onTouched()).not.toThrow();
    const change = (cmp as unknown as { onChange: (v: DateRange) => void }).onChange;
    expect(() => change({ start: '', end: '' })).not.toThrow();
  });

  it('registers an onTouched callback that can be invoked', async () => {
    const view = await render(`<app-date-range startLabel="Von" endLabel="Bis" />`, {
      imports: [DateRangeComponent],
    });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as DateRangeComponent;
    const touched = jest.fn();
    cmp.registerOnTouched(touched);
    // The default onTouched starts as a no-op; after registration it is the spy.
    expect(cmp.onTouched).toBe(touched);
    cmp.onTouched();
    expect(touched).toHaveBeenCalledTimes(1);
  });
});
