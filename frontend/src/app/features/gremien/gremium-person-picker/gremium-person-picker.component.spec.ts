import { fireEvent, render, screen, within } from '@testing-library/angular';
import { of } from 'rxjs';
import { GremiumPersonPickerComponent, type PickerHit } from './gremium-person-picker.component';

const GREMIEN = [
  { id: 'g-1', name: 'AStA', logoUrl: '/api/committees/g-1/logo' },
  { id: 'g-2', name: 'Fachschaft Informatik' },
];

async function setup(taken: readonly string[] = []) {
  const picked = jest.fn<void, [PickerHit]>();
  const persons = jest.fn((q: string) => of(q === 'as' ? [{ id: 'p-1', name: 'Astrid Berg' }] : []));
  const view = await render(GremiumPersonPickerComponent, {
    inputs: { placeholder: 'Gremium oder Person einladen', gremien: GREMIEN, persons, taken },
    on: { picked },
  });
  const field = screen.getByLabelText('Gremium oder Person einladen') as HTMLInputElement;
  return { ...view, picked, persons, field, detect: () => view.fixture.detectChanges() };
}

describe('GremiumPersonPickerComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** §ui-kit:001074: the Gremien by name in place, a logo in place of the avatar, no hit twice. */
  it('lists the Gremien on Arrow Down, moves in the list and picks with a click', async () => {
    const view = await setup(['g-2']);
    fireEvent.keyDown(view.field, { key: 'ArrowDown' });
    view.detect();
    const list = screen.getByRole('listbox', { name: 'Treffer' });
    const options = within(list).getAllByRole('option');
    expect(options).toHaveLength(1);
    expect(options[0].querySelector('app-gremium-logo img')?.getAttribute('src')).toBe('/api/committees/g-1/logo');
    fireEvent.keyDown(options[0], { key: 'ArrowUp' });
    expect(document.activeElement).toBe(view.field);
    fireEvent.click(options[0]);
    expect(view.picked).toHaveBeenCalledWith({ kind: 'gremium', id: 'g-1', name: 'AStA', logoUrl: '/api/committees/g-1/logo' });
    view.detect();
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('closes on Escape and picks the first hit on Enter', async () => {
    jest.useFakeTimers();
    try {
      const view = await setup();
      fireEvent.input(view.field, { target: { value: 'as' } });
      jest.advanceTimersByTime(300);
      view.detect();
      expect(view.persons).toHaveBeenCalledWith('as');
      const list = screen.getByRole('listbox', { name: 'Treffer' });
      expect(within(list).getAllByRole('option').map((o) => o.querySelector('.gpp__name')?.textContent)).toEqual([
        'AStA',
        'Astrid Berg',
      ]);
      fireEvent.keyDown(within(list).getAllByRole('option')[0], { key: 'Escape' });
      view.detect();
      expect(screen.queryByRole('listbox')).toBeNull();
      fireEvent.input(view.field, { target: { value: 'ast' } });
      view.detect();
      fireEvent.keyDown(view.field, { key: 'Enter' });
      expect(view.picked).toHaveBeenCalledWith(expect.objectContaining({ kind: 'gremium', id: 'g-1' }));
      fireEvent.input(view.field, { target: { value: 'zz' } });
      jest.advanceTimersByTime(300);
      view.detect();
      expect(screen.getByText('Keine Treffer')).toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  it('moves with the menu keys, browses on a press into the field and closes on Tab', async () => {
    jest.useFakeTimers();
    try {
      const view = await setup();
      fireEvent.pointerDown(view.field);
      view.detect();
      const options = within(screen.getByRole('listbox')).getAllByRole('option');
      expect(options).toHaveLength(2);
      options[0].focus();
      fireEvent.keyDown(options[0], { key: 'ArrowDown' });
      expect(document.activeElement).toBe(options[1]);
      fireEvent.keyDown(options[1], { key: 'ArrowDown' });
      expect(document.activeElement).toBe(options[1]);
      fireEvent.keyDown(options[1], { key: 'ArrowUp' });
      expect(document.activeElement).toBe(options[0]);
      fireEvent.keyDown(options[0], { key: 'End' });
      expect(document.activeElement).toBe(options[1]);
      fireEvent.keyDown(options[1], { key: 'Home' });
      expect(document.activeElement).toBe(options[0]);
      fireEvent.keyDown(options[0], { key: 'x' });
      fireEvent.keyDown(options[0], { key: 'Tab' });
      view.detect();
      expect(screen.queryByRole('listbox')).toBeNull();

      fireEvent.keyDown(view.field, { key: 'ArrowDown' });
      view.detect();
      jest.runOnlyPendingTimers();
      expect(document.activeElement?.getAttribute('role')).toBe('option');
      fireEvent.keyDown(view.field, { key: 'Escape' });
      view.detect();
      expect(screen.queryByRole('listbox')).toBeNull();
      fireEvent.keyDown(view.field, { key: 'Escape' });
      fireEvent.keyDown(view.field, { key: 'ArrowDown' });
      view.detect();
      fireEvent.keyDown(view.field, { key: 'Tab' });
      view.detect();
      expect(screen.queryByRole('listbox')).toBeNull();

      fireEvent.keyDown(view.field, { key: 'Enter' });
      expect(view.picked).not.toHaveBeenCalled();
      fireEvent.pointerDown(document.body);
      view.detect();
      expect(screen.queryByRole('listbox')).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it('offers no persons without a person search and closes when the field leaves the view', async () => {
    const view = await render(GremiumPersonPickerComponent, {
      inputs: { placeholder: 'Gremium', gremien: GREMIEN },
    });
    const field = screen.getByLabelText('Gremium') as HTMLInputElement;
    fireEvent.input(field, { target: { value: 'a' } });
    view.fixture.detectChanges();
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(2);
    const pill = field.closest('app-search-pill') as HTMLElement;
    jest.spyOn(pill, 'getBoundingClientRect').mockReturnValue({
      top: -200, bottom: -100, left: 0, right: 100, width: 100, height: 100, x: 0, y: -200, toJSON: () => ({}),
    } as DOMRect);
    window.dispatchEvent(new Event('scroll'));
    view.fixture.detectChanges();
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});
