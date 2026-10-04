import { Component, signal } from '@angular/core';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { FilterSelectComponent, type FilterSelectOption } from './filter-select.component';

const OPTIONS: FilterSelectOption[] = [
  { value: '', label: 'Alle Typen' },
  { value: 'f', label: 'Förderantrag' },
  { value: 'r', label: 'Reisekosten' },
  { value: 'rr', label: 'Rückerstattung' },
  { value: 'v', label: 'Veranstaltung' },
];

@Component({
  standalone: true,
  imports: [FilterSelectComponent],
  template: `
    <button type="button">davor</button>
    <app-filter-select
      label="Typ"
      [options]="options()"
      [multiple]="multiple()"
      [(value)]="value"
      [(values)]="values"
      [active]="value() !== '' || values().length > 0"
      [text]="text()"
      resetLabel="Zurücksetzen"
    />
    <button type="button">danach</button>
  `,
})
class HostComponent {
  readonly options = signal<readonly FilterSelectOption[]>(OPTIONS);
  readonly multiple = signal(false);
  readonly value = signal('');
  readonly values = signal<readonly string[]>([]);
  readonly text = signal<string | null>(null);
}

/** Let `matchMedia` report a phone (or not). jsdom has none of its own. */
function mockPhone(phone: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: phone && query.includes('max-width'),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

async function setup(opts: { phone?: boolean; multiple?: boolean; value?: string } = {}) {
  mockPhone(!!opts.phone);
  const view = await render(HostComponent);
  const host = view.fixture.componentInstance;
  host.multiple.set(!!opts.multiple);
  if (opts.value !== undefined) host.value.set(opts.value);
  view.fixture.detectChanges();
  const user = userEvent.setup();
  const chip = () => view.container.querySelector('app-filter-select button') as HTMLButtonElement;
  return { view, host, user, chip };
}

const focusedName = () => (document.activeElement as HTMLElement | null)?.textContent?.trim();

describe('FilterSelectComponent', () => {
  const realMatchMedia = window.matchMedia;
  afterEach(() => {
    window.matchMedia = realMatchMedia;
  });

  it('is a closed list button that shows the current value', async () => {
    const { chip, host, view } = await setup();
    expect(chip()).toHaveAttribute('aria-haspopup', 'listbox');
    expect(chip()).toHaveAttribute('aria-expanded', 'false');
    expect(chip()).not.toHaveAttribute('aria-controls');
    expect(chip()).toHaveClass('chip');
    expect(chip()).not.toHaveClass('on');
    // The label of the current value, and the filter name in front for the screen reader.
    expect(chip()).toHaveTextContent('Alle Typen');
    expect(chip()).toHaveAccessibleName('Typ: Alle Typen');
    host.value.set('f');
    view.fixture.detectChanges();
    expect(chip()).toHaveTextContent('Förderantrag');
    expect(chip()).toHaveClass('on');
    // An own text wins; a text that starts with the name keeps its name.
    host.text.set('Typ: Förderantrag');
    view.fixture.detectChanges();
    expect(chip()).toHaveAccessibleName('Typ: Förderantrag');
    expect(view.container.querySelector('select')).toBeNull();
  });

  it('opens the list under the chip on a click, with a check on the current value', async () => {
    const { chip, user } = await setup({ value: 'r' });
    await user.click(chip());
    const list = screen.getByRole('listbox', { name: 'Typ' });
    expect(chip()).toHaveAttribute('aria-expanded', 'true');
    expect(chip()).toHaveAttribute('aria-controls', list.id);
    expect(list).not.toHaveAttribute('aria-multiselectable');
    const options = within(list).getAllByRole('option');
    expect(options.map((o) => o.getAttribute('aria-selected'))).toEqual([
      'false',
      'false',
      'true',
      'false',
      'false',
    ]);
    expect(options[2].querySelector('.fs__check')).toBeTruthy();
    expect(options[1].querySelector('.fs__check')).toBeNull();
    // One Tab stop in the list: the current value.
    expect(options.filter((o) => o.tabIndex === 0)).toEqual([options[2]]);
    await waitFor(() => expect(focusedName()).toBe('Reisekosten'));
  });

  it('picks a value with a click, closes and returns the focus to the chip', async () => {
    const { chip, user, host } = await setup();
    await user.click(chip());
    await user.click(screen.getByRole('option', { name: 'Veranstaltung' }));
    expect(host.value()).toBe('v');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(document.activeElement).toBe(chip());
  });

  it('moves with the arrows, Home and End, and picks with Enter', async () => {
    const { chip, user, host } = await setup();
    chip().focus();
    await user.keyboard('{ArrowDown}');
    await waitFor(() => expect(focusedName()).toBe('Alle Typen'));
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(focusedName()).toBe('Reisekosten');
    await user.keyboard('{ArrowUp}');
    expect(focusedName()).toBe('Förderantrag');
    await user.keyboard('{End}');
    expect(focusedName()).toBe('Veranstaltung');
    // The list does not wrap.
    await user.keyboard('{ArrowDown}');
    expect(focusedName()).toBe('Veranstaltung');
    await user.keyboard('{Home}');
    expect(focusedName()).toBe('Alle Typen');
    await user.keyboard('{ArrowUp}');
    expect(focusedName()).toBe('Alle Typen');
    await user.keyboard('{ArrowDown}{Enter}');
    expect(host.value()).toBe('f');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(document.activeElement).toBe(chip());
  });

  it('opens on the last choice with Arrow Up', async () => {
    const { chip, user } = await setup();
    chip().focus();
    await user.keyboard('{ArrowUp}');
    await waitFor(() => expect(focusedName()).toBe('Veranstaltung'));
  });

  it('jumps to a choice by its first letters (type-ahead)', async () => {
    const { chip, user } = await setup();
    await user.click(chip());
    await waitFor(() => expect(focusedName()).toBe('Alle Typen'));
    const list = screen.getByRole('listbox');
    const now = jest.spyOn(Date, 'now');
    const key = (k: string, at: number) => {
      now.mockReturnValue(at);
      fireEvent.keyDown(list, { key: k });
    };
    // One letter again and again cycles through the choices with it.
    key('r', 1000);
    expect(focusedName()).toBe('Reisekosten');
    key('r', 1100);
    expect(focusedName()).toBe('Rückerstattung');
    key('r', 1200);
    expect(focusedName()).toBe('Reisekosten');
    // After a pause the search starts again; more letters narrow it.
    key('v', 5000);
    expect(focusedName()).toBe('Veranstaltung');
    key('r', 9000);
    key('ü', 9100);
    expect(focusedName()).toBe('Rückerstattung');
    // No match: the focus stays.
    key('x', 20000);
    expect(focusedName()).toBe('Rückerstattung');
    now.mockRestore();
  });

  it('closes on Escape and returns the focus, closes on Tab without it', async () => {
    const { chip, user, host } = await setup();
    await user.click(chip());
    await waitFor(() => expect(focusedName()).toBe('Alle Typen'));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(document.activeElement).toBe(chip());
    expect(host.value()).toBe('');

    await user.keyboard('{ArrowDown}');
    await waitFor(() => expect(screen.getByRole('listbox')).toBeInTheDocument());
    fireEvent.keyDown(document.activeElement!, { key: 'Tab' });
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('closes on a click outside and on a second click on the chip', async () => {
    const { chip, user } = await setup();
    await user.click(chip());
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'danach' }));
    expect(screen.queryByRole('listbox')).toBeNull();
    await user.click(chip());
    await user.click(chip());
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(chip()).toHaveAttribute('aria-expanded', 'false');
  });

  it('places the list under the start of the chip and keeps it in the viewport', async () => {
    const { chip, user } = await setup();
    jest.spyOn(chip(), 'getBoundingClientRect').mockReturnValue({
      top: 100,
      bottom: 132,
      left: 900,
      right: 1000,
      width: 100,
      height: 32,
    } as DOMRect);
    const proto = HTMLElement.prototype as HTMLElement & { showPopover?: () => void };
    const shown = jest.fn();
    proto.showPopover = shown;
    // The list: 240 x 200. jsdom: the window is 1024 wide, so the list moves left.
    const rect = jest
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue({ top: 0, bottom: 200, left: 0, right: 240, width: 240, height: 200 } as DOMRect);
    try {
      await user.click(chip());
      const menu = document.querySelector('.fs__menu') as HTMLElement;
      expect(menu.style.top).toBe('136px');
      await waitFor(() => expect(menu.style.left).toBe(`${1024 - 8 - 240}px`));
      expect(shown).toHaveBeenCalled();
    } finally {
      delete proto.showPopover;
      rect.mockRestore();
    }
  });

  it('toggles several values and stays open (multiple)', async () => {
    const { chip, user, host, view } = await setup({ multiple: true });
    await user.click(chip());
    const list = screen.getByRole('listbox', { name: 'Typ' });
    expect(list).toHaveAttribute('aria-multiselectable', 'true');
    await user.click(within(list).getByRole('option', { name: 'Reisekosten' }));
    await user.click(within(list).getByRole('option', { name: 'Förderantrag' }));
    expect(host.values()).toEqual(['r', 'f']);
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    view.fixture.detectChanges();
    expect(within(list).getByRole('option', { name: 'Förderantrag' })).toHaveAttribute('aria-selected', 'true');
    expect(list.querySelectorAll('.fs__box--on')).toHaveLength(2);
    // The chip names the filter, not a value, when it holds several.
    expect(chip()).toHaveTextContent('Typ');
    await user.click(within(list).getByRole('option', { name: 'Reisekosten' }));
    expect(host.values()).toEqual(['f']);
    await user.click(screen.getByRole('button', { name: 'Zurücksetzen' }));
    expect(host.values()).toEqual([]);
    view.fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Zurücksetzen' })).toBeNull();
  });

  it('says when there is no choice', async () => {
    const { chip, user, host, view } = await setup();
    host.options.set([]);
    view.fixture.detectChanges();
    await user.click(chip());
    expect(screen.getByText('Keine Auswahl möglich')).toBeInTheDocument();
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  describe('on a phone', () => {
    it('opens the bottom sheet with the list and focuses the current value', async () => {
      const { chip, user } = await setup({ phone: true, value: 'v' });
      await user.click(chip());
      const sheet = screen.getByRole('dialog', { name: 'Typ' });
      expect(sheet).toHaveClass('ss--bottom');
      expect(document.querySelector('.fs__menu')).toBeNull();
      const list = within(sheet).getByRole('listbox', { name: 'Typ' });
      expect(chip()).toHaveAttribute('aria-controls', list.id);
      await waitFor(() => expect(focusedName()).toBe('Veranstaltung'));
    });

    it('picks a value, closes the sheet and returns the focus', async () => {
      const { chip, user, host } = await setup({ phone: true });
      await user.click(chip());
      await user.click(screen.getByRole('option', { name: 'Förderantrag' }));
      expect(host.value()).toBe('f');
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(document.activeElement).toBe(chip());
    });

    it('closes on Escape and returns the focus', async () => {
      const { chip, user } = await setup({ phone: true });
      await user.click(chip());
      await waitFor(() => expect(focusedName()).toBe('Alle Typen'));
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(chip()).toHaveAttribute('aria-expanded', 'false');
      expect(document.activeElement).toBe(chip());
    });

    it('puts the reset of several values into the sheet header', async () => {
      const { chip, user, host } = await setup({ phone: true, multiple: true });
      host.values.set(['r']);
      await user.click(chip());
      const sheet = screen.getByRole('dialog', { name: 'Typ' });
      await user.click(within(sheet).getByRole('option', { name: 'Veranstaltung' }));
      expect(host.values()).toEqual(['r', 'v']);
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      await user.click(within(sheet).getByRole('button', { name: 'Zurücksetzen' }));
      expect(host.values()).toEqual([]);
    });
  });

  it('has no axe violations, closed and open', async () => {
    const { chip, user, view } = await setup({ value: 'f' });
    expect(await runAxe(view.container)).toHaveNoViolations();
    await user.click(chip());
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('has no axe violations in the sheet with several values', async () => {
    const { chip, user, host } = await setup({ phone: true, multiple: true });
    host.values.set(['f']);
    await user.click(chip());
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
