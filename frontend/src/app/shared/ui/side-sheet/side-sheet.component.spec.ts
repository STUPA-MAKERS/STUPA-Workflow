import { Component, signal } from '@angular/core';
import { DialogComponent } from '@stupa-makers/ui-kit';
import { fireEvent, render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { SideSheetComponent, type SheetSide } from './side-sheet.component';

@Component({
  standalone: true,
  imports: [SideSheetComponent],
  template: `
    <button type="button" (click)="open.set(true)">Anwesenheit</button>
    <app-side-sheet
      heading="Anwesenheit"
      [side]="side()"
      [contentScrolls]="contentScrolls()"
      [(open)]="open"
      (closed)="closes = closes + 1"
    >
      @if (withActions) {
        <button sheet-actions type="button">Zurücksetzen</button>
      }
      @if (withContent) {
        <input aria-label="Mitglied suchen" />
        <button type="button">Speichern</button>
      }
    </app-side-sheet>
  `,
})
class HostComponent {
  readonly open = signal(false);
  readonly side = signal<SheetSide>('end');
  readonly contentScrolls = signal(false);
  closes = 0;
  withActions = true;
  withContent = true;
}

@Component({
  standalone: true,
  imports: [SideSheetComponent, DialogComponent],
  template: `
    <button type="button" (click)="open.set(true)">Kommentare</button>
    <app-side-sheet heading="Kommentare" [(open)]="open" (closed)="closes = closes + 1">
      <button type="button" (click)="ask.set(true)">Löschen</button>
      <input aria-label="Nachricht" (keydown.escape)="$event.preventDefault()" />
      <app-dialog title="Kommentar löschen?" [open]="ask()" (closed)="ask.set(false)">
        <input aria-label="Grund" />
        <button type="button">Endgültig löschen</button>
      </app-dialog>
    </app-side-sheet>
  `,
})
class NestedHostComponent {
  readonly open = signal(false);
  readonly ask = signal(false);
  closes = 0;
}

async function setup(configure?: (h: HostComponent) => void) {
  const view = await render(HostComponent, {
    configureTestBed: () => undefined,
  });
  const host = view.fixture.componentInstance;
  configure?.(host);
  view.fixture.detectChanges();
  const user = userEvent.setup();
  const opener = screen.getByRole('button', { name: 'Anwesenheit' });
  return { view, host, user, opener };
}

describe('SideSheetComponent', () => {
  afterEach(() => {
    document.body.style.overflow = '';
  });

  it('renders nothing while closed', async () => {
    await setup();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens as a named modal dialog and moves the focus into it', async () => {
    const { user, opener, view } = await setup();
    await user.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Anwesenheit' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveClass('ss', 'ss--end');
    expect(document.body.style.overflow).toBe('hidden');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Zurücksetzen' })).toHaveFocus(),
    );
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('closes on Escape, gives the focus back and frees the page', async () => {
    const { user, opener, host } = await setup();
    document.body.style.overflow = 'auto';
    await user.click(opener);
    await waitFor(() => expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(host.open()).toBe(false);
    expect(host.closes).toBe(1);
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe('auto');
  });

  it('leaves Escape and Tab to a dialog inside the sheet, and to a field that took the Escape', async () => {
    const view = await render(NestedHostComponent);
    const host = view.fixture.componentInstance;
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Kommentare' }));
    const sheet = screen.getByRole('dialog', { name: 'Kommentare' });
    await waitFor(() => expect(sheet).toContainElement(document.activeElement as HTMLElement));
    await user.click(screen.getByRole('button', { name: 'Löschen' }));
    view.fixture.detectChanges();
    const ask = await screen.findByRole('dialog', { name: 'Kommentar löschen?' });
    const reason = screen.getByRole('textbox', { name: 'Grund' });
    const confirm = screen.getByRole('button', { name: 'Endgültig löschen' });
    await waitFor(() => expect(ask).toContainElement(document.activeElement as HTMLElement));
    // Tab from the last control of the dialog wraps inside the dialog, not to the sheet.
    confirm.focus();
    await user.tab();
    expect(ask).toContainElement(document.activeElement as HTMLElement);
    expect(sheet.querySelector('.ss__close, [aria-label="Schließen"]')).not.toHaveFocus();
    reason.focus();
    await user.keyboard('{Escape}');
    view.fixture.detectChanges();
    expect(screen.queryByRole('dialog', { name: 'Kommentar löschen?' })).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Kommentare' })).toBeInTheDocument();
    expect(host.open()).toBe(true);
    expect(host.closes).toBe(0);
    // A field that handles Escape itself keeps the sheet open as well.
    screen.getByRole('textbox', { name: 'Nachricht' }).focus();
    await user.keyboard('{Escape}');
    expect(host.closes).toBe(0);
    // Escape on the sheet itself still closes it.
    screen.getByRole('button', { name: 'Löschen' }).focus();
    await user.keyboard('{Escape}');
    expect(host.closes).toBe(1);
  });

  it('closes on the close button and on the scrim', async () => {
    const { user, opener, host, view } = await setup();
    await user.click(opener);
    await user.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(host.closes).toBe(1);
    await user.click(opener);
    await user.click(view.container.querySelector('.ss__scrim') as HTMLElement);
    expect(host.closes).toBe(2);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('keeps Tab inside the sheet in both directions', async () => {
    const { user, opener } = await setup();
    await user.click(opener);
    const first = screen.getByRole('button', { name: 'Zurücksetzen' });
    const last = screen.getByRole('button', { name: 'Speichern' });
    await waitFor(() => expect(first).toHaveFocus());
    await user.tab({ shift: true });
    expect(last).toHaveFocus();
    await user.tab();
    expect(first).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Schließen' })).toHaveFocus();
    await user.keyboard('a');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('wraps from the pane itself on Shift+Tab', async () => {
    const { user, opener } = await setup();
    await user.click(opener);
    const dialog = screen.getByRole('dialog');
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    dialog.focus();
    await user.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Speichern' })).toHaveFocus();
  });

  it('keeps Tab on the only control, or on the pane when there is none', async () => {
    const { host, view, user } = await setup((h) => {
      h.withActions = false;
      h.withContent = false;
    });
    host.open.set(true);
    view.fixture.detectChanges();
    const dialog = screen.getByRole('dialog');
    const close = screen.getByRole('button', { name: 'Schließen' });
    // The close button is the only control: Tab stays on it.
    await waitFor(() => expect(close).toHaveFocus());
    await user.tab();
    expect(close).toHaveFocus();
    // Remove it to check the empty case.
    close.remove();
    dialog.focus();
    await user.tab();
    expect(dialog).toHaveFocus();
  });

  it('opens from the start and from the bottom', async () => {
    const { host, view } = await setup();
    host.side.set('start');
    host.open.set(true);
    view.fixture.detectChanges();
    expect(screen.getByRole('dialog')).toHaveClass('ss--start');
    host.side.set('bottom');
    view.fixture.detectChanges();
    expect(screen.getByRole('dialog')).toHaveClass('ss--bottom');
  });

  it('lets the content scroll by itself when asked', async () => {
    const { host, view } = await setup();
    host.open.set(true);
    view.fixture.detectChanges();
    const body = screen.getByRole('dialog').querySelector('.ss__body') as HTMLElement;
    expect(body).not.toHaveClass('ss__body--fill');
    host.contentScrolls.set(true);
    view.fixture.detectChanges();
    expect(body).toHaveClass('ss__body--fill');
  });

  describe('the bottom sheet', () => {
    async function openBottom() {
      const view = await setup((h) => h.side.set('bottom'));
      view.host.open.set(true);
      view.view.fixture.detectChanges();
      const dialog = screen.getByRole('dialog');
      const top = dialog.querySelector('.ss__top') as HTMLElement;
      return { ...view, dialog, top };
    }
    const pointer = (
      y: number,
      time: number,
      extra: Partial<{ pointerId: number; isPrimary: boolean }> = {},
    ) => ({
      pointerId: 1,
      isPrimary: true,
      button: 0,
      clientY: y,
      timeStamp: time,
      ...extra,
    });
    /**
     * jsdom has no PointerEvent: the spec builds a mouse event and adds the pointer
     * fields, and the time, which no init sets.
     */
    function firePointer(el: HTMLElement, type: string, init: ReturnType<typeof pointer>): void {
      const { pointerId, isPrimary, timeStamp, clientY, button } = init;
      const event = new MouseEvent(type, { bubbles: true, clientY, button: button as number });
      Object.defineProperties(event, {
        pointerId: { value: pointerId },
        isPrimary: { value: isPrimary },
        timeStamp: { value: timeStamp },
      });
      fireEvent(el, event);
    }

    it('has a handle, the handle only there', async () => {
      const { dialog, host, view } = await openBottom();
      expect(dialog.querySelector('.ss__handle')).not.toBeNull();
      host.side.set('end');
      view.fixture.detectChanges();
      expect(dialog.querySelector('.ss__handle')).toBeNull();
    });

    it('follows a swipe down and closes after a long way', async () => {
      const { dialog, top, host, view } = await openBottom();
      firePointer(top, 'pointerdown', pointer(100, 0));
      firePointer(top, 'pointermove', pointer(160, 400));
      view.fixture.detectChanges();
      expect(dialog).toHaveClass('ss--dragging');
      expect(dialog.style.transform).toBe('translateY(60px)');
      // Up past its place: the sheet stays where it is.
      firePointer(top, 'pointermove', pointer(40, 500));
      view.fixture.detectChanges();
      expect(dialog.style.transform).toBe('');
      firePointer(top, 'pointerup', pointer(300, 1000));
      view.fixture.detectChanges();
      expect(host.open()).toBe(false);
      expect(host.closes).toBe(1);
    });

    it('closes on a quick flick and snaps back after a slow short pull', async () => {
      const { dialog, top, host, view } = await openBottom();
      firePointer(top, 'pointerdown', pointer(100, 0));
      firePointer(top, 'pointerup', pointer(150, 2000));
      view.fixture.detectChanges();
      expect(host.open()).toBe(true);
      expect(dialog).not.toHaveClass('ss--dragging');
      expect(dialog.style.transform).toBe('');
      firePointer(top, 'pointerdown', pointer(100, 0));
      firePointer(top, 'pointercancel', pointer(400, 10));
      expect(host.open()).toBe(true);
      firePointer(top, 'pointerdown', pointer(100, 0));
      firePointer(top, 'pointerup', pointer(150, 50));
      view.fixture.detectChanges();
      expect(host.open()).toBe(false);
    });

    it('starts no swipe on a control, a side sheet or a second pointer', async () => {
      const { top, host, view } = await openBottom();
      const close = screen.getByRole('button', { name: 'Schließen' });
      firePointer(close, 'pointerdown', pointer(100, 0));
      firePointer(top, 'pointerup', pointer(400, 10));
      firePointer(top, 'pointerdown', pointer(100, 0, { isPrimary: false }));
      firePointer(top, 'pointerup', pointer(400, 10));
      firePointer(top, 'pointerdown', pointer(100, 0));
      firePointer(top, 'pointermove', pointer(400, 10, { pointerId: 2 }));
      firePointer(top, 'pointerup', pointer(400, 10, { pointerId: 2 }));
      expect(host.open()).toBe(true);
      host.side.set('end');
      view.fixture.detectChanges();
      firePointer(top, 'pointerdown', pointer(100, 0, { pointerId: 3 }));
      firePointer(top, 'pointerup', pointer(400, 10, { pointerId: 3 }));
      expect(host.open()).toBe(true);
    });

    it('fades an end of the body only where more content is hidden', async () => {
      const { dialog, view } = await openBottom();
      const body = dialog.querySelector('.ss__body') as HTMLElement;
      Object.defineProperty(body, 'scrollHeight', { value: 600 });
      Object.defineProperty(body, 'clientHeight', { value: 300 });
      body.scrollTop = 0;
      fireEvent.scroll(body);
      view.fixture.detectChanges();
      expect(body).not.toHaveClass('ss__body--fadeTop');
      expect(body).toHaveClass('ss__body--fadeBottom');
      body.scrollTop = 150;
      fireEvent.scroll(body);
      view.fixture.detectChanges();
      expect(body).toHaveClass('ss__body--fadeTop', 'ss__body--fadeBottom');
      body.scrollTop = 300;
      fireEvent.scroll(body);
      view.fixture.detectChanges();
      expect(body).toHaveClass('ss__body--fadeTop');
      expect(body).not.toHaveClass('ss__body--fadeBottom');
    });

    it('measures the body once it is open and watches its size', async () => {
      const observed: Element[] = [];
      const original = globalThis.ResizeObserver;
      let fire: () => void = () => undefined;
      Object.defineProperty(globalThis, 'ResizeObserver', {
        writable: true,
        value: class {
          constructor(cb: () => void) {
            fire = cb;
          }
          observe(el: Element): void {
            observed.push(el);
          }
          disconnect(): void {}
        },
      });
      try {
        const { dialog, host, view } = await openBottom();
        const body = dialog.querySelector('.ss__body') as HTMLElement;
        await waitFor(() => expect(observed).toContain(body));
        Object.defineProperty(body, 'scrollHeight', { value: 900 });
        Object.defineProperty(body, 'clientHeight', { value: 300 });
        fire();
        view.fixture.detectChanges();
        expect(body).toHaveClass('ss__body--fadeBottom');
        host.open.set(false);
        view.fixture.detectChanges();
      } finally {
        Object.defineProperty(globalThis, 'ResizeObserver', { writable: true, value: original });
      }
    });
  });

  it('does not emit closed when the page closes it', async () => {
    const { host, view, user, opener } = await setup();
    await user.click(opener);
    host.open.set(false);
    view.fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(host.closes).toBe(0);
  });

  it('frees the page when it is destroyed while open', async () => {
    const { user, opener, view } = await setup();
    await user.click(opener);
    expect(document.body.style.overflow).toBe('hidden');
    view.fixture.destroy();
    expect(document.body.style.overflow).toBe('');
  });

  it('leaves the focus alone when the opener is gone', async () => {
    const { user, opener, host, view } = await setup();
    await user.click(opener);
    opener.remove();
    host.open.set(false);
    view.fixture.detectChanges();
    expect(document.activeElement).not.toBe(opener);
  });

  describe('shown', () => {
    const sheetOf = (view: Awaited<ReturnType<typeof setup>>['view']) =>
      view.fixture.debugElement.query((d) => d.name === 'app-side-sheet')
        .componentInstance as SideSheetComponent;
    type Leave = { leave(event: { target: Element; animationComplete: () => void }): void };

    it('is true from the opening and false once the pane is gone', async () => {
      const { view, host } = await setup();
      const sheet = sheetOf(view);
      expect(sheet.shown()).toBe(false);
      host.open.set(true);
      view.fixture.detectChanges();
      expect(sheet.shown()).toBe(true);
      host.open.set(false);
      view.fixture.detectChanges();
      await new Promise((resolve) => setTimeout(resolve));
      expect(sheet.shown()).toBe(false);
    });

    it('stays true while the pane slides out and turns false at its end', async () => {
      const { view, host } = await setup();
      const sheet = sheetOf(view);
      host.open.set(true);
      view.fixture.detectChanges();
      // Closed, but no change detection yet: only the leave animation can end `shown`.
      sheet.open.set(false);
      let finish!: () => void;
      const pane = document.createElement('div');
      Object.assign(pane, {
        getAnimations: () => [{ finished: new Promise<void>((resolve) => (finish = resolve)) }],
      });
      const animationComplete = jest.fn();
      (sheet as unknown as Leave).leave({ target: pane, animationComplete });
      expect(pane).toHaveClass('ss--leaving');
      await Promise.resolve();
      expect(sheet.shown()).toBe(true);
      expect(animationComplete).not.toHaveBeenCalled();
      finish();
      await waitFor(() => expect(animationComplete).toHaveBeenCalled());
      expect(sheet.shown()).toBe(false);
    });

    it('stays true when the sheet opens again before the old pane has gone', async () => {
      const { view, host } = await setup();
      const sheet = sheetOf(view);
      host.open.set(true);
      view.fixture.detectChanges();
      const animationComplete = jest.fn();
      (sheet as unknown as Leave).leave({ target: document.createElement('div'), animationComplete });
      expect(animationComplete).toHaveBeenCalled();
      expect(sheet.shown()).toBe(true);
    });
  });
});
