import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Attendance, Meeting } from '@core/api/models';
import {
  AGENDA,
  ATTENDANCE,
  DELEGATION_CONTEXT,
  WITH_VOTER,
  meeting,
} from '../../../../testing/meeting-fixtures';
import { type DockPanel, SessionDockComponent } from './session-dock.component';

const OUTPUTS = [
  'step', 'jumpNow', 'attendanceChange', 'attendanceReset', 'setProtokollant', 'handOver',
  'cancelHandover',
] as const;

interface Inputs {
  meeting: Meeting;
  agenda: AgendaItem[];
  topIndex: number;
  attendance: Attendance[];
  savingAttendance: boolean;
  viewers: string[];
  wordCount: number;
  myVote: string | null;
  panel: DockPanel;
}

async function setup(over: Partial<Inputs> = {}) {
  const on = Object.fromEntries(OUTPUTS.map((name) => [name, jest.fn()])) as Record<
    (typeof OUTPUTS)[number],
    jest.Mock
  >;
  const view = await render(SessionDockComponent, {
    inputs: {
      meeting: meeting(),
      agenda: AGENDA,
      topIndex: 0,
      attendance: ATTENDANCE,
      savingAttendance: false,
      viewers: ['Pia Protokoll', 'Alina Admin'],
      wordCount: 12,
      myVote: null,
      panel: 'none',
      ...over,
    },
    on,
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  return { ...view, on, http };
}

const planned = (over: Partial<Meeting> = {}) => meeting({ status: 'planned', ...over });

describe('SessionDockComponent', () => {
  describe('live', () => {
    it('steps through the agenda and disables the edges', async () => {
      const { on, fixture } = await setup();
      expect(screen.getByText('1 von 3')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Vorheriger TOP' })).toBeDisabled();
      await userEvent.click(screen.getByRole('button', { name: 'Nächster TOP' }));
      expect(on.step).toHaveBeenCalledWith(1);
      fixture.componentRef.setInput('topIndex', 2);
      fixture.detectChanges();
      expect(screen.getByRole('button', { name: 'Nächster TOP' })).toBeDisabled();
      await userEvent.click(screen.getByRole('button', { name: 'Vorheriger TOP' }));
      expect(on.step).toHaveBeenCalledWith(-1);
    });

    it('shows no position and no word count while no item is open', async () => {
      await setup({ topIndex: -1 });
      expect(screen.getByText('–')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Nächster TOP' })).toBeDisabled();
      expect(screen.queryByText(/Wörter/)).toBeNull();
    });

    it('counts the words of the open item and shows the own ballot', async () => {
      await setup({ myVote: 'Ja' });
      expect(screen.getByText('12 Wörter')).toBeInTheDocument();
      expect(screen.getByText('Deine Stimme', { exact: false })).toHaveTextContent('Deine Stimme: Ja');
    });

    it('points back to the item that runs now', async () => {
      const { on } = await setup({ meeting: meeting({ currentAgendaItemId: 't-2' }), myVote: 'Ja' });
      expect(screen.getByText('Jetzt läuft TOP 2 · Bericht des Finanzreferats')).toBeInTheDocument();
      // The way back wins over the own ballot.
      expect(screen.queryByText(/Deine Stimme/)).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Jetzt' }));
      expect(on.jumpNow).toHaveBeenCalledWith('t-2');
    });

    it('names an untitled item that runs now', async () => {
      await setup({
        agenda: [AGENDA[0], { ...AGENDA[1], title: null }],
        meeting: meeting({ currentAgendaItemId: 't-2' }),
      });
      expect(screen.getByText('Jetzt läuft TOP 2 · Unbenannter TOP')).toBeInTheDocument();
    });

    it('opens the attendance with the room state and the viewers', async () => {
      const { on, http } = await setup();
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      const popover = screen.getByRole('dialog', { name: 'Anwesenheit' });
      expect(within(popover).getByText('Anwesend 1 von 3')).toBeInTheDocument();
      expect(within(popover).getByText('Mika Mitglied')).toBeInTheDocument();
      expect(within(popover).getByText('Protokollführung')).toBeInTheDocument();
      // Once in the roster, once in the viewer list.
      expect(within(popover).getAllByText('Alina Admin')).toHaveLength(2);
      expect(within(popover).getByText('2 live')).toBeInTheDocument();
      const [, mika] = within(popover).getAllByRole('group', { name: 'Anwesenheit' });
      await userEvent.click(within(mika).getByRole('button', { name: 'Auf „Offen“ zurücksetzen' }));
      expect(on.attendanceReset).toHaveBeenCalledWith(expect.objectContaining({ principalId: 'pr-2' }));
      await userEvent.click(within(mika).getByRole('button', { name: 'Unentschuldigt' }));
      expect(on.attendanceChange).toHaveBeenCalledWith({
        member: expect.objectContaining({ principalId: 'pr-2' }),
        status: 'absent',
      });
      http.match((r) => r.url.includes('/delegations/')).forEach((req) => req.flush(DELEGATION_CONTEXT));
    });

    it('says when nobody has the meeting open and hides the live count from a reader', async () => {
      const { fixture, http } = await setup({ viewers: [] });
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      expect(screen.getByText('Niemand hat die Sitzung gerade geöffnet.')).toBeInTheDocument();
      fixture.componentRef.setInput('meeting', meeting({ canWrite: false }));
      fixture.detectChanges();
      expect(screen.queryByText('0 live')).toBeNull();
      http.match((r) => r.url.includes('/delegations/')).forEach((req) => req.flush(DELEGATION_CONTEXT));
    });

    it('closes a popover on the backdrop, on the close button, on Escape and on a second click', async () => {
      const { fixture, container } = await setup();
      const dock = fixture.componentInstance;
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      await userEvent.click(screen.getByRole('button', { name: 'Schließen' }));
      expect(dock.panel()).toBe('none');
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      await userEvent.keyboard('{Escape}');
      expect(dock.panel()).toBe('none');
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      await userEvent.click(container.querySelector('.sd__backdrop') as HTMLElement);
      expect(dock.panel()).toBe('none');
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      expect(dock.panel()).toBe('none');
    });
  });

  describe('handover during a live meeting (Z3)', () => {
    const chip = (): HTMLElement => screen.getByTitle('Protokollführung übergeben');

    it('shows the minute-taker without the handover to a member who neither leads nor keeps the minutes', async () => {
      await setup({ meeting: meeting({ canManage: false, isProtokollant: false }) });
      expect(screen.queryByTitle('Protokollführung übergeben')).toBeNull();
      expect(screen.getByText('Protokoll: Pia Protokoll')).toBeInTheDocument();
    });

    it('offers the handover to the minute-taker', async () => {
      await setup({ meeting: meeting({ canManage: false, isProtokollant: true }) });
      expect(chip()).toHaveTextContent('Protokoll: Pia Protokoll');
    });

    it('hands over now to a member who can keep the minutes (O20)', async () => {
      const { on } = await setup({ attendance: WITH_VOTER });
      await userEvent.click(chip());
      const sheet = screen.getByRole('dialog', { name: 'Protokollführung übergeben' });
      expect(within(sheet).getByText('Protokoll: Pia Protokoll')).toBeInTheDocument();
      expect(within(sheet).queryByRole('button', { name: /Vera Votum/ })).toBeNull();
      // The current minute-taker is no target.
      await userEvent.click(within(sheet).getByRole('button', { name: /Pia Protokoll/, pressed: true }));
      expect(on.handOver).not.toHaveBeenCalled();
      await userEvent.click(chip());
      const again = screen.getByRole('dialog', { name: 'Protokollführung übergeben' });
      await userEvent.click(within(again).getByRole('button', { name: /Mika Mitglied/ }));
      expect(on.handOver).toHaveBeenCalledWith({ principalId: 'pr-2', mode: 'now' });
      expect(screen.queryByRole('dialog', { name: 'Protokollführung übergeben' })).toBeNull();
    });

    it('plans the handover for the next item', async () => {
      const { on } = await setup();
      await userEvent.click(chip());
      const sheet = screen.getByRole('dialog', { name: 'Protokollführung übergeben' });
      const next = within(sheet).getByRole('button', { name: 'Ab nächstem TOP' });
      expect(next).not.toBeDisabled();
      await userEvent.click(next);
      expect(next).toHaveAttribute('aria-pressed', 'true');
      await userEvent.click(within(sheet).getByRole('button', { name: 'Ab jetzt' }));
      await userEvent.click(next);
      await userEvent.click(within(sheet).getByRole('button', { name: /Alina Admin/ }));
      expect(on.handOver).toHaveBeenCalledWith({ principalId: 'pr-3', mode: 'next_item' });
    });

    it('hands over now on the last item, which has no next one', async () => {
      const { on, fixture } = await setup({ meeting: meeting({ currentAgendaItemId: 't-3' }) });
      await userEvent.click(chip());
      const sheet = screen.getByRole('dialog', { name: 'Protokollführung übergeben' });
      expect(within(sheet).getByRole('button', { name: 'Ab nächstem TOP' })).toBeDisabled();
      // A stale choice from before the last item still sends `now`.
      (fixture.componentInstance as unknown as { handoverMode: { set(v: string): void } }).handoverMode.set(
        'next_item',
      );
      fixture.detectChanges();
      await userEvent.click(within(sheet).getByRole('button', { name: /Mika Mitglied/ }));
      expect(on.handOver).toHaveBeenCalledWith({ principalId: 'pr-2', mode: 'now' });
    });

    it('shows and discards the planned handover', async () => {
      const plan = {
        principalId: 'pr-2',
        name: 'Mika Mitglied',
        fromAt: null,
        toAt: null,
        fromAgendaItemId: null,
        toAgendaItemId: null,
        fromPosition: null,
        toPosition: null,
      };
      const { on } = await setup({ meeting: meeting({ plannedHandover: plan }) });
      expect(within(chip()).getByText(/Übergabe geplant/)).toBeInTheDocument();
      await userEvent.click(chip());
      const sheet = screen.getByRole('dialog', { name: 'Protokollführung übergeben' });
      expect(within(sheet).getByText('Übergabe an Mika Mitglied mit dem nächsten TOP geplant.')).toBeInTheDocument();
      await userEvent.click(within(sheet).getByRole('button', { name: 'Verwerfen' }));
      expect(on.cancelHandover).toHaveBeenCalled();
    });
  });

  describe('planned', () => {
    it('says that the meeting is not open yet and shows no step', async () => {
      await setup({ meeting: planned() });
      expect(screen.getByText('Noch nicht eröffnet')).toBeInTheDocument();
      expect(screen.getByText('3 TOPs vorbereitet')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Nächster TOP' })).toBeNull();
      expect(screen.queryByText(/Wörter/)).toBeNull();
    });

    it('marks a missing minute-taker and opens the picker', async () => {
      const { container } = await setup({ meeting: planned({ protokollantId: null, protokollantName: null }) });
      const chip = screen.getByRole('button', { name: /Protokollführung fehlt/ });
      expect(chip).toHaveClass('sd__chip--warn');
      expect(chip).toHaveAttribute('aria-expanded', 'false');
      await userEvent.click(chip);
      expect(chip).toHaveAttribute('aria-expanded', 'true');
      expect(container.querySelector('.sd__pop--narrow')).toBeTruthy();
    });

    it('names the minute-taker on the chip once one is set', async () => {
      await setup({ meeting: planned() });
      expect(screen.getByRole('button', { name: /Protokoll: Pia Protokoll/ })).not.toHaveClass('sd__chip--warn');
    });

    it('searches the roster and names the picked member', async () => {
      const { on } = await setup({ meeting: planned({ protokollantId: null, protokollantName: null }) });
      await userEvent.click(screen.getByRole('button', { name: /Protokollführung fehlt/ }));
      const picker = screen.getByRole('dialog', { name: 'Protokollführung wählen' });
      expect(within(picker).getByText('PP')).toBeInTheDocument();
      expect(within(picker).getByText('Anwesend')).toBeInTheDocument();
      expect(within(picker).getByText('Offen')).toBeInTheDocument();
      const search = within(picker).getByRole('searchbox', { name: 'Mitglied suchen' });
      await userEvent.type(search, 'mika');
      expect(within(picker).getAllByRole('button', { name: /Mika Mitglied/ })).toHaveLength(1);
      expect(within(picker).queryByRole('button', { name: /Alina Admin/ })).toBeNull();
      await userEvent.clear(search);
      await userEvent.type(search, 'zzz');
      expect(within(picker).getByText('Kein Mitglied mit Protokollrecht gefunden.')).toBeInTheDocument();
      await userEvent.clear(search);
      await userEvent.click(within(picker).getByRole('button', { name: /Alina Admin/ }));
      expect(on.setProtokollant).toHaveBeenCalledWith('pr-3');
      expect(screen.queryByRole('dialog', { name: 'Protokollführung wählen' })).toBeNull();
    });

    it('offers only the members who can keep the minutes (O20)', async () => {
      await setup({ meeting: planned({ protokollantId: null, protokollantName: null }), attendance: WITH_VOTER });
      await userEvent.click(screen.getByRole('button', { name: /Protokollführung fehlt/ }));
      const picker = screen.getByRole('dialog', { name: 'Protokollführung wählen' });
      expect(within(picker).getByRole('button', { name: /Mika Mitglied/ })).toBeInTheDocument();
      expect(within(picker).queryByRole('button', { name: /Vera Votum/ })).toBeNull();
    });

    it('does not send the minute-taker that is already set', async () => {
      const { on } = await setup({ meeting: planned() });
      await userEvent.click(screen.getByRole('button', { name: /Protokoll: Pia Protokoll/ }));
      await userEvent.click(screen.getByRole('button', { name: /Pia Protokoll/, pressed: true }));
      expect(on.setProtokollant).not.toHaveBeenCalled();
    });

    it('falls back to the e-mail and the id for a member without a name', async () => {
      await setup({
        meeting: planned(),
        attendance: [
          { principalId: 'pr-7', displayName: null, email: 'kai.klar@x.de', status: 'absent', source: null, note: null, isSelf: false, canKeepProtocol: true },
          { principalId: 'pr-8', displayName: null, email: null, status: null, source: null, note: null, isSelf: false, canKeepProtocol: true },
        ],
      });
      await userEvent.click(screen.getByRole('button', { name: /Protokoll: Pia Protokoll/ }));
      const picker = screen.getByRole('dialog', { name: 'Protokollführung wählen' });
      expect(within(picker).getByText('kai.klar@x.de')).toBeInTheDocument();
      expect(within(picker).getByText('pr-8')).toBeInTheDocument();
      await userEvent.type(within(picker).getByRole('searchbox', { name: 'Mitglied suchen' }), 'kai');
      expect(within(picker).queryByText('pr-8')).toBeNull();
    });

    it('shows a plain mark to a lead who may not name the minute-taker', async () => {
      await setup({ meeting: planned({ protokollantId: null, protokollantName: null, canManage: false }) });
      expect(screen.getByText('Protokollführung fehlt')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Protokollführung fehlt/ })).toBeNull();
    });
  });
});
