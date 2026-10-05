import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Attendance, KeeperPeriod, Meeting } from '@core/api/models';
import { AGENDA, ATTENDANCE, meeting } from '../../../../testing/meeting-fixtures';
import { HandoverDialogComponent } from './handover-dialog.component';

const MIKA = ATTENDANCE[1];

const RUNNING: KeeperPeriod = {
  principalId: 'pr-1',
  name: 'Pia Protokoll',
  fromAt: '2026-10-15T16:04:00Z',
  toAt: null,
  fromAgendaItemId: 't-1',
  toAgendaItemId: null,
  fromPosition: 1,
  toPosition: null,
};

interface Inputs {
  meeting: Meeting;
  agenda: AgendaItem[];
  target: Attendance | null;
  saving: boolean;
  refusal: string | null;
}

async function setup(over: Partial<Inputs> = {}) {
  const on = { closed: jest.fn(), repick: jest.fn(), confirm: jest.fn() };
  const view = await render(HandoverDialogComponent, {
    inputs: {
      meeting: meeting({ currentAgendaItemId: 't-2', keeperPeriods: [RUNNING] }),
      agenda: AGENDA,
      target: MIKA,
      saving: false,
      refusal: null,
      ...over,
    },
    on,
  });
  return { ...view, on };
}

const dialog = () => screen.getByRole('dialog', { name: 'Protokollführung übergeben' });

describe('HandoverDialogComponent', () => {
  it('shows the old and the new minute-taker and goes back to the picker', async () => {
    const { on } = await setup();
    expect(within(dialog()).getByText('Konstituierende Sitzung')).toBeInTheDocument();
    expect(within(dialog()).getByText('Bisher')).toBeInTheDocument();
    expect(within(dialog()).getByText('Pia Protokoll')).toBeInTheDocument();
    expect(within(dialog()).getByText('Neu')).toBeInTheDocument();
    expect(within(dialog()).getByText('Mika Mitglied')).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Ändern' }));
    expect(on.repick).toHaveBeenCalled();
  });

  it('lets a pick of a mode reach no output of the host (the native change event bubbles)', async () => {
    const repick = jest.fn();
    const closed = jest.fn();
    const confirm = jest.fn();
    await render(
      `<app-handover-dialog [meeting]="m" [agenda]="agenda" [target]="target"
        (repick)="repick()" (closed)="closed()" (confirm)="confirm($event)" />`,
      {
        imports: [HandoverDialogComponent],
        componentProperties: {
          m: meeting({ currentAgendaItemId: 't-2', keeperPeriods: [RUNNING] }),
          agenda: AGENDA,
          target: MIKA,
          repick,
          closed,
          confirm,
        },
      },
    );
    const next = within(dialog()).getByRole('radio', { name: /Ab TOP 3/ });
    await userEvent.click(next);
    expect(next).toBeChecked();
    expect(repick).not.toHaveBeenCalled();
    expect(closed).not.toHaveBeenCalled();
    await userEvent.keyboard('{ArrowUp}');
    expect(within(dialog()).getByRole('radio', { name: /Ab jetzt/ })).toBeChecked();
    expect(repick).not.toHaveBeenCalled();
    await userEvent.keyboard('{ArrowDown}');
    expect(next).toBeChecked();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Übergeben' }));
    expect(confirm).toHaveBeenCalledWith('next_item');
  });

  it('hands over now, in the current TOP, and previews the head of the protocol (O1, O2)', async () => {
    const { on } = await setup();
    const now = within(dialog()).getByRole('radio', { name: /Ab jetzt/ });
    expect(now).toBeChecked();
    expect(within(dialog()).getByText(/^in TOP 2, \d\d:\d\d$/)).toBeInTheDocument();
    expect(within(dialog()).getByText(/^Protokoll: Pia Protokoll \(TOP 1–2\), Mika Mitglied \(ab TOP 2, \d\d:\d\d\)$/)).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Übergeben' }));
    expect(on.confirm).toHaveBeenCalledWith('now');
  });

  it('plans the handover with the next TOP: the old keeper finishes the current one', async () => {
    const { on } = await setup();
    const next = within(dialog()).getByRole('radio', { name: /Ab TOP 3/ });
    expect(within(dialog()).getByText('Pia Protokoll schreibt TOP 2 zu Ende')).toBeInTheDocument();
    await userEvent.click(next);
    expect(next).toBeChecked();
    expect(within(dialog()).getByText('Protokoll: Pia Protokoll (TOP 1–2), Mika Mitglied (ab TOP 3)')).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Übergeben' }));
    expect(on.confirm).toHaveBeenCalledWith('next_item');
  });

  it('offers only "now" on the last TOP and sends now for a stale choice', async () => {
    const { on, fixture } = await setup();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Ab TOP 3/ }));
    fixture.componentRef.setInput('meeting', meeting({ currentAgendaItemId: 't-3', keeperPeriods: [RUNNING] }));
    fixture.detectChanges();
    const next = within(dialog()).getByRole('radio', { name: /Ab nächstem TOP/ });
    expect(next).toBeDisabled();
    expect(within(dialog()).getByText('Der aktuelle TOP ist der letzte.')).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Übergeben' }));
    expect(on.confirm).toHaveBeenCalledWith('now');
  });

  it('shows the refusals of the server in the body (409, 422)', async () => {
    const { fixture } = await setup({ refusal: 'protokollant_needs_protocol_write' });
    expect(within(dialog()).getByRole('alert')).toHaveTextContent('Diese Person hat im Gremium kein Protokollrecht.');
    fixture.componentRef.setInput('refusal', 'already_protokollant');
    fixture.detectChanges();
    expect(within(dialog()).getByRole('alert')).toHaveTextContent('Diese Person führt das Protokoll schon.');
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Ab TOP 3/ }));
    fixture.componentRef.setInput('refusal', 'no_next_item');
    fixture.detectChanges();
    expect(within(dialog()).getByRole('alert')).toHaveTextContent('Der aktuelle TOP ist der letzte.');
    // Only "now" is left.
    expect(within(dialog()).getByRole('radio', { name: /Ab jetzt/ })).toBeChecked();
    expect(within(dialog()).getByRole('radio', { name: /Ab nächstem TOP/ })).toBeDisabled();
    fixture.componentRef.setInput('refusal', 'meeting_not_live');
    fixture.detectChanges();
    expect(within(dialog()).queryByRole('alert')).toBeNull();
  });

  it('names a member without a name by the e-mail, and a missing minute-taker by a dash', async () => {
    await setup({
      target: { ...MIKA, displayName: null, email: 'mika@x.de' },
      meeting: meeting({ protokollantName: null, keeperPeriods: [] }),
    });
    expect(within(dialog()).getByText('mika@x.de')).toBeInTheDocument();
    expect(within(dialog()).getByText('—')).toBeInTheDocument();
  });

  it('names a meeting without a current TOP and without periods by its times', async () => {
    await setup({
      meeting: meeting({ currentAgendaItemId: null, keeperPeriods: [], startedAt: '2026-10-15T16:04:00Z' }),
    });
    expect(within(dialog()).getByText(/^um \d\d:\d\d$/)).toBeInTheDocument();
    expect(within(dialog()).getByRole('radio', { name: /Ab nächstem TOP/ })).not.toBeDisabled();
    expect(within(dialog()).getByText('mit dem nächsten TOP')).toBeInTheDocument();
    expect(within(dialog()).getByText(/^Protokoll: Pia Protokoll \(\d\d:04–\d\d:\d\d\), Mika Mitglied \(ab \d\d:\d\d\)$/)).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Ab nächstem TOP/ }));
    expect(within(dialog()).getByText(/Mika Mitglied \(ab dem nächsten TOP\)$/)).toBeInTheDocument();
  });

  it('closes on cancel and sends nothing while saving or without a target', async () => {
    const { on, fixture } = await setup({ saving: true });
    // The close button of the dialog and the footer button both cancel.
    const cancels = within(dialog()).getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancels[cancels.length - 1]);
    expect(on.closed).toHaveBeenCalled();
    (fixture.componentInstance as unknown as { submit(): void }).submit();
    expect(on.confirm).not.toHaveBeenCalled();
    fixture.componentRef.setInput('target', null);
    fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
    const internals = fixture.componentInstance as unknown as { preview(): string; targetName(): string };
    expect(internals.preview()).toBe('');
    expect(internals.targetName()).toBe('');
    fixture.componentRef.setInput('saving', false);
    (fixture.componentInstance as unknown as { submit(): void }).submit();
    expect(on.confirm).not.toHaveBeenCalled();
  });
});
