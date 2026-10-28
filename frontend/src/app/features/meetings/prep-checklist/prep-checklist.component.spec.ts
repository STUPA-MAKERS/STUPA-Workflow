import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Meeting } from '@core/api/models';
import { AGENDA, ATTENDANCE, meeting } from '../../../../testing/meeting-fixtures';
import { PrepChecklistComponent } from './prep-checklist.component';

const OUTPUTS = ['editAgenda', 'assignKeeper', 'recordAttendance', 'start'] as const;

async function setup(over: Partial<Meeting> = {}) {
  const on = Object.fromEntries(OUTPUTS.map((name) => [name, jest.fn()])) as Record<
    (typeof OUTPUTS)[number],
    jest.Mock
  >;
  const view = await render(PrepChecklistComponent, {
    inputs: { meeting: meeting({ status: 'planned', ...over }), agenda: AGENDA, attendance: ATTENDANCE },
    on,
  });
  return { ...view, on };
}

describe('PrepChecklistComponent', () => {
  it('lists the agenda, the minute-taker and the attendance and opens each', async () => {
    const { on } = await setup();
    expect(screen.getByRole('heading', { name: 'Sitzung vorbereiten' })).toBeInTheDocument();
    expect(screen.getByText('Die Sitzung ist noch nicht eröffnet.')).toBeInTheDocument();
    expect(screen.getByText('3 TOPs vorbereitet')).toBeInTheDocument();
    expect(screen.getByText('Pia Protokoll')).toBeInTheDocument();
    expect(screen.getByText('1 von 3 anwesend')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Tagesordnung bearbeiten' }));
    expect(on.editAgenda).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Ändern' }));
    expect(on.assignKeeper).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Erfassen' }));
    expect(on.recordAttendance).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung eröffnen' }));
    expect(on.start).toHaveBeenCalled();
  });

  it('leaves the agenda card out where the page shows the agenda pane', async () => {
    const { rerender } = await setup();
    await rerender({ inputs: { agendaCard: false }, partialUpdate: true });
    expect(screen.queryByText('3 TOPs vorbereitet')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Tagesordnung bearbeiten' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Ändern' })).toBeInTheDocument();
  });

  it('marks a missing minute-taker and keeps the opening disabled until one is set', async () => {
    const { container } = await setup({ protokollantId: null, protokollantName: null });
    expect(screen.getByText('Noch nicht zugewiesen — nötig zum Eröffnen')).toBeInTheDocument();
    expect(container.querySelector('.pc__card--todo')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Zuweisen' })).toBeInTheDocument();
    const start = screen.getByRole('button', { name: 'Sitzung eröffnen' });
    expect(start).toBeDisabled();
    expect(start).toHaveAttribute('title', 'Erst die Protokollführung zuweisen.');
  });

  it('offers no assignment without the manage right and no start without the lead right', async () => {
    await setup({ protokollantId: null, protokollantName: null, canManage: false, canControl: false });
    expect(screen.queryByRole('button', { name: 'Zuweisen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Sitzung eröffnen' })).toBeNull();
  });

  /** Late in the evening the window can open on the next day, and the hint then names the day. */
  it('keeps the opening disabled before the open window and says when it opens', async () => {
    const opensAt = new Date(Date.now() + 30 * 60_000);
    await setup({ opensAt: opensAt.toISOString(), confirmUntil: new Date(Date.now() + 80 * 60_000).toISOString() });
    const time = opensAt.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    const start = screen.getByRole('button', { name: 'Sitzung eröffnen' });
    expect(start).toBeDisabled();
    expect(screen.getByText(new RegExp(`^Eröffnen ab (\\d\\d\\.\\d\\d\\., )?${time}$`))).toBeInTheDocument();
  });

  it('enables the opening inside the window', async () => {
    await setup({ opensAt: new Date(Date.now() - 60_000).toISOString(), confirmUntil: new Date(Date.now() + 60_000).toISOString() });
    expect(screen.getByRole('button', { name: 'Sitzung eröffnen' })).toBeEnabled();
    expect(screen.queryByText(/^Eröffnen ab/)).toBeNull();
  });
});
