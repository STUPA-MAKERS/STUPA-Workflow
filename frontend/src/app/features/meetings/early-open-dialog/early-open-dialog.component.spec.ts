import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Meeting } from '@core/api/models';
import { meeting } from '../../../../testing/meeting-fixtures';
import { EarlyOpenDialogComponent } from './early-open-dialog.component';

async function setup(over: Partial<Meeting> = {}) {
  const closed = jest.fn();
  const confirmed = jest.fn();
  await render(EarlyOpenDialogComponent, {
    inputs: { open: true, meeting: meeting({ status: 'planned', ...over }) },
    on: { closed, confirmed },
  });
  return { closed, confirmed };
}

describe('EarlyOpenDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('names the planned start and confirms the early open', async () => {
    const { confirmed, closed } = await setup({ startTime: '18:00:00' });
    expect(screen.getByText('Sitzung schon eröffnen?')).toBeInTheDocument();
    expect(screen.getByText('Die Sitzung ist erst für 18:00 Uhr geplant.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Jetzt eröffnen' }));
    expect(confirmed).toHaveBeenCalledTimes(1);
    expect(closed).not.toHaveBeenCalled();
  });

  it('says that the meeting has not begun when it has no start time, and cancels', async () => {
    const { confirmed, closed } = await setup({ startTime: null });
    expect(screen.getByText('Die Sitzung beginnt laut Planung noch nicht.')).toBeInTheDocument();
    const cancel = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancel[cancel.length - 1]);
    expect(closed).toHaveBeenCalled();
    expect(confirmed).not.toHaveBeenCalled();
  });
});
