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
});
