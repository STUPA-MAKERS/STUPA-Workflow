import { Component, signal } from '@angular/core';
import { fireEvent, render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from './row-menu.component';

const SECTIONS: RowMenuSection[] = [
  { label: 'Übergänge', items: [{ id: 'review', label: 'Prüfung beginnen', icon: 'play' }] },
  {
    items: [
      { id: 'open', label: 'Öffnen', icon: 'ext' },
      { id: 'archive', label: 'Archivieren', icon: 'archive', disabledReason: 'Erst entscheiden.' },
      { id: 'np', label: 'Nicht öffentlich', icon: 'lock', checked: true },
    ],
  },
  { items: [] },
  { items: [{ id: 'delete', label: 'Löschen', icon: 'trash', danger: true }] },
];

@Component({
  standalone: true,
  imports: [RowMenuComponent],
  template: `
    <button type="button">davor</button>
    <app-row-menu
      [sections]="sections()"
      [loading]="loading()"
      (opened)="onOpened()"
      (closed)="closedCount = closedCount + 1"
      (selected)="chosen.push($event)"
    />
    <button type="button">danach</button>
  `,
})
class HostComponent {
  readonly sections = signal<readonly RowMenuSection[]>(SECTIONS);
  readonly loading = signal(false);
  opens = 0;
  closedCount = 0;
  chosen: RowMenuItem[] = [];
  lazy = false;

  onOpened(): void {
    this.opens++;
    if (this.lazy) {
      this.loading.set(true);
      this.sections.set([]);
    }
  }
}

async function setup(lazy = false) {
  const view = await render(HostComponent);
  view.fixture.componentInstance.lazy = lazy;
  const user = userEvent.setup();
  const trigger = screen.getByRole('button', { name: 'Weitere Aktionen' });
  return { view, host: view.fixture.componentInstance, user, trigger };
}

const items = () => document.querySelectorAll('[data-menu-item]');
/** The label of the focused item (without the visible reason of a disabled one), or its text. */
const focusedName = () => {
  const el = document.activeElement as HTMLElement | null;
  return (el?.querySelector('.rm__label') ?? el)?.textContent?.trim();
};

describe('RowMenuComponent', () => {
  afterEach(() => {
    jest.restoreAllMocks();
    delete (HTMLElement.prototype as Partial<{ showPopover: () => void }>).showPopover;
  });

  it('is a closed menu button by default', async () => {
    const { trigger } = await setup();
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).not.toHaveAttribute('aria-controls');
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('opens on a click, names the menu and focuses the first item', async () => {
    const { trigger, user, host } = await setup();
    await user.click(trigger);
    const menu = screen.getByRole('menu', { name: 'Weitere Aktionen' });
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(trigger).toHaveAttribute('aria-controls', menu.id);
    expect(host.opens).toBe(1);
    await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
  });

  it('draws the sections with captions, separators and a red destructive item', async () => {
    const { trigger, user } = await setup();
    await user.click(trigger);
    // The empty section is left out: three sections, two lines between them.
    expect(screen.getAllByRole('group')).toHaveLength(3);
    expect(screen.getAllByRole('separator')).toHaveLength(2);
    expect(screen.getByRole('group', { name: 'Übergänge' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Löschen' })).toHaveClass('rm__item--danger');
    const np = screen.getByRole('menuitemcheckbox', { name: 'Nicht öffentlich' });
    expect(np).toHaveAttribute('aria-checked', 'true');
  });

  it('keeps a disabled item, says why and does not run it', async () => {
    const { trigger, user, host } = await setup();
    await user.click(trigger);
    const item = screen.getByRole('menuitem', { name: 'Archivieren' });
    expect(item).toHaveAttribute('aria-disabled', 'true');
    expect(item).toHaveAttribute('title', 'Erst entscheiden.');
    expect(item).toHaveAccessibleDescription('Erst entscheiden.');
    // Visible in the item for a touch user, but not part of its name.
    expect(item.querySelector('.rm__reason')).toHaveTextContent('Erst entscheiden.');
    await user.click(item);
    expect(host.chosen).toEqual([]);
    expect(screen.getByRole('menu')).toBeInTheDocument();
  });

  it('gives each disabled reason its own id, also for a repeated or spaced item id', async () => {
    const { trigger, user, host, view } = await setup();
    host.sections.set([
      { label: 'Eins', items: [{ id: 'move x', label: 'Verschieben A', disabledReason: 'Grund A' }] },
      { label: 'Zwei', items: [{ id: 'move x', label: 'Verschieben B', disabledReason: 'Grund B' }] },
    ]);
    view.fixture.detectChanges();
    await user.click(trigger);
    const a = screen.getByRole('menuitem', { name: 'Verschieben A' });
    const b = screen.getByRole('menuitem', { name: 'Verschieben B' });
    expect(a).toHaveAccessibleDescription('Grund A');
    expect(b).toHaveAccessibleDescription('Grund B');
    const ids = [a, b].map((el) => el.getAttribute('aria-describedby'));
    expect(new Set(ids).size).toBe(2);
    for (const id of ids) expect(id).not.toMatch(/\s/);
  });

  it('runs an enabled item, closes and returns the focus to the button', async () => {
    const { trigger, user, host } = await setup();
    await user.click(trigger);
    await user.click(screen.getByRole('menuitem', { name: 'Löschen' }));
    expect(host.chosen.map((i) => i.id)).toEqual(['delete']);
    expect(host.closedCount).toBe(1);
    expect(screen.queryByRole('menu')).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it('closes on a second click of the button', async () => {
    const { trigger, user } = await setup();
    await user.click(trigger);
    await user.click(trigger);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  describe('keyboard', () => {
    it('opens on the first item with Arrow Down and on the last with Arrow Up', async () => {
      const { trigger, user } = await setup();
      trigger.focus();
      await user.keyboard('{ArrowDown}');
      await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
      await user.keyboard('{Escape}');
      expect(trigger).toHaveFocus();
      await user.keyboard('{ArrowUp}');
      await waitFor(() => expect(focusedName()).toBe('Löschen'));
    });

    it('moves the focus to the end or the start while the menu is open', async () => {
      const { trigger, user } = await setup();
      await user.click(trigger);
      trigger.focus();
      await user.keyboard('{ArrowUp}');
      await waitFor(() => expect(focusedName()).toBe('Löschen'));
    });

    it('opens with Enter and Space like any button', async () => {
      const { trigger, user } = await setup();
      trigger.focus();
      await user.keyboard('{Enter}');
      expect(screen.getByRole('menu')).toBeInTheDocument();
      await user.keyboard('{Escape}');
      await user.keyboard(' ');
      expect(screen.getByRole('menu')).toBeInTheDocument();
    });

    it('moves with the arrows, wraps, and jumps with Home and End', async () => {
      const { trigger, user } = await setup();
      await user.click(trigger);
      await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
      await user.keyboard('{ArrowDown}');
      expect(focusedName()).toBe('Öffnen');
      // The disabled item takes the focus too, so its reason can be read.
      await user.keyboard('{ArrowDown}');
      expect(focusedName()).toBe('Archivieren');
      await user.keyboard('{End}');
      expect(focusedName()).toBe('Löschen');
      await user.keyboard('{ArrowDown}');
      expect(focusedName()).toBe('Prüfung beginnen');
      await user.keyboard('{ArrowUp}');
      expect(focusedName()).toBe('Löschen');
      await user.keyboard('{Home}');
      expect(focusedName()).toBe('Prüfung beginnen');
      expect(items()).toHaveLength(5);
    });

    it('closes with Escape on the button', async () => {
      const { trigger, user } = await setup();
      await user.click(trigger);
      trigger.focus();
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('menu')).toBeNull();
      expect(trigger).toHaveFocus();
    });

    it('closes on Tab without pulling the focus back', async () => {
      const { trigger, user, host } = await setup();
      await user.click(trigger);
      await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
      await user.keyboard('{Tab}');
      expect(screen.queryByRole('menu')).toBeNull();
      expect(host.closedCount).toBe(1);
      expect(trigger).not.toHaveFocus();
    });

    it('ignores other keys', async () => {
      const { trigger, user } = await setup();
      trigger.focus();
      await user.keyboard('a');
      expect(screen.queryByRole('menu')).toBeNull();
      await user.click(trigger);
      await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
      await user.keyboard('a');
      expect(focusedName()).toBe('Prüfung beginnen');
    });
  });

  describe('lazy content', () => {
    it('asks for the items once per opening and focuses them when they arrive', async () => {
      const { trigger, user, host, view } = await setup(true);
      await user.click(trigger);
      expect(host.opens).toBe(1);
      const menu = screen.getByRole('menu');
      expect(menu).toHaveAttribute('aria-busy', 'true');
      expect(screen.getByRole('status')).toHaveTextContent('Wird geladen');
      await waitFor(() => expect(menu).toHaveFocus());

      host.sections.set(SECTIONS);
      host.loading.set(false);
      view.fixture.detectChanges();
      expect(menu).not.toHaveAttribute('aria-busy');
      await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
      expect(host.opens).toBe(1);

      await user.keyboard('{Escape}');
      await user.click(trigger);
      expect(host.opens).toBe(2);
    });

    it('keeps the focus where it is when the items go away later', async () => {
      const { trigger, user, host, view } = await setup();
      await user.click(trigger);
      await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
      host.sections.set([]);
      view.fixture.detectChanges();
      await new Promise((r) => setTimeout(r));
      expect(screen.getByRole('menu')).toHaveTextContent('Keine Aktionen möglich');
      expect(screen.getByRole('menu')).not.toHaveFocus();
    });

    it('drops a pending focus when it is destroyed while open', async () => {
      const { trigger, view } = await setup();
      trigger.click();
      view.fixture.destroy();
      await new Promise((r) => setTimeout(r));
      expect(document.querySelector('[role="menu"]')).toBeNull();
    });

    it('says so when there is no action', async () => {
      const { trigger, user, host, view } = await setup();
      host.sections.set([{ items: [] }]);
      view.fixture.detectChanges();
      await user.click(trigger);
      expect(screen.getByRole('menu')).toHaveTextContent('Keine Aktionen möglich');
      await waitFor(() => expect(screen.getByRole('menu')).toHaveFocus());
    });
  });

  describe('closing from outside', () => {
    it('closes on a pointer down outside, but not inside', async () => {
      const { trigger, user, host } = await setup();
      await user.click(trigger);
      fireEvent.pointerDown(screen.getByRole('menu'));
      expect(screen.getByRole('menu')).toBeInTheDocument();
      fireEvent.pointerDown(document.body);
      expect(screen.queryByRole('menu')).toBeNull();
      expect(host.closedCount).toBe(1);
      expect(trigger).not.toHaveFocus();
    });

    it('follows its button when the page scrolls or resizes', async () => {
      const { trigger, user } = await setup();
      const rect = jest.spyOn(trigger, 'getBoundingClientRect');
      rect.mockReturnValue({ top: 100, bottom: 140, right: 900 } as DOMRect);
      await user.click(trigger);
      const menu = screen.getByRole('menu');
      expect(menu.style.top).toBe('144px');
      rect.mockReturnValue({ top: 60, bottom: 100, right: 900 } as DOMRect);
      fireEvent.scroll(window);
      expect(menu.style.top).toBe('104px');
      rect.mockReturnValue({ top: 20, bottom: 60, right: 800 } as DOMRect);
      fireEvent(window, new Event('resize'));
      expect(menu.style.top).toBe('64px');
      expect(menu.style.right).toBe(`${window.innerWidth - 800}px`);
      expect(screen.getByRole('menu')).toBe(menu);
    });

    it('copes with a scroll between the opening and the first render', async () => {
      const view = await render(RowMenuComponent, {
        inputs: { sections: SECTIONS },
        on: { opened: () => fireEvent.scroll(window) },
      });
      await userEvent.setup().click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
      expect(screen.getByRole('menu')).toBeInTheDocument();
      expect(view.container).toBeTruthy();
    });

    it('stays put on a scroll inside the menu', async () => {
      const { trigger, user } = await setup();
      const rect = jest.spyOn(trigger, 'getBoundingClientRect');
      rect.mockReturnValue({ top: 100, bottom: 140, right: 900 } as DOMRect);
      await user.click(trigger);
      rect.mockReturnValue({ top: 0, bottom: 40, right: 900 } as DOMRect);
      fireEvent.scroll(screen.getByRole('menu'));
      expect(screen.getByRole('menu').style.top).toBe('144px');
    });

    it('closes when its button scrolls out of view, above or below', async () => {
      const { trigger, user, host } = await setup();
      const rect = jest.spyOn(trigger, 'getBoundingClientRect');
      rect.mockReturnValue({ top: 100, bottom: 140, right: 900 } as DOMRect);
      await user.click(trigger);
      rect.mockReturnValue({ top: -60, bottom: -20, right: 900 } as DOMRect);
      fireEvent.scroll(window);
      expect(screen.queryByRole('menu')).toBeNull();
      rect.mockReturnValue({ top: 100, bottom: 140, right: 900 } as DOMRect);
      await user.click(trigger);
      rect.mockReturnValue({ top: window.innerHeight + 10, bottom: window.innerHeight + 50, right: 900 } as DOMRect);
      fireEvent.scroll(window);
      expect(screen.queryByRole('menu')).toBeNull();
      expect(host.closedCount).toBe(2);
      expect(trigger).not.toHaveFocus();
    });

    it('ignores outside events while closed', async () => {
      const { host } = await setup();
      fireEvent.pointerDown(document.body);
      fireEvent.scroll(window);
      expect(host.closedCount).toBe(0);
    });
  });

  describe('placement', () => {
    it('sits below the button, aligned to its end', async () => {
      const { trigger, user } = await setup();
      jest.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
        top: 100, bottom: 140, left: 900, right: 940, width: 40, height: 40, x: 900, y: 100,
        toJSON: () => ({}),
      });
      await user.click(trigger);
      const menu = screen.getByRole('menu');
      expect(menu.style.top).toBe('144px');
      expect(menu.style.right).toBe(`${window.innerWidth - 940}px`);
    });

    it('opens upwards when there is no room below', async () => {
      const { trigger, user } = await setup();
      const rect = (top: number, height: number) => ({
        top, bottom: top + height, left: 0, right: 40, width: 40, height, x: 0, y: top,
        toJSON: () => ({}),
      });
      jest.spyOn(trigger, 'getBoundingClientRect').mockReturnValue(rect(600, 40));
      const spy = jest
        .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
        .mockReturnValue(rect(0, 300));
      await user.click(trigger);
      const menu = screen.getByRole('menu');
      await waitFor(() => expect(menu.style.top).toBe('296px'));
      spy.mockRestore();
    });

    it('stays below when it fits', async () => {
      const { trigger, user } = await setup();
      await user.click(trigger);
      await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
      expect(screen.getByRole('menu').style.top).toBe('4px');
    });

    it('stays below when there is no room above either', async () => {
      const { trigger, user } = await setup();
      const rect = (top: number, height: number) => ({
        top, bottom: top + height, left: 0, right: 40, width: 40, height, x: 0, y: top,
        toJSON: () => ({}),
      });
      jest.spyOn(trigger, 'getBoundingClientRect').mockReturnValue(rect(100, 40));
      const spy = jest
        .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
        .mockReturnValue(rect(0, 5000));
      await user.click(trigger);
      await waitFor(() => expect(focusedName()).toBe('Prüfung beginnen'));
      expect(screen.getByRole('menu').style.top).toBe('144px');
      spy.mockRestore();
    });

    it('shows the menu in the top layer where the browser has popovers', async () => {
      const show = jest.fn();
      (HTMLElement.prototype as Partial<{ showPopover: () => void }>).showPopover = show;
      // jsdom does not know the `:popover-open` selector; answer it, pass the rest on.
      const original = Element.prototype.matches;
      jest.spyOn(Element.prototype, 'matches').mockImplementation(function (this: Element, sel) {
        return sel === ':popover-open' ? false : original.call(this, sel);
      });
      const { trigger, user } = await setup();
      await user.click(trigger);
      await waitFor(() => expect(show).toHaveBeenCalledTimes(1));
    });
  });

  it('takes a custom name and icon', async () => {
    await render(RowMenuComponent, {
      inputs: { label: 'Aktionen für Druckkosten', icon: 'tune' },
    });
    const trigger = screen.getByRole('button', { name: 'Aktionen für Druckkosten' });
    expect(trigger.querySelector('[data-icon="tune"]')).toBeTruthy();
  });

  it('shows a text instead of the icon and opens at the start edge of its button', async () => {
    const user = userEvent.setup();
    await render(RowMenuComponent, {
      inputs: { label: 'Weitere Ebenen', text: '…', align: 'start', sections: SECTIONS },
    });
    const trigger = screen.getByRole('button', { name: 'Weitere Ebenen' });
    expect(trigger.classList).toContain('rm__trigger--text');
    expect(trigger.textContent?.trim()).toBe('…');
    expect(trigger.querySelector('app-icon')).toBeNull();
    jest.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      top: 100, bottom: 128, left: 300, right: 328, width: 28, height: 28, x: 300, y: 100,
      toJSON: () => ({}),
    });
    await user.click(trigger);
    const menu = screen.getByRole('menu');
    expect(menu.style.top).toBe('132px');
    expect(menu.style.left).toBe('300px');
    expect(menu.style.right).toBe('');
  });

  it('keeps a start-aligned menu off the left edge of the viewport', async () => {
    const user = userEvent.setup();
    await render(RowMenuComponent, { inputs: { text: '…', align: 'start', sections: SECTIONS } });
    const trigger = screen.getByRole('button', { name: 'Weitere Aktionen' });
    jest.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      top: 0, bottom: 28, left: 2, right: 30, width: 28, height: 28, x: 2, y: 0,
      toJSON: () => ({}),
    });
    await user.click(trigger);
    expect(screen.getByRole('menu').style.left).toBe('8px');
  });

  it('has no a11y violations, closed or open', async () => {
    const { trigger, user, view } = await setup();
    expect(await runAxe(view.container)).toHaveNoViolations();
    await user.click(trigger);
    expect(await runAxe(view.container)).toHaveNoViolations();
  });
});
