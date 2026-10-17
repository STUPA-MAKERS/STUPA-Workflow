import { Component, signal } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { SelectFieldComponent, type SelectFieldOption } from './select.component';

const OPTIONS: SelectFieldOption[] = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
  { value: 'x', label: 'Bremen', disabled: true },
  { value: 'c', label: 'Berlin' },
  { value: 'd', label: 'Delta' },
];

@Component({
  standalone: true,
  imports: [FormsModule, SelectFieldComponent],
  template: `
    <app-select
      name="city"
      [label]="label()"
      [ariaLabel]="ariaLabel()"
      [placeholder]="placeholder()"
      [hint]="hint()"
      [error]="error()"
      [required]="required()"
      [options]="options()"
      [disabled]="disabled()"
      [ngModel]="value()"
      (ngModelChange)="onChange($event)"
    />
    <button type="button">Weiter</button>
  `,
})
class ModelHost {
  readonly label = signal('Stadt');
  readonly ariaLabel = signal('');
  readonly placeholder = signal('');
  readonly hint = signal('');
  readonly error = signal('');
  readonly required = signal(false);
  readonly disabled = signal(false);
  readonly options = signal<SelectFieldOption[]>(OPTIONS);
  readonly value = signal('b');
  readonly changes: string[] = [];
  onChange(v: string): void {
    this.changes.push(v);
    this.value.set(v);
  }
}

@Component({
  standalone: true,
  imports: [ReactiveFormsModule, SelectFieldComponent],
  template: `<app-select label="Art" [options]="options" [formControl]="control" />`,
})
class ReactiveHost {
  readonly options = OPTIONS;
  readonly control = new FormControl('', { nonNullable: true, validators: Validators.required });
}

@Component({
  standalone: true,
  imports: [SelectFieldComponent],
  template: `<app-select label="Signal" [options]="options" [(value)]="choice" />`,
})
class SignalHost {
  readonly options = OPTIONS;
  readonly choice = signal('a');
}

function setPhone(matches: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: matches && query.includes('max-width'),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

async function setup(init: (h: ModelHost) => void = () => undefined) {
  const view = await render(ModelHost);
  init(view.fixture.componentInstance);
  view.fixture.detectChanges();
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const field = () => screen.getByRole('combobox');
  const tick = async () => {
    await new Promise((r) => setTimeout(r));
    await new Promise((r) => setTimeout(r));
    view.fixture.detectChanges();
  };
  return { view, host: view.fixture.componentInstance, field, tick };
}

describe('SelectFieldComponent', () => {
  const realMatchMedia = window.matchMedia;
  beforeEach(() => setPhone(false));
  afterEach(() => {
    window.matchMedia = realMatchMedia;
  });

  describe('closed field', () => {
    it('is a combobox named by its label that shows the chosen label', async () => {
      const { field } = await setup();
      expect(field()).toHaveAccessibleName('Stadt');
      expect(field()).toHaveTextContent('Beta');
      expect(field()).toHaveAttribute('aria-haspopup', 'listbox');
      expect(field()).toHaveAttribute('aria-expanded', 'false');
      expect(screen.getByLabelText('Stadt')).toBe(field());
      expect(document.querySelector('select')).toBeNull();
    });

    it('shows the placeholder while no option is chosen', async () => {
      const { field } = await setup((h) => {
        h.value.set('');
        h.placeholder.set('Bitte wählen');
      });
      expect(field()).toHaveTextContent('Bitte wählen');
      expect(field().querySelector('.sel__value--empty')).not.toBeNull();
    });

    it('takes the aria-label when it has no visible label', async () => {
      const { field } = await setup((h) => {
        h.label.set('');
        h.ariaLabel.set('Ort');
      });
      expect(field()).toHaveAccessibleName('Ort');
    });

    it('marks a required field, and links the hint and the error', async () => {
      const { view, host, field } = await setup((h) => {
        h.required.set(true);
        h.hint.set('Nur eine');
      });
      expect(field()).toHaveAttribute('aria-required', 'true');
      expect(screen.getByText('*')).toHaveAttribute('aria-hidden', 'true');
      expect(field()).toHaveAccessibleDescription('Nur eine');
      host.error.set('Pflichtfeld');
      view.fixture.detectChanges();
      expect(field()).toHaveAttribute('aria-invalid', 'true');
      expect(field()).toHaveAccessibleDescription('Pflichtfeld');
      expect(screen.getByRole('alert')).toHaveTextContent('Pflichtfeld');
      expect(screen.queryByText('Nur eine')).toBeNull();
    });

    it('does not open while disabled', async () => {
      const { view, host, field } = await setup();
      host.disabled.set(true);
      view.fixture.detectChanges();
      await view.fixture.whenStable();
      view.fixture.detectChanges();
      expect(field()).toBeDisabled();
      fireEvent.click(field());
      fireEvent.keyDown(field(), { key: 'ArrowDown' });
      expect(screen.queryByRole('listbox')).toBeNull();
    });
  });

  describe('popover (desktop)', () => {
    it('opens on a click with the options, the chosen one checked and active', async () => {
      const { field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      const list = screen.getByRole('listbox', { name: 'Stadt' });
      expect(field()).toHaveAttribute('aria-expanded', 'true');
      expect(field()).toHaveAttribute('aria-controls', list.id);
      const names = within(list)
        .getAllByRole('option')
        .map((o) => o.textContent?.trim());
      expect(names).toEqual(['Alpha', 'Beta', 'Bremen', 'Berlin', 'Delta']);
      const beta = within(list).getByRole('option', { name: 'Beta' });
      expect(beta).toHaveAttribute('aria-selected', 'true');
      expect(beta.querySelector('app-icon')).not.toBeNull();
      expect(field()).toHaveAttribute('aria-activedescendant', beta.id);
      expect(within(list).getByRole('option', { name: 'Bremen' })).toHaveAttribute(
        'aria-disabled',
        'true',
      );
      // The focus stays on the field.
      expect(field()).toHaveFocus();
      // No native tooltip doubles a row text.
      expect(list.querySelector('[title]')).toBeNull();
    });

    it('reports a click on an option once, closes and keeps the focus', async () => {
      const { host, field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      await userEvent.click(screen.getByRole('option', { name: 'Delta' }));
      expect(host.changes).toEqual(['d']);
      expect(screen.queryByRole('listbox')).toBeNull();
      expect(field()).toHaveTextContent('Delta');
      expect(field()).toHaveFocus();
    });

    it('reports nothing when the chosen option is picked again', async () => {
      const { host, field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      await userEvent.click(screen.getByRole('option', { name: 'Beta' }));
      expect(host.changes).toEqual([]);
      expect(screen.queryByRole('listbox')).toBeNull();
    });

    it('ignores a click on a disabled option', async () => {
      const { host, field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      fireEvent.click(screen.getByRole('option', { name: 'Bremen' }));
      expect(host.changes).toEqual([]);
      expect(screen.getByRole('listbox')).toBeInTheDocument();
    });

    it('closes on a press outside without a change', async () => {
      const { host, field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));
      expect(screen.queryByRole('listbox')).toBeNull();
      expect(host.changes).toEqual([]);
    });

    it('closes again on a second click on the field', async () => {
      const { field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      await userEvent.click(field());
      expect(screen.queryByRole('listbox')).toBeNull();
    });

    it('places the list under the field, at least as wide as the field', async () => {
      const { view, field, tick } = await setup();
      const box = view.container.querySelector('.fld__box') as HTMLElement;
      box.getBoundingClientRect = () =>
        ({ top: 100, bottom: 156, left: 40, right: 340, width: 300, height: 56 }) as DOMRect;
      await userEvent.click(field());
      await tick();
      const menu = document.querySelector('.sel__menu') as HTMLElement;
      expect(menu.style.top).toBe('160px');
      expect(menu.style.left).toBe('40px');
      expect(menu.style.minWidth).toBe('300px');
      expect(menu).toHaveClass('sel__menu--placed');
    });

    it('flips above the field when the room below is too small', async () => {
      const { view, field, tick } = await setup();
      const box = view.container.querySelector('.fld__box') as HTMLElement;
      const bottom = window.innerHeight - 10;
      box.getBoundingClientRect = () =>
        ({ top: bottom - 56, bottom, left: 40, right: 340, width: 300, height: 56 }) as DOMRect;
      await userEvent.click(field());
      await tick();
      const menu = document.querySelector('.sel__menu') as HTMLElement;
      Object.defineProperty(menu, 'scrollHeight', { value: 200, configurable: true });
      // Re-place after a scroll of the page.
      window.dispatchEvent(new Event('scroll'));
      view.fixture.detectChanges();
      expect(parseFloat(menu.style.top)).toBe(bottom - 56 - 4 - 200);
    });

    it('closes when the field scrolls out of view', async () => {
      const { view, field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      const box = view.container.querySelector('.fld__box') as HTMLElement;
      box.getBoundingClientRect = () =>
        ({ top: -100, bottom: -44, left: 0, right: 300, width: 300, height: 56 }) as DOMRect;
      window.dispatchEvent(new Event('scroll'));
      view.fixture.detectChanges();
      expect(screen.queryByRole('listbox')).toBeNull();
    });

    it('has no axe violations, open and closed', async () => {
      const { view, field, tick } = await setup((h) => {
        h.options.set([
          { value: 'a', label: 'Alpha', group: 'Nord' },
          { value: 'b', label: 'Beta', group: 'Nord' },
          { value: 'c', label: 'Gamma', group: 'Süd' },
        ]);
        h.hint.set('Eine Stadt');
      });
      expect(await runAxe(view.container)).toHaveNoViolations();
      await userEvent.click(field());
      await tick();
      expect(await runAxe(document.body)).toHaveNoViolations();
    });
  });

  describe('keyboard', () => {
    it('Arrow Down opens on the chosen option; arrows skip a disabled one', async () => {
      const { field, tick } = await setup();
      field().focus();
      await userEvent.keyboard('{ArrowDown}');
      await tick();
      const active = () => document.getElementById(field().getAttribute('aria-activedescendant')!);
      expect(active()).toHaveTextContent('Beta');
      expect(active()).toHaveClass('sel__option--active');
      await userEvent.keyboard('{ArrowDown}');
      expect(active()).toHaveTextContent('Berlin');
      await userEvent.keyboard('{ArrowUp}');
      expect(active()).toHaveTextContent('Beta');
      await userEvent.keyboard('{End}');
      expect(active()).toHaveTextContent('Delta');
      await userEvent.keyboard('{ArrowDown}');
      expect(active()).toHaveTextContent('Delta');
      await userEvent.keyboard('{Home}');
      expect(active()).toHaveTextContent('Alpha');
      await userEvent.keyboard('{ArrowUp}');
      expect(active()).toHaveTextContent('Alpha');
      await userEvent.keyboard('{PageDown}');
      expect(active()).toHaveTextContent('Delta');
      await userEvent.keyboard('{PageUp}');
      expect(active()).toHaveTextContent('Alpha');
    });

    it('Enter chooses the active option and closes', async () => {
      const { host, field, tick } = await setup();
      field().focus();
      await userEvent.keyboard('{Enter}');
      await tick();
      expect(screen.getByRole('listbox')).toBeInTheDocument();
      await userEvent.keyboard('{ArrowDown}{Enter}');
      expect(host.changes).toEqual(['c']);
      expect(screen.queryByRole('listbox')).toBeNull();
      expect(field()).toHaveFocus();
    });

    it('Space opens and chooses; Alt+Arrow Up chooses too', async () => {
      const { host, field, tick } = await setup();
      field().focus();
      await userEvent.keyboard(' ');
      await tick();
      await userEvent.keyboard('{ArrowUp} ');
      expect(host.changes).toEqual(['a']);
      await userEvent.keyboard('{ArrowDown}');
      await tick();
      await userEvent.keyboard('{End}');
      fireEvent.keyDown(field(), { key: 'ArrowUp', altKey: true });
      expect(host.changes).toEqual(['a', 'd']);
      expect(screen.queryByRole('listbox')).toBeNull();
    });

    it('cancels the keyup of Space, so the button click does not toggle the list back', async () => {
      const { host, field, tick } = await setup();
      field().focus();
      fireEvent.keyDown(field(), { key: ' ' });
      await tick();
      const up = new KeyboardEvent('keyup', { key: ' ', bubbles: true, cancelable: true });
      field().dispatchEvent(up);
      expect(up.defaultPrevented).toBe(true);
      // user-event clicks a button on the keyup of Space unless it is prevented.
      await userEvent.keyboard(' ');
      await tick();
      expect(host.changes).toEqual([]);
      expect(screen.queryByRole('listbox')).toBeNull();
      await userEvent.keyboard(' ');
      await tick();
      expect(screen.getByRole('listbox')).toBeInTheDocument();
      await userEvent.keyboard('{ArrowDown} ');
      await tick();
      expect(host.changes).toEqual(['c']);
      expect(screen.queryByRole('listbox')).toBeNull();
    });

    it('Space chooses again once the type-ahead window has passed', async () => {
      const { host, field, tick } = await setup((h) => h.value.set('a'));
      field().focus();
      const now = jest.spyOn(Date, 'now');
      now.mockReturnValue(1000);
      await userEvent.keyboard('d');
      await tick();
      now.mockReturnValue(1200);
      await userEvent.keyboard(' ');
      expect(screen.getByRole('listbox')).toBeInTheDocument();
      expect(host.changes).toEqual([]);
      now.mockReturnValue(5000);
      await userEvent.keyboard(' ');
      await tick();
      expect(host.changes).toEqual(['d']);
      expect(screen.queryByRole('listbox')).toBeNull();
      now.mockRestore();
    });

    it('Escape closes without a change and does not reach a dialog around it', async () => {
      const { host, field, tick } = await setup();
      const outer = jest.fn();
      document.addEventListener('keydown', outer);
      field().focus();
      await userEvent.keyboard('{ArrowDown}');
      await tick();
      await userEvent.keyboard('{ArrowDown}{Escape}');
      expect(screen.queryByRole('listbox')).toBeNull();
      expect(host.changes).toEqual([]);
      expect(outer.mock.calls.some(([e]) => (e as KeyboardEvent).key === 'Escape')).toBe(false);
      expect(field()).toHaveFocus();
      document.removeEventListener('keydown', outer);
    });

    it('Tab closes without a change and leaves the focus free', async () => {
      const { host, field, tick } = await setup();
      field().focus();
      await userEvent.keyboard('{ArrowDown}');
      await tick();
      await userEvent.keyboard('{ArrowDown}');
      await userEvent.tab();
      expect(screen.queryByRole('listbox')).toBeNull();
      expect(host.changes).toEqual([]);
      expect(screen.getByRole('button', { name: 'Weiter' })).toHaveFocus();
    });

    it('Home and End open the list on the first and the last option', async () => {
      const { field, tick } = await setup();
      field().focus();
      await userEvent.keyboard('{End}');
      await tick();
      const active = () => document.getElementById(field().getAttribute('aria-activedescendant')!);
      expect(active()).toHaveTextContent('Delta');
      await userEvent.keyboard('{Escape}{Home}');
      await tick();
      expect(active()).toHaveTextContent('Alpha');
    });

    it('type-ahead opens on a match, cycles one letter and skips disabled options', async () => {
      const { field, tick } = await setup((h) => h.value.set('a'));
      field().focus();
      const now = jest.spyOn(Date, 'now');
      now.mockReturnValue(1000);
      await userEvent.keyboard('d');
      await tick();
      const active = () => document.getElementById(field().getAttribute('aria-activedescendant')!);
      expect(active()).toHaveTextContent('Delta');
      now.mockReturnValue(5000);
      await userEvent.keyboard('b');
      expect(active()).toHaveTextContent('Beta');
      now.mockReturnValue(5100);
      await userEvent.keyboard('b');
      expect(active()).toHaveTextContent('Berlin');
      now.mockReturnValue(9000);
      await userEvent.keyboard('b');
      now.mockReturnValue(9100);
      await userEvent.keyboard('e');
      now.mockReturnValue(9200);
      await userEvent.keyboard('r');
      expect(active()).toHaveTextContent('Berlin');
      now.mockReturnValue(20000);
      await userEvent.keyboard('z');
      expect(active()).toHaveTextContent('Berlin');
      now.mockRestore();
    });

    it('opens on the chosen option when a typed letter matches nothing', async () => {
      const { field, tick } = await setup();
      field().focus();
      await userEvent.keyboard('q');
      await tick();
      const active = document.getElementById(field().getAttribute('aria-activedescendant')!);
      expect(active).toHaveTextContent('Beta');
    });

    it('ignores Alt+Arrow Down and shortcuts while open', async () => {
      const { host, field, tick } = await setup();
      field().focus();
      await userEvent.keyboard('{ArrowDown}');
      await tick();
      const before = field().getAttribute('aria-activedescendant');
      fireEvent.keyDown(field(), { key: 'ArrowDown', altKey: true });
      fireEvent.keyDown(field(), { key: 'd', ctrlKey: true });
      expect(field().getAttribute('aria-activedescendant')).toBe(before);
      expect(host.changes).toEqual([]);
    });

    it('Page Down stops on the last enabled option', async () => {
      const { field, tick } = await setup((h) =>
        h.options.set([...OPTIONS, { value: 'z', label: 'Zeta', disabled: true }]),
      );
      field().focus();
      await userEvent.keyboard('{ArrowDown}');
      await tick();
      await userEvent.keyboard('{PageDown}');
      const active = document.getElementById(field().getAttribute('aria-activedescendant')!);
      expect(active).toHaveTextContent('Delta');
    });

    it('with only disabled options, moves nowhere and Enter only closes', async () => {
      const { host, field, tick } = await setup((h) =>
        h.options.set([{ value: 'x', label: 'Aus', disabled: true }]),
      );
      field().focus();
      await userEvent.keyboard('{ArrowDown}');
      await tick();
      expect(field()).not.toHaveAttribute('aria-activedescendant');
      await userEvent.keyboard('{ArrowDown}{Enter}');
      expect(screen.queryByRole('listbox')).toBeNull();
      expect(host.changes).toEqual([]);
    });

    it('shows the popover in the top layer and scrolls the active row into view', async () => {
      const proto = HTMLElement.prototype as HTMLElement & {
        showPopover?: () => void;
        scrollIntoView?: (arg?: ScrollIntoViewOptions) => void;
      };
      const show = jest.fn();
      const scroll = jest.fn();
      proto.showPopover = show;
      proto.scrollIntoView = scroll;
      try {
        const { field, tick } = await setup();
        field().focus();
        await userEvent.keyboard('{ArrowDown}');
        await tick();
        expect(show).toHaveBeenCalled();
        await userEvent.keyboard('{End}');
        expect(scroll).toHaveBeenLastCalledWith({ block: 'nearest' });
      } finally {
        delete proto.showPopover;
        delete proto.scrollIntoView;
      }
    });

    it('a pointer over a row moves the active row without the keyboard ring', async () => {
      const { field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      const delta = screen.getByRole('option', { name: 'Delta' });
      fireEvent.pointerMove(delta);
      expect(field()).toHaveAttribute('aria-activedescendant', delta.id);
      expect(delta).not.toHaveClass('sel__option--active');
      fireEvent.pointerMove(screen.getByRole('option', { name: 'Bremen' }));
      expect(field()).toHaveAttribute('aria-activedescendant', delta.id);
    });
  });

  describe('placeholder row', () => {
    it('clears the value while the field is not required', async () => {
      const { host, field, tick } = await setup((h) => h.placeholder.set('Keine'));
      await userEvent.click(field());
      await tick();
      const row = screen.getByRole('option', { name: 'Keine' });
      expect(row).toHaveAttribute('aria-selected', 'false');
      await userEvent.click(row);
      expect(host.changes).toEqual(['']);
      expect(field()).toHaveTextContent('Keine');
    });

    it('opens on the placeholder row while the value is empty', async () => {
      const { field, tick } = await setup((h) => {
        h.placeholder.set('Keine');
        h.value.set('');
      });
      field().focus();
      await userEvent.keyboard('{ArrowDown}');
      await tick();
      const active = document.getElementById(field().getAttribute('aria-activedescendant')!);
      expect(active).toHaveTextContent('Keine');
      expect(active).toHaveAttribute('aria-selected', 'true');
    });

    it('has no row while the field is required', async () => {
      const { field, tick } = await setup((h) => {
        h.placeholder.set('Keine');
        h.required.set(true);
      });
      await userEvent.click(field());
      await tick();
      expect(screen.queryByRole('option', { name: 'Keine' })).toBeNull();
    });

    it('shows the empty text without any option', async () => {
      const { field, tick } = await setup((h) => h.options.set([]));
      await userEvent.click(field());
      await tick();
      expect(screen.queryByRole('listbox')).toBeNull();
      expect(document.querySelector('.sel__empty')).not.toBeNull();
    });
  });

  describe('groups', () => {
    it('renders a labelled group per heading', async () => {
      const { field, tick } = await setup((h) =>
        h.options.set([
          { value: 'a', label: 'Alpha' },
          { value: 'b', label: 'Beta', group: 'Nord' },
          { value: 'c', label: 'Gamma', group: 'Nord' },
          { value: 'd', label: 'Delta', group: 'Süd' },
        ]),
      );
      await userEvent.click(field());
      await tick();
      const nord = screen.getByRole('group', { name: 'Nord' });
      expect(within(nord).getAllByRole('option')).toHaveLength(2);
      expect(within(screen.getByRole('group', { name: 'Süd' })).getByRole('option')).toHaveTextContent(
        'Delta',
      );
    });
  });

  describe('forms', () => {
    it('works with a reactive form: value, touched and disabled', async () => {
      const view = await render(ReactiveHost);
      const { control } = view.fixture.componentInstance;
      const field = screen.getByRole('combobox', { name: 'Art' });
      expect(control.valid).toBe(false);
      control.setValue('c');
      view.fixture.detectChanges();
      expect(field).toHaveTextContent('Berlin');
      await userEvent.click(field);
      await new Promise((r) => setTimeout(r));
      view.fixture.detectChanges();
      expect(control.touched).toBe(false);
      await userEvent.click(screen.getByRole('option', { name: 'Alpha' }));
      expect(control.value).toBe('a');
      expect(control.touched).toBe(true);
      control.disable();
      view.fixture.detectChanges();
      expect(field).toBeDisabled();
    });

    it('marks the control touched when the focus leaves the closed field', async () => {
      const view = await render(ReactiveHost);
      const { control } = view.fixture.componentInstance;
      screen.getByRole('combobox').focus();
      screen.getByRole('combobox').blur();
      expect(control.touched).toBe(true);
    });

    it('treats a null value as no choice', async () => {
      const view = await render(ReactiveHost);
      const { control } = view.fixture.componentInstance;
      (control as unknown as FormControl<string | null>).setValue(null);
      view.fixture.detectChanges();
      expect(screen.getByRole('combobox')).toHaveTextContent('');
    });

    it('binds a signal two-way', async () => {
      const view = await render(SignalHost);
      const host = view.fixture.componentInstance;
      await userEvent.click(screen.getByRole('combobox', { name: 'Signal' }));
      await new Promise((r) => setTimeout(r));
      view.fixture.detectChanges();
      await userEvent.click(screen.getByRole('option', { name: 'Delta' }));
      expect(host.choice()).toBe('d');
    });
  });

  it('closes the list when the viewport crosses the phone limit', async () => {
    let listener: ((e: { matches: boolean }) => void) | null = null;
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => {
        if (query.includes('max-width')) listener = fn;
      },
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
    const { view, field, tick } = await setup();
    await userEvent.click(field());
    await tick();
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    listener!({ matches: true });
    view.fixture.detectChanges();
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(field()).toHaveAttribute('aria-expanded', 'false');
  });

  describe('bottom sheet (phone)', () => {
    beforeEach(() => setPhone(true));

    it('opens the list in the shared bottom sheet with the focus on the listbox', async () => {
      const { field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      await tick();
      const sheet = screen.getByRole('dialog', { name: 'Stadt' });
      const list = within(sheet).getByRole('listbox');
      expect(list).toHaveFocus();
      expect(list).toHaveAttribute('aria-activedescendant', screen.getByRole('option', { name: 'Beta' }).id);
      expect(document.querySelector('.sel__menu')).toBeNull();
      expect(field()).not.toHaveAttribute('aria-activedescendant');
    });

    it('chooses with the keyboard in the sheet and returns the focus to the field', async () => {
      const { host, field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      await tick();
      await userEvent.keyboard('{ArrowDown}{Enter}');
      expect(host.changes).toEqual(['c']);
      expect(screen.queryByRole('dialog')).toBeNull();
      await tick();
      expect(field()).toHaveFocus();
    });

    it('leaves Escape to the sheet, which closes without a change', async () => {
      const { host, field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      await tick();
      await userEvent.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(host.changes).toEqual([]);
    });

    it('names the sheet by the placeholder without a label, and closes by its button', async () => {
      const { host, field, tick } = await setup((h) => {
        h.label.set('');
        h.placeholder.set('Ort wählen');
      });
      await userEvent.click(field());
      await tick();
      await tick();
      const sheet = screen.getByRole('dialog', { name: 'Ort wählen' });
      await userEvent.click(within(sheet).getAllByRole('button')[0]);
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(host.changes).toEqual([]);
    });

    it('chooses with a tap on a row', async () => {
      const { host, field, tick } = await setup();
      await userEvent.click(field());
      await tick();
      await userEvent.click(screen.getByRole('option', { name: 'Alpha' }));
      expect(host.changes).toEqual(['a']);
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });
});
