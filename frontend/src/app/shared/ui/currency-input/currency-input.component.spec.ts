import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { fireEvent, render, screen } from '@testing-library/angular';
import { CurrencyInputComponent } from './currency-input.component';

@Component({
  standalone: true,
  imports: [CurrencyInputComponent, FormsModule],
  template: `<app-currency-input [ngModel]="value()" (ngModelChange)="value.set($event)" ariaLabel="amount" />`,
})
class HostComponent {
  readonly value = signal('');
}

async function setup(initial = '') {
  const view = await render(HostComponent);
  view.fixture.componentInstance.value.set(initial);
  view.fixture.detectChanges();
  await view.fixture.whenStable();
  view.fixture.detectChanges(); // NgModel.writeValue läuft per Microtask → re-render
  const input = screen.getByLabelText('amount') as HTMLInputElement;
  return { ...view, input, host: view.fixture.componentInstance };
}

describe('CurrencyInputComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders a € symbol', async () => {
    await setup();
    expect(screen.getByText('€')).toBeInTheDocument();
  });

  it('writes a canonical model value from user input', async () => {
    const { input, host } = await setup();
    fireEvent.input(input, { target: { value: '1234,56' } });
    expect(host.value()).toBe('1234.56');
  });

  it('formats with grouping + 2 decimals on blur (de)', async () => {
    const { input } = await setup();
    fireEvent.input(input, { target: { value: '1234.5' } });
    fireEvent.blur(input);
    expect(input.value).toBe('1.234,50');
  });

  it('shows an editable (ungrouped) value on focus', async () => {
    const { input } = await setup('1234.56');
    expect(input.value).toBe('1.234,56'); // formatted while blurred
    fireEvent.focus(input);
    expect(input.value).toBe('1234,56'); // editable on focus
  });

  it('clears to empty model for blank input', async () => {
    const { input, host } = await setup('10');
    fireEvent.input(input, { target: { value: '' } });
    expect(host.value()).toBe('');
  });
});
