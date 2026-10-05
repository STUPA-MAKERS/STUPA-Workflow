import { Component, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DateChipComponent } from './date-chip.component';

@Component({
  standalone: true,
  imports: [DateChipComponent],
  template: `<app-date-chip label="Von" [(value)]="day" />`,
})
class HostComponent {
  readonly day = signal('');
}

async function setup(value = '') {
  const view = await render(HostComponent);
  view.fixture.componentInstance.day.set(value);
  view.fixture.detectChanges();
  const picker = view.container.querySelector('input[type=date]') as HTMLInputElement;
  const valueChange = (): string => view.fixture.componentInstance.day();
  return { ...view, picker, valueChange };
}

describe('DateChipComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('opens the date picker of the browser from anywhere on the chip', async () => {
    const { picker } = await setup();
    const showPicker = jest.fn();
    (picker as unknown as { showPicker: () => void }).showPicker = showPicker;
    await userEvent.click(screen.getByRole('button', { name: 'Von' }));
    expect(showPicker).toHaveBeenCalled();
  });

  it('focuses the input where showPicker is missing or refused', async () => {
    const { picker } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Von' }));
    expect(document.activeElement).toBe(picker);
    picker.blur();
    (picker as unknown as { showPicker: () => void }).showPicker = () => {
      throw new Error('NotAllowedError');
    };
    await userEvent.click(screen.getByRole('button', { name: 'Von' }));
    expect(document.activeElement).toBe(picker);
  });

  it('emits the picked day and shows it in the chip', async () => {
    const { picker, valueChange, fixture } = await setup();
    picker.value = '2026-09-29';
    picker.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(valueChange()).toBe('2026-09-29');
    expect(screen.getByRole('button', { name: 'Von: 29.09.2026' })).toHaveClass('on');
  });

  it('clears a set day with its own button', async () => {
    const { valueChange } = await setup('2026-09-29');
    await userEvent.click(screen.getByRole('button', { name: 'Datum entfernen: Von' }));
    expect(valueChange()).toBe('');
    expect(screen.queryByRole('button', { name: /Datum entfernen/ })).toBeNull();
  });
});
