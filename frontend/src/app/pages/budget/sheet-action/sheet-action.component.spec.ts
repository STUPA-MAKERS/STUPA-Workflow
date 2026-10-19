import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { SheetActionComponent } from './sheet-action.component';

describe('SheetActionComponent', () => {
  it('is an icon button with a name and a tooltip off the phone', async () => {
    const pressed = jest.fn();
    const { container } = await render(
      `<app-sheet-action icon="edit" label="Bearbeiten" ariaLabel="Buchung bearbeiten" (pressed)="pressed()" />`,
      { imports: [SheetActionComponent], componentProperties: { pressed } },
    );
    const button = screen.getByRole('button', { name: 'Buchung bearbeiten' });
    expect(button).toHaveAttribute('title', 'Buchung bearbeiten');
    expect(screen.queryByText('Bearbeiten')).toBeNull();
    await userEvent.click(button);
    expect(pressed).toHaveBeenCalledTimes(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('is a tonal button with the icon and the text on a phone', async () => {
    const pressed = jest.fn();
    await render(
      `<app-sheet-action icon="edit" label="Bearbeiten" ariaLabel="Buchung bearbeiten" phone (pressed)="pressed()" />`,
      { imports: [SheetActionComponent], componentProperties: { pressed } },
    );
    const button = screen.getByRole('button', { name: 'Bearbeiten' });
    expect(button.querySelector('.sa__btn app-icon')).not.toBeNull();
    await userEvent.click(button);
    expect(pressed).toHaveBeenCalledTimes(1);
  });
});
