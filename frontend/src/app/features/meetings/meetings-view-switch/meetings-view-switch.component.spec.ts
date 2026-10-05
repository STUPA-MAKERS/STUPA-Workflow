import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { MeetingsViewSwitchComponent } from './meetings-view-switch.component';

describe('MeetingsViewSwitchComponent', () => {
  it('switches between the list and the calendar', async () => {
    const valueChange = jest.fn();
    const { fixture } = await render(MeetingsViewSwitchComponent, {
      inputs: { value: 'list' },
      on: { valueChange },
    });
    expect(screen.getByRole('radiogroup', { name: 'Ansicht' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Liste' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('radio', { name: 'Kalender' }));
    expect(valueChange).toHaveBeenCalledWith('calendar');
    // A value that is no view (a cleared control) changes nothing.
    (fixture.componentInstance as unknown as { pick(v: string | null): void }).pick(null);
    expect(valueChange).toHaveBeenCalledTimes(1);
  });
});
