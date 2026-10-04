import { Component, signal } from '@angular/core';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { SideSheetComponent, type SheetSide } from './side-sheet.component';

@Component({
  standalone: true,
  imports: [SideSheetComponent],
  template: `
    <button type="button" (click)="open.set(true)">Anwesenheit</button>
    <app-side-sheet heading="Anwesenheit" [side]="side()" [(open)]="open" (closed)="closes = closes + 1">
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
  closes = 0;
  withActions = true;
  withContent = true;
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
});
