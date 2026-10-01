import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Attendance } from '@core/api/models';
import { MeetingAttendanceTableComponent } from './meeting-attendance-table.component';

function row(over: Partial<Attendance> = {}): Attendance {
  return {
    principalId: 'me',
    displayName: 'Ich',
    email: null,
    status: null,
    source: null,
    note: null,
    isSelf: true,
    ...over,
  };
}

async function setup(rows: Attendance[], over: { editAll?: boolean; locked?: boolean } = {}) {
  const statusChange = jest.fn();
  const reset = jest.fn();
  const view = await render(MeetingAttendanceTableComponent, {
    inputs: {
      rows,
      editAll: over.editAll ?? false,
      locked: over.locked ?? false,
      saving: false,
    },
    on: { statusChange, reset },
  });
  return { ...view, statusChange, reset };
}

describe('MeetingAttendanceTableComponent', () => {
  it('offers a member only present and absent (excused) for the own row', async () => {
    const { statusChange } = await setup([row()]);
    const group = screen.getByRole('group');
    const buttons = within(group).getAllByRole('button');
    expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual(['Anwesend', 'Abwesend']);
    await userEvent.click(within(group).getByRole('button', { name: 'Abwesend' }));
    expect(statusChange).toHaveBeenCalledWith({ member: expect.objectContaining({ principalId: 'me' }), status: 'excused' });
  });

  it('hides the own control when the lead set the record (O15)', async () => {
    await setup([row({ status: 'absent', source: 'lead', note: null })]);
    expect(screen.queryByRole('group')).not.toBeInTheDocument();
    expect(screen.getByText('Unentschuldigt')).toBeInTheDocument();
    expect(screen.getByText(/durch Sitzungsleitung/)).toBeInTheDocument();
  });

  it('shows a read-only reason when the member cannot edit it', async () => {
    await setup([row({ status: 'excused', source: 'lead', note: 'Krank' })]);
    expect(screen.getByText('Grund: Krank')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('shows another member as a badge without controls', async () => {
    await setup([row({ principalId: 'p-2', isSelf: false, status: 'excused', source: 'self' })]);
    expect(screen.queryByRole('group')).not.toBeInTheDocument();
    expect(screen.getByText('Entschuldigt')).toBeInTheDocument();
  });

  it('lets the member give, change and remove the reason of an excuse', async () => {
    const { statusChange } = await setup([row({ status: 'excused', source: 'self', note: 'Alt' })]);
    const input = screen.getByRole('textbox', { name: 'Grund' });
    expect(input).toHaveValue('Alt');
    // Unchanged: nothing to save.
    input.focus();
    input.blur();
    expect(statusChange).not.toHaveBeenCalled();
    await userEvent.clear(input);
    await userEvent.type(input, ' Neu {Enter}');
    expect(statusChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'excused', note: 'Neu' }),
    );
  });

  it('removes the reason when the field is emptied', async () => {
    const { statusChange } = await setup([row({ status: 'excused', source: 'self', note: 'Alt' })]);
    const input = screen.getByRole('textbox', { name: 'Grund' });
    await userEvent.clear(input);
    input.blur();
    expect(statusChange).toHaveBeenCalledWith(expect.objectContaining({ note: null }));
  });

  it('gives the lead all statuses, the reset and the reason field', async () => {
    const rows = [
      row({ status: 'excused', source: 'self', note: 'Krank' }),
      row({ principalId: 'p-2', displayName: 'Max', isSelf: false }),
    ];
    const { statusChange, reset } = await setup(rows, { editAll: true });
    const [first, second] = screen.getAllByRole('group');
    expect(within(first).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
      'Anwesend',
      'Entschuldigt',
      'Unentschuldigt',
      'Auf „Offen“ zurücksetzen',
    ]);
    await userEvent.click(within(first).getByRole('button', { name: 'Unentschuldigt' }));
    expect(statusChange).toHaveBeenCalledWith({ member: rows[0], status: 'absent' });
    await userEvent.click(within(first).getByRole('button', { name: 'Auf „Offen“ zurücksetzen' }));
    expect(reset).toHaveBeenCalledWith(rows[0]);
    // A row without a record has nothing to reset.
    expect(within(second).getByRole('button', { name: 'Auf „Offen“ zurücksetzen' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Grund' })).toHaveValue('Krank');
  });

  it('disables every control in a closed meeting', async () => {
    await setup([row({ status: 'excused', source: 'self', note: 'x' })], { editAll: true, locked: true });
    for (const button of screen.getAllByRole('button')) {
      expect(button).toBeDisabled();
    }
    expect(screen.getByRole('textbox')).toBeDisabled();
  });

  it('says when the roster is empty', async () => {
    await setup([]);
    expect(screen.getByText('Noch keine Mitglieder erfasst.')).toBeInTheDocument();
  });
});
