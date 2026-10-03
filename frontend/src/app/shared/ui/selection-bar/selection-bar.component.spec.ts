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

  it('falls back to the bare number without a label', async () => {
    await render(SelectionBarComponent, { inputs: { count: 2 } });
    expect(screen.getByRole('status')).toHaveTextContent('2');
  });

  it('emits cleared when the clear button is pressed', async () => {
    const cleared = jest.fn();
    await render(SelectionBarComponent, { inputs: { count: 1 }, on: { cleared } });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Auswahl aufheben' }));
    expect(cleared).toHaveBeenCalledTimes(1);
  });
});
