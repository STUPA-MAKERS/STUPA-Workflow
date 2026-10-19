import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { SelectionBarComponent } from './selection-bar.component';

describe('SelectionBarComponent', () => {
  it('stays hidden while nothing is selected', async () => {
    await render(SelectionBarComponent, { inputs: { count: 0 } });
    expect(screen.queryByRole('toolbar')).toBeNull();
  });

  it('shows the count, the actions and a clear button in a named toolbar', async () => {
    const { container } = await render(
      `<app-selection-bar [count]="3" countLabel="3 ausgewählt">
         <button type="button">Exportieren</button>
       </app-selection-bar>`,
      { imports: [SelectionBarComponent] },
    );
    const bar = screen.getByRole('toolbar', { name: 'Auswahl' });
    expect(bar).toHaveTextContent('3 ausgewählt');
    expect(screen.getByRole('button', { name: 'Exportieren' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Auswahl aufheben' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says "<n> ausgewählt" without a label', async () => {
    await render(SelectionBarComponent, { inputs: { count: 2 } });
    expect(screen.getByRole('status')).toHaveTextContent(/^2 ausgewählt$/);
  });

  it('emits cleared when the clear button is pressed', async () => {
    const cleared = jest.fn();
    await render(SelectionBarComponent, { inputs: { count: 1 }, on: { cleared } });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Auswahl aufheben' }));
    expect(cleared).toHaveBeenCalledTimes(1);
  });

  it('shows an inline bar also at zero, as a row on the page', async () => {
    const { fixture } = await render(SelectionBarComponent, { inputs: { count: 0, inline: true } });
    expect(screen.getByRole('toolbar', { name: 'Auswahl' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('0 ausgewählt');
    expect((fixture.nativeElement as HTMLElement).classList.contains('selbar--inline')).toBe(true);
  });

  it('names the clear button as the page asks', async () => {
    await render(SelectionBarComponent, { inputs: { count: 1, clearLabel: 'Auswahl beenden' } });
    expect(screen.getByRole('button', { name: 'Auswahl beenden' })).toBeInTheDocument();
  });

  it('toggles every row with the select-all box and shows the mixed state', async () => {
    const selectAll = jest.fn();
    const { rerender, fixture } = await render(SelectionBarComponent, {
      inputs: { count: 1, allSelected: false },
      on: { selectAll },
    });
    const box = screen.getByRole('checkbox', { name: /^Alle wählen/ });
    expect(box).toHaveAccessibleName('Alle wählen 1 ausgewählt');
    expect((box as HTMLInputElement).indeterminate).toBe(true);
    await userEvent.setup().click(box);
    expect(selectAll).toHaveBeenLastCalledWith(true);

    await rerender({
      inputs: { count: 2, allSelected: true, selectAllLabel: 'Alle' },
      on: { selectAll },
      partialUpdate: true,
    });
    await fixture.whenStable();
    const all = screen.getByRole('checkbox', { name: /^Alle 2/ });
    expect((all as HTMLInputElement).indeterminate).toBe(false);
    expect(all).toBeChecked();
    await userEvent.setup().click(all);
    expect(selectAll).toHaveBeenLastCalledWith(false);
  });

  it('shows no select-all box without allSelected', async () => {
    await render(SelectionBarComponent, { inputs: { count: 2 } });
    expect(screen.queryByRole('checkbox')).toBeNull();
  });
});
