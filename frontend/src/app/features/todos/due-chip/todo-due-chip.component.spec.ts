import { fireEvent, render, screen } from '@testing-library/angular';
import { TodoDueChipComponent } from './todo-due-chip.component';

async function setup(value: string | null, disabled = false) {
  const changed = jest.fn();
  const view = await render(TodoDueChipComponent, { inputs: { value, disabled }, on: { changed } });
  const native = view.container.querySelector('input[type="date"]') as HTMLInputElement;
  return { ...view, changed, native };
}

describe('TodoDueChipComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the date, opens the picker of the browser and removes the date', async () => {
    const { changed, native } = await setup('2026-11-03');
    const showPicker = jest.fn();
    Object.defineProperty(native, 'showPicker', { value: showPicker, configurable: true });
    fireEvent.click(screen.getByRole('button', { name: 'Fälligkeit ändern: Di, 03.11.2026' }));
    expect(showPicker).toHaveBeenCalled();
    expect(native.value).toBe('2026-11-03');
    fireEvent.change(native, { target: { value: '' } });
    expect(changed).toHaveBeenCalledWith(null);
  });

  it('falls back to a click without showPicker or when it throws', async () => {
    const { native } = await setup(null);
    const click = jest.spyOn(native, 'click');
    Object.defineProperty(native, 'showPicker', { value: undefined, configurable: true });
    fireEvent.click(screen.getByRole('button', { name: 'Datum setzen' }));
    expect(click).toHaveBeenCalledTimes(1);
    Object.defineProperty(native, 'showPicker', {
      value: () => {
        throw new Error('no gesture');
      },
      configurable: true,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Datum setzen' }));
    expect(click).toHaveBeenCalledTimes(2);
    expect(native.value).toBe('');
    expect(screen.getByText('ohne Datum')).toBeInTheDocument();
    fireEvent.change(native, { target: { value: '' } });
  });

  it('emits a new date only', async () => {
    const { changed, native } = await setup('2026-11-03');
    fireEvent.change(native, { target: { value: '2026-11-03' } });
    expect(changed).not.toHaveBeenCalled();
    fireEvent.change(native, { target: { value: '2026-11-05' } });
    expect(changed).toHaveBeenCalledWith('2026-11-05');
  });

  it('is locked while disabled', async () => {
    await setup('2026-11-03', true);
    expect(screen.getByRole('button', { name: /Fälligkeit ändern/ })).toBeDisabled();
  });
});
