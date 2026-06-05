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
});
