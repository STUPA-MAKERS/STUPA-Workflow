import { render, screen } from '@testing-library/angular';
import { ListDetailNav } from '@stupa-makers/ui-kit';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
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

  it('docks in the bar of the one-view layout and gives the task back when it ends', async () => {
    const nav = new ListDetailNav();
    nav.active.set(true);
    const closed = jest.fn();
    const { container, fixture } = await render(
      `<header appPaneFormHead heading="Buchung hinzufügen" headingId="f-t" (closed)="closed()"></header>`,
      { imports: [PaneFormHeadComponent], componentProperties: { closed }, providers: [{ provide: ListDetailNav, useValue: nav }] },
    );
    expect(container.querySelector('header')).toHaveClass('pfh--docked');
    expect(screen.queryByRole('button', { name: 'Schließen' })).toBeNull();
    expect(screen.getByRole('heading', { level: 2, name: 'Buchung hinzufügen' })).toBeInTheDocument();
    const task = nav.task();
    expect(task).toMatchObject({ title: 'Buchung hinzufügen', cancelLabel: 'Schließen' });
    task?.cancel();
    expect(closed).toHaveBeenCalledTimes(1);
    nav.active.set(false);
    fixture.detectChanges();
    expect(nav.task()).toBeNull();
    expect(screen.getByRole('button', { name: 'Schließen' })).toBeInTheDocument();
    nav.active.set(true);
    fixture.detectChanges();
    expect(nav.task()).not.toBeNull();
    fixture.destroy();
    expect(nav.task()).toBeNull();
  });
});
