import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { fireEvent, render, screen } from '@testing-library/angular';
import { TimeInputComponent } from './time-input.component';

@Component({
  standalone: true,
  imports: [FormsModule, TimeInputComponent],
  template: `<app-time-input label="Zeit" [ngModel]="value()" (ngModelChange)="value.set($event)" />`,
})
class Host {
  readonly value = signal('');
}

async function setup(initial = '') {
  const view = await render(Host);
  view.fixture.componentInstance.value.set(initial);
  view.fixture.detectChanges();
  // ngModel schreibt asynchron in den CVA — auf den Initial-Write warten.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return view;
}

describe('TimeInputComponent (24h, #time-input)', () => {
  it('commits tolerant input as HH:MM on blur', async () => {
    const view = await setup();
    const input = screen.getByLabelText('Zeit') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '9.5 invalid' } });
    fireEvent.blur(input);
    expect(input.value).toBe(''); // ungültig → letzter gültiger Wert (leer)

    fireEvent.input(input, { target: { value: '9:30' } });
    fireEvent.blur(input);
    expect(input.value).toBe('09:30');
    expect(view.fixture.componentInstance.value()).toBe('09:30');
  });

  it('rejects out-of-range and falls back to the last valid value', async () => {
    const view = await setup();
    const input = screen.getByLabelText('Zeit') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '18:00' } });
    fireEvent.blur(input);
    fireEvent.input(input, { target: { value: '25:00' } });
    fireEvent.blur(input);
    expect(input.value).toBe('18:00');
    expect(view.fixture.componentInstance.value()).toBe('18:00');
  });

  it('normalizes backend HH:MM:SS wire values', async () => {
    await setup('18:30:00');
    const input = screen.getByLabelText('Zeit') as HTMLInputElement;
    expect(input.value).toBe('18:30');
  });

  it('clearing the field commits empty', async () => {
    const view = await setup('10:00');
    const input = screen.getByLabelText('Zeit') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '' } });
    fireEvent.blur(input);
    expect(view.fixture.componentInstance.value()).toBe('');
  });

  it('parses an hours-only value (no minutes) as HH:00', async () => {
    const view = await setup();
    const input = screen.getByLabelText('Zeit') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '9' } });
    fireEvent.blur(input);
    expect(input.value).toBe('09:00');
    expect(view.fixture.componentInstance.value()).toBe('09:00');
  });

  it('accepts the compact 0930 and dotted 09.30 forms', async () => {
    const view = await setup();
    const input = screen.getByLabelText('Zeit') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '0930' } });
    fireEvent.blur(input);
    expect(input.value).toBe('09:30');

    fireEvent.input(input, { target: { value: '09.30' } });
    fireEvent.blur(input);
    expect(input.value).toBe('09:30');
    expect(view.fixture.componentInstance.value()).toBe('09:30');
  });

  it('rejects a malformed wire value (writeValue) as empty', async () => {
    await setup('not-a-time');
    const input = screen.getByLabelText('Zeit') as HTMLInputElement;
    expect(input.value).toBe('');
  });

  it('exposes an ariaLabel and required marker when no visible label is set', async () => {
    await render(`<app-time-input ariaLabel="Beginn" [required]="true" />`, {
      imports: [TimeInputComponent],
    });
    const input = screen.getByLabelText('Beginn') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute('required');
  });

  it('disables the control via setDisabledState', async () => {
    const view = await render(`<app-time-input ariaLabel="Zeit" />`, {
      imports: [TimeInputComponent],
    });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as TimeInputComponent;
    cmp.setDisabledState(true);
    view.fixture.detectChanges();
    expect(screen.getByLabelText('Zeit')).toBeDisabled();
  });

  it('registers onChange/onTouched and exercises the default no-ops', async () => {
    const view = await render(`<app-time-input ariaLabel="Zeit" />`, {
      imports: [TimeInputComponent],
    });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as TimeInputComponent;
    const defaultOnChange = (cmp as unknown as { onChange: (v: string) => void }).onChange;
    expect(() => defaultOnChange('09:00')).not.toThrow();
    expect(() => cmp.onTouched()).not.toThrow();
    const onChange = jest.fn();
    const onTouched = jest.fn();
    cmp.registerOnChange(onChange);
    cmp.registerOnTouched(onTouched);
    const input = screen.getByLabelText('Zeit') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '07:45' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith('07:45');
    expect(onTouched).toHaveBeenCalled();
  });
});
