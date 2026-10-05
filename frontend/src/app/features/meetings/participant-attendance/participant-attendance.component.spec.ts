import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Attendance, MeetingStatus } from '@core/api/models';
import { ParticipantAttendanceComponent } from './participant-attendance.component';

function me(over: Partial<Attendance> = {}): Attendance {
  return {
    principalId: 'p-1',
    displayName: 'Paul Neumann',
    email: null,
    status: null,
    source: null,
    note: null,
    isSelf: true,
    ...over,
  };
}

async function setup(
  member: Attendance,
  opts: { status?: MeetingStatus; delegated?: boolean; saving?: boolean } = {},
) {
  const change = jest.fn();
  const view = await render(ParticipantAttendanceComponent, {
    inputs: {
      member,
      meetingStatus: opts.status ?? 'planned',
      delegated: opts.delegated ?? false,
      saving: opts.saving ?? false,
    },
    on: { change },
  });
  return { ...view, change };
}

describe('ParticipantAttendanceComponent', () => {
  it('reports "Anwesend" as present and "Abwesend" as an excuse (Z2)', async () => {
    const { change } = await setup(me());
    expect(screen.getByRole('heading', { name: 'Deine Anwesenheit' })).toBeInTheDocument();
    const group = screen.getByRole('radiogroup', { name: 'Deine Anwesenheit' });
    expect(group).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'Anwesend' }));
    expect(change).toHaveBeenLastCalledWith({ status: 'present' });
    await userEvent.click(screen.getByRole('radio', { name: 'Abwesend' }));
    expect(change).toHaveBeenLastCalledWith({ status: 'excused' });
    // Never "absent": a member cannot set an unexcused absence.
    expect(change.mock.calls.every(([c]) => c.status !== 'absent')).toBe(true);
  });

  it('sends nothing for the status the member already has, or while a change saves', async () => {
    const { change, fixture } = await setup(me({ status: 'present', source: 'self' }));
    expect(screen.getByRole('radio', { name: 'Anwesend' })).toHaveAttribute('aria-checked', 'true');
    // The kit control ignores a click on the chosen option; the component guards too.
    (fixture.componentInstance as unknown as { pick(v: string | null): void }).pick('present');
    (fixture.componentInstance as unknown as { pick(v: string | null): void }).pick(null);
    expect(change).not.toHaveBeenCalled();
    fixture.componentRef.setInput('saving', true);
    fixture.detectChanges();
    (fixture.componentInstance as unknown as { pick(v: string | null): void }).pick('excused');
    expect(change).not.toHaveBeenCalled();
  });

  it('asks for an optional reason of an absence and sends a changed reason', async () => {
    const { change, fixture } = await setup(me({ status: 'excused', source: 'self', note: 'Prüfung' }));
    const field = screen.getByLabelText('Grund (optional)');
    await waitFor(() => expect(field).toHaveValue('Prüfung'));
    expect(screen.getByText('Sichtbar für dich und die Sitzungsführung.')).toBeInTheDocument();
    // Leaving the field unchanged sends nothing.
    await userEvent.click(field);
    await userEvent.tab();
    expect(change).not.toHaveBeenCalled();
    await userEvent.clear(field);
    await userEvent.type(field, ' Klausur {Enter}');
    expect(change).toHaveBeenCalledWith({ status: 'excused', note: 'Klausur' });
    // While a change saves, the field sends nothing.
    change.mockReset();
    fixture.componentRef.setInput('saving', true);
    fixture.detectChanges();
    await userEvent.type(field, 'x{Enter}');
    expect(change).not.toHaveBeenCalled();
  });

  it('removes the reason when the field is emptied', async () => {
    const { change } = await setup(me({ status: 'absent', source: 'self', note: 'Krank' }));
    expect(screen.getByRole('radio', { name: 'Abwesend' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.clear(screen.getByLabelText('Grund (optional)'));
    await userEvent.tab();
    expect(change).toHaveBeenCalledWith({ status: 'excused', note: null });
  });

  it('shows the record of the lead as text, which the member cannot change (O15)', async () => {
    await setup(me({ status: 'excused', source: 'lead', note: 'Urlaub' }));
    expect(screen.queryByRole('radiogroup')).toBeNull();
    expect(screen.getByText('Abwesend')).toBeInTheDocument();
    expect(screen.getByText('durch Sitzungsleitung')).toBeInTheDocument();
    expect(screen.getByText('Urlaub')).toBeInTheDocument();
  });

  it('shows the record of a closed meeting as text', async () => {
    const { fixture } = await setup(me({ status: 'present', source: 'self' }), { status: 'closed' });
    expect(screen.queryByRole('radiogroup')).toBeNull();
    expect(screen.getByText('Anwesend')).toBeInTheDocument();
    expect(screen.queryByText('durch Sitzungsleitung')).toBeNull();
    fixture.componentRef.setInput('member', me());
    fixture.detectChanges();
    expect(screen.getByText('Offen')).toBeInTheDocument();
  });

  it('turns "Anwesend" off while the member hands the meeting over (O23)', async () => {
    const { change } = await setup(me({ status: 'excused', source: 'self' }), { delegated: true });
    expect(screen.getByRole('radio', { name: 'Anwesend' })).toBeDisabled();
    expect(screen.getByText(/Widerrufe die Vertretung, um dich anwesend zu melden/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'Anwesend' }));
    expect(change).not.toHaveBeenCalled();
  });

  it('keeps a present member able to report an absence while delegated', async () => {
    await setup(me({ status: 'present', source: 'self' }), { delegated: true });
    expect(screen.getByRole('radio', { name: 'Anwesend' })).toBeEnabled();
    expect(screen.queryByText(/Widerrufe die Vertretung/)).toBeNull();
  });
});
