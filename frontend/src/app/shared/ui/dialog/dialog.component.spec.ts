import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DialogComponent } from './dialog.component';

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
});
