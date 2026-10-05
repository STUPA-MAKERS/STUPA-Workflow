import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Attendance, Meeting } from '@core/api/models';
import { ATTENDANCE, WITH_VOTER, meeting } from '../../../../testing/meeting-fixtures';
import { KeeperMenuComponent } from './keeper-menu.component';

async function setup(m: Meeting, attendance: Attendance[] = ATTENDANCE, inSheet = false) {
  const pick = jest.fn();
  const discard = jest.fn();
  const view = await render(KeeperMenuComponent, {
    inputs: { meeting: m, attendance, inSheet },
    on: { pick, discard },
  });
  return { ...view, pick, discard };
}

describe('KeeperMenuComponent', () => {
  it('lists the members with protocol.write, the current one marked (O20)', async () => {
    const { pick } = await setup(meeting(), WITH_VOTER);
    expect(screen.getByText('Protokollführung übergeben an')).toBeInTheDocument();
    expect(screen.queryByText('Vera Votum')).toBeNull();
    const current = screen.getByRole('button', { name: /Pia Protokoll/ });
    expect(current).toHaveAttribute('aria-current', 'true');
    expect(current).toHaveTextContent('Anwesend · führt das Protokoll');
    expect(screen.getByRole('button', { name: /Mika Mitglied/ })).toHaveTextContent('Entschuldigt');
    expect(screen.getByRole('button', { name: /Alina Admin/ })).toHaveTextContent('Offen');
    await userEvent.click(screen.getByRole('button', { name: /Mika Mitglied/ }));
    expect(pick).toHaveBeenCalledWith('pr-2');
  });

  it('assigns in a planned meeting and shows no planned handover there', async () => {
    const plan = {
      principalId: 'pr-2', name: 'Mika Mitglied', fromAt: null, toAt: null,
      fromAgendaItemId: null, toAgendaItemId: null, fromPosition: 2, toPosition: null,
    };
    await setup(meeting({ status: 'planned', plannedHandover: plan }));
    expect(screen.getByText('Protokollführung zuweisen')).toBeInTheDocument();
    expect(screen.queryByText('Geplant')).toBeNull();
  });

  it('discards the planned handover of a live meeting', async () => {
    const plan = {
      principalId: 'pr-2', name: 'Mika Mitglied', fromAt: null, toAt: null,
      fromAgendaItemId: 't-2', toAgendaItemId: null, fromPosition: 2, toPosition: null,
    };
    const { discard } = await setup(meeting({ plannedHandover: plan }));
    expect(screen.getByRole('status')).toHaveTextContent('Mika Mitglied');
    expect(screen.getByRole('status')).toHaveTextContent('übernimmt ab TOP 2');
    await userEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    expect(discard).toHaveBeenCalled();
  });

  it('takes the sheet look inside a bottom sheet and says when nobody matches', async () => {
    const { container } = await setup(meeting(), [], true);
    expect(container).toHaveClass('km--sheet');
    expect(screen.getByText('Kein Mitglied mit Protokollrecht gefunden.')).toBeInTheDocument();
  });
});
