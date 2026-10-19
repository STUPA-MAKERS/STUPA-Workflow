import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { PaneFormFootComponent } from './pane-form-foot.component';
import { PaneFormHeadComponent } from './pane-form-head.component';

describe('PaneFormHeadComponent', () => {
  it('shows the title, the subtitle and closes', async () => {
    const closed = jest.fn();
    const { container } = await render(
      `<form aria-labelledby="f-t"><header class="ff__head" appPaneFormHead heading="Buchung bearbeiten" headingId="f-t" subtitle="Druckkosten" (closed)="closed()"></header></form>`,
      { imports: [PaneFormHeadComponent], componentProperties: { closed } },
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Buchung bearbeiten' })).toHaveAttribute('id', 'f-t');
    expect(screen.getByText('Druckkosten')).toHaveClass('pfh__subtitle');
    expect(container.querySelector('header.ff__head')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(closed).toHaveBeenCalledTimes(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows no subtitle line without a subtitle', async () => {
    const { container } = await render(`<header appPaneFormHead heading="Neu"></header>`, {
      imports: [PaneFormHeadComponent],
    });
    expect(container.querySelector('.pfh__subtitle')).toBeNull();
  });
});

describe('PaneFormFootComponent', () => {
  it('offers cancel and the projected main action, no delete for a create', async () => {
    const cancelled = jest.fn();
    await render(
      `<footer appPaneFormFoot (cancelled)="cancelled()"><button type="button">Hinzufügen</button></footer>`,
      { imports: [PaneFormFootComponent], componentProperties: { cancelled } },
    );
    expect(screen.queryByRole('button', { name: 'Löschen' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Hinzufügen' }).closest('.pff__end')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(cancelled).toHaveBeenCalledTimes(1);
  });

  it('offers a labelled delete, and an icon in a phone sheet', async () => {
    const removed = jest.fn();
    const view = await render(`<footer appPaneFormFoot deletable [compact]="compact" (removed)="removed()"></footer>`, {
      imports: [PaneFormFootComponent],
      componentProperties: { removed, compact: false },
    });
    const del = screen.getByRole('button', { name: 'Löschen' });
    expect(del).toHaveTextContent('Löschen');
    await userEvent.click(del);
    expect(removed).toHaveBeenCalledTimes(1);
    view.fixture.componentInstance.compact = true;
    view.fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Löschen' })).not.toHaveTextContent('Löschen');
  });
});
