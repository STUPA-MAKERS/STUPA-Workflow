import { Component, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { ConfirmDialogComponent } from './confirm-dialog.component';

@Component({
  standalone: true,
  imports: [ConfirmDialogComponent],
  template: `
    <app-confirm-dialog
      [open]="open()"
      title="Rechnung löschen?"
      [subtitle]="subtitle()"
      [body]="body()"
      [confirmLabel]="confirmLabel()"
      [danger]="danger()"
      [busy]="busy()"
      [disabled]="disabled()"
      (confirm)="confirms = confirms + 1"
      (cancel)="cancels = cancels + 1; open.set(false)"
    >
      @if (withNote) {
        <p role="alert">Die Rechnung ist schon gebucht.</p>
      }
    </app-confirm-dialog>
  `,
})
class HostComponent {
  readonly open = signal(true);
  readonly body = signal('„R-17“ wird gelöscht. Das lässt sich nicht rückgängig machen.');
  readonly confirmLabel = signal('');
  readonly subtitle = signal('');
  readonly danger = signal(true);
  readonly busy = signal(false);
  readonly disabled = signal(false);
  withNote = false;
  confirms = 0;
  cancels = 0;
}

async function setup(configure?: (h: HostComponent) => void) {
  const view = await render(HostComponent);
  const host = view.fixture.componentInstance;
  configure?.(host);
  view.fixture.detectChanges();
  return { view, host, user: userEvent.setup() };
}

const confirmButton = () => screen.getByRole('button', { name: 'Löschen' });

describe('ConfirmDialogComponent', () => {
  afterEach(() => {
    document.body.style.overflow = '';
  });

  it('shows the title, the text, "Abbrechen" and "Löschen" in the danger look', async () => {
    const { view } = await setup();
    const dialog = screen.getByRole('dialog', { name: 'Rechnung löschen?' });
    expect(dialog).toHaveTextContent('„R-17“ wird gelöscht. Das lässt sich nicht rückgängig machen.');
    const footer = view.container.querySelectorAll('.dialog__footer app-button');
    expect(Array.from(footer).map((b) => b.textContent?.trim())).toEqual(['Abbrechen', 'Löschen']);
    expect(confirmButton()).toHaveClass('btn--danger');
    expect(confirmButton()).toHaveClass('btn--md');
    expect(screen.getByRole('button', { name: 'Abbrechen' })).toHaveClass('btn--text');
    expect(screen.getByRole('button', { name: 'Schließen' })).toBeInTheDocument();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('shows the subtitle as the description of the dialog', async () => {
    await setup((h) => h.subtitle.set('anna@example.org'));
    expect(screen.getByRole('dialog')).toHaveAccessibleDescription('anna@example.org');
  });

  it('renders nothing while closed', async () => {
    await setup((h) => h.open.set(false));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('emits confirm on the confirm button', async () => {
    const { host, user } = await setup();
    await user.click(confirmButton());
    expect(host.confirms).toBe(1);
    expect(host.cancels).toBe(0);
  });

  it('emits cancel on "Abbrechen"', async () => {
    const { host, user } = await setup();
    await user.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(host.cancels).toBe(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('emits cancel on the X and on Escape', async () => {
    const { host, user, view } = await setup();
    await user.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(host.cancels).toBe(1);
    host.open.set(true);
    view.fixture.detectChanges();
    await user.keyboard('{Escape}');
    expect(host.cancels).toBe(2);
    expect(host.confirms).toBe(0);
  });

  it('takes another confirm label and the fill look', async () => {
    await setup((h) => {
      h.confirmLabel.set('Widerrufen');
      h.danger.set(false);
    });
    const button = screen.getByRole('button', { name: 'Widerrufen' });
    expect(button).toHaveClass('btn--fill');
    expect(button).not.toHaveClass('btn--danger');
  });

  it('shows no text paragraph without a body', async () => {
    const { view } = await setup((h) => h.body.set(''));
    expect(view.container.querySelector('.cfd__body')).toBeNull();
  });

  it('shows the projected content below the text', async () => {
    await setup((h) => (h.withNote = true));
    expect(screen.getByRole('alert')).toHaveTextContent('Die Rechnung ist schon gebucht.');
  });

  it('shows the spinner while busy and ignores a click', async () => {
    const { host, view } = await setup((h) => h.busy.set(true));
    expect(confirmButton()).toBeDisabled();
    expect(confirmButton()).toHaveAttribute('aria-busy', 'true');
    const cmp = view.fixture.debugElement.children[0].componentInstance as ConfirmDialogComponent;
    (cmp as unknown as { onConfirm(): void }).onConfirm();
    expect(host.confirms).toBe(0);
  });

  it('blocks the confirm while disabled', async () => {
    const { host, view } = await setup((h) => h.disabled.set(true));
    expect(confirmButton()).toBeDisabled();
    const cmp = view.fixture.debugElement.children[0].componentInstance as ConfirmDialogComponent;
    (cmp as unknown as { onConfirm(): void }).onConfirm();
    expect(host.confirms).toBe(0);
  });
});
