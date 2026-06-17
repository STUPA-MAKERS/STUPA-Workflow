import { fireEvent, render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DialogComponent } from './dialog.component';

function pane(): HTMLElement {
  return screen.getByRole('dialog');
}

function backdrop(): HTMLElement {
  return document.querySelector('.dialog__backdrop') as HTMLElement;
}


describe('DialogComponent', () => {
  it('is not rendered while closed', async () => {
    await render(`<app-dialog title="Hinweis" [open]="false">Body</app-dialog>`, {
      imports: [DialogComponent],
    });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders an accessible modal with a labelled title when open', async () => {
    await render(`<app-dialog title="Antrag löschen?" [open]="true">Body</app-dialog>`, {
      imports: [DialogComponent],
    });
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName('Antrag löschen?');
  });

  it('emits closed when the close button is pressed', async () => {
    const closed = jest.fn();
    await render(`<app-dialog title="X" [open]="true" (closed)="onClosed()">B</app-dialog>`, {
      imports: [DialogComponent],
      componentProperties: { onClosed: closed },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it('moves focus into the dialog on open (a11y focus management)', async () => {
    await render(`<app-dialog title="X" [open]="true">B</app-dialog>`, {
      imports: [DialogComponent],
    });
    await new Promise((r) => setTimeout(r, 0)); // queueMicrotask-Fokus abwarten
    const closeBtn = screen.getByRole('button', { name: 'Schließen' });
    expect(document.activeElement).toBe(closeBtn);
  });

  it('traps Tab within the dialog (focus-trap)', async () => {
    await render(`<app-dialog title="X" [open]="true"><button>Body-Btn</button></app-dialog>`, {
      imports: [DialogComponent],
    });
    await new Promise((r) => setTimeout(r, 0));
    const buttons = screen.getAllByRole('button');
    buttons[buttons.length - 1].focus();
    // Tab am letzten Element → zurück zum ersten (kein Verlassen des Dialogs).
    await userEvent.tab();
    expect(document.activeElement).toBe(buttons[0]);
  });

  it('restores focus to the opener when closed', async () => {
    const view = await render(
      `<button id="opener">Open</button><app-dialog title="X" [open]="open">B</app-dialog>`,
      { imports: [DialogComponent], componentProperties: { open: false } },
    );
    const opener = document.getElementById('opener') as HTMLButtonElement;
    opener.focus();
    view.rerender({ componentProperties: { open: true } });
    await new Promise((r) => setTimeout(r, 0));
    view.rerender({ componentProperties: { open: false } });
    expect(document.activeElement).toBe(opener);
  });

  it('applies the large size modifier', async () => {
    await render(`<app-dialog title="X" [open]="true" size="lg">B</app-dialog>`, {
      imports: [DialogComponent],
    });
    expect(pane()).toHaveClass('dialog--lg');
  });

  it('closes on a backdrop click but not on a click inside the pane', async () => {
    const closed = jest.fn();
    await render(`<app-dialog title="X" [open]="true" (closed)="onClosed()">B</app-dialog>`, {
      imports: [DialogComponent],
      componentProperties: { onClosed: closed },
    });
    // Click inside the pane → stopPropagation → does NOT close.
    fireEvent.click(pane());
    expect(closed).not.toHaveBeenCalled();
    // Click the backdrop → closes.
    fireEvent.click(backdrop());
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape when open and ignores Escape when closed', async () => {
    const closed = jest.fn();
    const view = await render(
      `<app-dialog title="X" [open]="open" (closed)="onClosed()">B</app-dialog>`,
      { imports: [DialogComponent], componentProperties: { open: true, onClosed: closed } },
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closed).toHaveBeenCalledTimes(1);

    // Closed → Escape is a no-op.
    view.rerender({ componentProperties: { open: false, onClosed: closed } });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it('ignores non-Tab keydowns and Tab when closed (focus-trap guard)', async () => {
    const view = await render(
      `<app-dialog title="X" [open]="open"><button>Inner</button></app-dialog>`,
      { imports: [DialogComponent], componentProperties: { open: true } },
    );
    // Non-Tab key → handler returns early (no throw).
    expect(() => fireEvent.keyDown(document, { key: 'a' })).not.toThrow();
    // Close → Tab handler returns early because !open.
    view.rerender({ componentProperties: { open: false } });
    expect(() => fireEvent.keyDown(document, { key: 'Tab' })).not.toThrow();
  });

  it('wraps Shift+Tab from the first focusable back to the last', async () => {
    await render(
      `<app-dialog title="X" [open]="true"><button>Inner</button></app-dialog>`,
      { imports: [DialogComponent] },
    );
    await new Promise((r) => setTimeout(r, 0));
    const buttons = screen.getAllByRole('button');
    const first = buttons[0];
    first.focus();
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(buttons[buttons.length - 1]);
  });

  it('keeps focus inside the dialog when the only focusable is the close button', async () => {
    await render(`<app-dialog title="X" [open]="true">Body</app-dialog>`, {
      imports: [DialogComponent],
    });
    await new Promise((r) => setTimeout(r, 0));
    const close = screen.getByRole('button', { name: 'Schließen' });
    close.focus();
    await userEvent.tab();
    expect(document.activeElement).toBe(close);
  });

  it('focuses the pane itself when it has no focusable children (Tab guard)', async () => {
    const view = await render(`<app-dialog title="X" [open]="true">Body</app-dialog>`, {
      imports: [DialogComponent],
    });
    const paneEl = pane();
    // Strip all focusable descendants so the focus-trap takes the empty-pane path.
    paneEl.querySelectorAll('button').forEach((b) => b.remove());
    const focusSpy = jest.spyOn(paneEl, 'focus');
    const evt = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true });
    const prevent = jest.spyOn(evt, 'preventDefault');
    document.dispatchEvent(evt);
    view.fixture.detectChanges();
    expect(prevent).toHaveBeenCalled();
    expect(focusSpy).toHaveBeenCalled();
  });

  it('locks body scroll while open and restores it on close', async () => {
    document.body.style.overflow = 'scroll';
    const view = await render(`<app-dialog title="X" [open]="open">B</app-dialog>`, {
      imports: [DialogComponent],
      componentProperties: { open: false },
    });
    expect(document.body.style.overflow).toBe('scroll');
    view.rerender({ componentProperties: { open: true } });
    expect(document.body.style.overflow).toBe('hidden');
    view.rerender({ componentProperties: { open: false } });
    expect(document.body.style.overflow).toBe('scroll');
    document.body.style.overflow = '';
  });

  it('locks scroll when initially opened (firstChange path)', async () => {
    await render(`<app-dialog title="X" [open]="true">B</app-dialog>`, {
      imports: [DialogComponent],
    });
    expect(document.body.style.overflow).toBe('hidden');
    document.body.style.overflow = '';
  });

  it('unlocks body scroll when destroyed while open', async () => {
    const view = await render(`<app-dialog title="X" [open]="true">B</app-dialog>`, {
      imports: [DialogComponent],
    });
    expect(document.body.style.overflow).toBe('hidden');
    view.fixture.destroy();
    expect(document.body.style.overflow).not.toBe('hidden');
  });

  // jsdom assigns its own event.timeStamp, so velocity in onDragEnd cannot be
  // controlled via fireEvent. Drive the drag handlers directly with synthetic
  // TouchEvent-shaped objects that carry explicit clientY/timeStamp.
  function makeTouch(clientY: number, timeStamp: number): TouchEvent {
    return { touches: [{ clientY }], timeStamp } as unknown as TouchEvent;
  }

  it('closes via drag-to-dismiss when dragged far enough down', async () => {
    const closed = jest.fn();
    const view = await render(`<app-dialog title="X" [open]="true" (closed)="onClosed()">B</app-dialog>`, {
      imports: [DialogComponent],
      componentProperties: { onClosed: closed },
    });
    const cmp = view.fixture.debugElement.children[0].componentInstance as DialogComponent;
    cmp.onDragStart(makeTouch(0, 0));
    cmp.onDragMove(makeTouch(200, 100)); // 200px down (> 120 threshold)
    cmp.onDragEnd(makeTouch(200, 2000)); // slow but far → close
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it('closes on a fast downward flick (high velocity)', async () => {
    const closed = jest.fn();
    const view = await render(`<app-dialog title="X" [open]="true" (closed)="onClosed()">B</app-dialog>`, {
      imports: [DialogComponent],
      componentProperties: { onClosed: closed },
    });
    const cmp = view.fixture.debugElement.children[0].componentInstance as DialogComponent;
    cmp.onDragStart(makeTouch(0, 0));
    cmp.onDragMove(makeTouch(60, 50));
    cmp.onDragEnd(makeTouch(60, 50)); // 60px in ~50ms → velocity > 0.5 → close
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it('snaps back when dragged only a little and slowly (no close)', async () => {
    const closed = jest.fn();
    const view = await render(`<app-dialog title="X" [open]="true" (closed)="onClosed()">B</app-dialog>`, {
      imports: [DialogComponent],
      componentProperties: { onClosed: closed },
    });
    const cmp = view.fixture.debugElement.children[0].componentInstance as DialogComponent;
    const paneEl = pane();
    cmp.onDragStart(makeTouch(0, 0));
    cmp.onDragMove(makeTouch(20, 5000));
    cmp.onDragEnd(makeTouch(20, 5000)); // 20px over 5000ms → velocity 0.004 → snap back
    expect(closed).not.toHaveBeenCalled();
    expect(paneEl.style.transform).toBe('');
  });

  it('only drags down, never up (clamped at 0)', async () => {
    const view = await render(`<app-dialog title="X" [open]="true">B</app-dialog>`, {
      imports: [DialogComponent],
    });
    const cmp = view.fixture.debugElement.children[0].componentInstance as DialogComponent;
    const paneEl = pane();
    cmp.onDragStart(makeTouch(100, 0));
    cmp.onDragMove(makeTouch(40, 50)); // upward → clamped to 0
    expect(paneEl.style.transform).toBe('translateY(0px)');
  });

  it('ignores multi-touch drag starts and stray move/end without an active drag', async () => {
    const view = await render(`<app-dialog title="X" [open]="true">B</app-dialog>`, {
      imports: [DialogComponent],
    });
    const cmp = view.fixture.debugElement.children[0].componentInstance as DialogComponent;
    const paneEl = pane();
    // Two-finger start → dragging never begins.
    cmp.onDragStart({ touches: [{ clientY: 0 }, { clientY: 10 }], timeStamp: 0 } as unknown as TouchEvent);
    cmp.onDragMove(makeTouch(200, 50)); // ignored (not dragging)
    expect(paneEl.style.transform).toBe('');
    // touchend without an active drag → no-op (no throw, no close).
    expect(() => cmp.onDragEnd(makeTouch(200, 50))).not.toThrow();
  });
});
