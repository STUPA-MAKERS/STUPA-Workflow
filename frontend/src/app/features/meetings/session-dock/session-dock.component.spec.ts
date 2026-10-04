import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Attendance, Meeting } from '@core/api/models';
import {
  AGENDA,
  ATTENDANCE,
  WITH_VOTER,
  matchMediaQueries,
  meeting,
} from '../../../../testing/meeting-fixtures';
import { MEDIA } from '@stupa-makers/ui-kit';
import { type DockPanel, SessionDockComponent } from './session-dock.component';

const OUTPUTS = ['step', 'jumpNow', 'setProtokollant', 'pickHandover', 'cancelHandover'] as const;

interface Inputs {
  meeting: Meeting;
  agenda: AgendaItem[];
  topIndex: number;
  attendance: Attendance[];
  wordCount: number;
  myVote: string | null;
  panel: DockPanel;
}

let restoreMedia: (() => void) | null = null;
afterEach(() => {
  restoreMedia?.();
  restoreMedia = null;
  document.body.style.overflow = '';
});

/** Render the dock; `media` lists the width queries that match (none: wider than a phone). */
async function setup(over: Partial<Inputs> = {}, media: string[] = []) {
  restoreMedia = matchMediaQueries(...media);
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
      wordCount: 12,
      myVote: null,
      panel: 'none',
      ...over,
    },
    on,
  });
  return { ...view, on };
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

    it('counts the present members and opens the attendance sheet of the page', async () => {
      const { fixture } = await setup();
      const chip = screen.getByTitle('Anwesenheit');
      expect(chip).toHaveTextContent('Anwesend 1 von 3');
      await userEvent.click(chip);
      expect(fixture.componentInstance.panel()).toBe('attendance');
      expect(chip).toHaveAttribute('aria-expanded', 'true');
      // The sheet is the page's; the dock opens no popover for it.
      expect(screen.queryByRole('dialog')).toBeNull();
      await userEvent.click(chip);
      expect(fixture.componentInstance.panel()).toBe('none');
    });

    it('closes the minute-taker menu on the backdrop, on Escape and on a second click', async () => {
      const { fixture, container } = await setup();
      const dock = fixture.componentInstance;
      const chip = screen.getByTitle('Protokollführung übergeben');
      await userEvent.click(chip);
      expect(screen.getByRole('dialog', { name: 'Protokollführung übergeben' })).toBeInTheDocument();
      await userEvent.keyboard('{Escape}');
      expect(dock.panel()).toBe('none');
      await userEvent.click(chip);
      await userEvent.click(container.querySelector('.sd__backdrop') as HTMLElement);
      expect(dock.panel()).toBe('none');
      await userEvent.click(chip);
      await userEvent.click(chip);
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

    it('passes a pick on to the handover dialog, only for members who can keep the minutes (O20)', async () => {
      const { on } = await setup({ attendance: WITH_VOTER });
      await userEvent.click(chip());
      const menu = screen.getByRole('dialog', { name: 'Protokollführung übergeben' });
      expect(within(menu).getByText('Protokollführung übergeben an')).toBeInTheDocument();
      expect(within(menu).queryByRole('button', { name: /Vera Votum/ })).toBeNull();
      // The current minute-taker is marked and is no target.
      const current = within(menu).getByRole('button', { name: /Pia Protokoll/ });
      expect(current).toHaveAttribute('aria-current', 'true');
      expect(current).toHaveTextContent('Anwesend · führt das Protokoll');
      await userEvent.click(current);
      expect(on.pickHandover).not.toHaveBeenCalled();
      expect(screen.queryByRole('dialog', { name: 'Protokollführung übergeben' })).toBeNull();
      await userEvent.click(chip());
      const again = screen.getByRole('dialog', { name: 'Protokollführung übergeben' });
      await userEvent.click(within(again).getByRole('button', { name: /Mika Mitglied/ }));
      expect(on.pickHandover).toHaveBeenCalledWith('pr-2');
      expect(on.setProtokollant).not.toHaveBeenCalled();
      expect(screen.queryByRole('dialog', { name: 'Protokollführung übergeben' })).toBeNull();
    });

    it('shows and discards the planned handover', async () => {
      const plan = {
        principalId: 'pr-2',
        name: 'Mika Mitglied',
        fromAt: null,
        toAt: null,
        fromAgendaItemId: 't-2',
        toAgendaItemId: null,
        fromPosition: 2,
        toPosition: null,
      };
      const { on, fixture } = await setup({ meeting: meeting({ plannedHandover: plan }) });
      expect(within(chip()).getByText(/Übergabe geplant/)).toBeInTheDocument();
      await userEvent.click(chip());
      const menu = screen.getByRole('dialog', { name: 'Protokollführung übergeben' });
      expect(within(menu).getByText('Geplant')).toBeInTheDocument();
      expect(within(menu).getByText('übernimmt ab TOP 2')).toBeInTheDocument();
      await userEvent.click(within(menu).getByRole('button', { name: 'Verwerfen' }));
      expect(on.cancelHandover).toHaveBeenCalled();
      expect(fixture.componentInstance.panel()).toBe('none');
      // Without a known TOP number the plan says "with the next item".
      fixture.componentRef.setInput('meeting', meeting({ plannedHandover: { ...plan, fromPosition: null } }));
      fixture.detectChanges();
      await userEvent.click(chip());
      expect(screen.getByText('übernimmt mit dem nächsten TOP')).toBeInTheDocument();
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
      await setup({ meeting: planned({ protokollantId: null, protokollantName: null }) });
      const chip = screen.getByRole('button', { name: /Protokollführung fehlt/ });
      expect(chip).toHaveClass('sd__chip--warn');
      expect(chip).toHaveAttribute('aria-expanded', 'false');
      await userEvent.click(chip);
      expect(chip).toHaveAttribute('aria-expanded', 'true');
      expect(screen.getByRole('dialog', { name: 'Protokollführung wählen' })).toBeInTheDocument();
      expect(screen.getByText('Protokollführung zuweisen')).toBeInTheDocument();
    });

    it('names the minute-taker on the chip once one is set', async () => {
      await setup({ meeting: planned() });
      expect(screen.getByRole('button', { name: /Protokoll: Pia Protokoll/ })).not.toHaveClass('sd__chip--warn');
    });

    it('searches the roster and names the picked member at once', async () => {
      const { on } = await setup({ meeting: planned({ protokollantId: null, protokollantName: null }) });
      await userEvent.click(screen.getByRole('button', { name: /Protokollführung fehlt/ }));
      const picker = screen.getByRole('dialog', { name: 'Protokollführung wählen' });
      expect(within(picker).getByText('PP')).toBeInTheDocument();
      expect(within(picker).getByText('Anwesend')).toBeInTheDocument();
      expect(within(picker).getByText('Offen')).toBeInTheDocument();
      expect(within(picker).getByText('Nur Mitglieder mit dem Recht „Protokoll führen“.')).toBeInTheDocument();
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
      expect(on.pickHandover).not.toHaveBeenCalled();
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
      const picker = screen.getByRole('dialog', { name: 'Protokollführung wählen' });
      await userEvent.click(within(picker).getByRole('button', { name: /Pia Protokoll/ }));
      expect(on.setProtokollant).not.toHaveBeenCalled();
    });

    it('falls back to the e-mail for a member without a name, never to the id', async () => {
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
      expect(within(picker).queryByText('pr-8')).toBeNull();
      expect(within(picker).getByText('—')).toBeInTheDocument();
      await userEvent.type(within(picker).getByRole('searchbox', { name: 'Mitglied suchen' }), 'kai');
      expect(within(picker).queryByText('—')).toBeNull();
    });

    it('shows a plain mark to a lead who may not name the minute-taker', async () => {
      await setup({ meeting: planned({ protokollantId: null, protokollantName: null, canManage: false }) });
      expect(screen.getByText('Protokollführung fehlt')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Protokollführung fehlt/ })).toBeNull();
    });
  });

  describe('closed', () => {
    const closed = (over: Partial<Meeting> = {}) =>
      meeting({
        status: 'closed',
        closedAt: '2026-10-15T19:12:00Z',
        keeperPeriods: [
          { principalId: 'pr-1', name: 'Pia Protokoll', fromAt: '2026-10-15T16:04:00Z', toAt: '2026-10-15T16:55:00Z', fromAgendaItemId: 't-1', toAgendaItemId: 't-2', fromPosition: 1, toPosition: 2 },
          { principalId: 'pr-2', name: 'Mika Mitglied', fromAt: '2026-10-15T16:55:00Z', toAt: '2026-10-15T19:12:00Z', fromAgendaItemId: 't-2', toAgendaItemId: 't-3', fromPosition: 2, toPosition: 3 },
          { principalId: 'pr-1', name: 'Pia Protokoll', fromAt: '2026-10-15T19:00:00Z', toAt: '2026-10-15T19:12:00Z', fromAgendaItemId: 't-3', toAgendaItemId: 't-3', fromPosition: 3, toPosition: 3 },
        ],
        ...over,
      });

    it('says when the meeting closed, counts the TOPs and steps no more', async () => {
      await setup({ meeting: closed() });
      expect(screen.getByText(/^Geschlossen um \d\d:12$/)).toBeInTheDocument();
      expect(screen.getByText('3 TOPs')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Nächster TOP' })).toBeNull();
      expect(screen.queryByText(/Wörter/)).toBeNull();
    });

    it('names every minute-taker once, locked, and keeps the attendance', async () => {
      const { fixture } = await setup({ meeting: closed() });
      const keepers = screen.getByTitle('Sitzung geschlossen – die Protokollführung steht fest.');
      expect(keepers).toHaveTextContent('Protokoll: Pia Protokoll, Mika Mitglied');
      expect(keepers.tagName).toBe('SPAN');
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      expect(fixture.componentInstance.panel()).toBe('attendance');
    });

    it('falls back to the minute-taker and to the bare state without periods and a close time', async () => {
      await setup({ meeting: closed({ keeperPeriods: [], closedAt: null }), agenda: [AGENDA[0]] });
      expect(screen.getByText('Geschlossen')).toBeInTheDocument();
      expect(screen.getByText('1 TOP')).toBeInTheDocument();
      expect(screen.getByText('Protokoll: Pia Protokoll')).toBeInTheDocument();
    });
  });

  describe('on a phone', () => {
    it('opens the minute-taker menu as a bottom sheet over the navigation bar', async () => {
      const { fixture, container, on } = await setup(
        { meeting: planned({ protokollantId: null, protokollantName: null }) },
        [MEDIA.phone],
      );
      const dock = fixture.componentInstance;
      const host = fixture.nativeElement as HTMLElement;
      expect(host.style.zIndex).toBe('');
      await userEvent.click(screen.getByRole('button', { name: /Protokollführung fehlt/ }));
      let sheet = screen.getByRole('dialog', { name: 'Protokollführung wählen' });
      expect(sheet).toHaveClass('ss', 'ss--bottom');
      expect(sheet.querySelector('.ss__handle')).not.toBeNull();
      // No popover and no own backdrop: the sheet has its scrim.
      expect(container.querySelector('.sd__pop')).toBeNull();
      expect(container.querySelector('.sd__backdrop')).toBeNull();
      expect(host.style.zIndex).toBe('var(--z-dialog)');
      await userEvent.keyboard('{Escape}');
      expect(dock.panel()).toBe('none');
      expect(host.style.zIndex).toBe('');
      await userEvent.click(screen.getByRole('button', { name: /Protokollführung fehlt/ }));
      sheet = screen.getByRole('dialog', { name: 'Protokollführung wählen' });
      await userEvent.click(within(sheet).getByRole('button', { name: /Mika Mitglied/ }));
      expect(on.setProtokollant).toHaveBeenCalledWith('pr-2');
      expect(screen.queryByRole('dialog')).toBeNull();
    });

    it('keeps the dock below the dialog level while the attendance sheet of the page is open', async () => {
      const { fixture } = await setup({}, [MEDIA.phone]);
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      expect(fixture.componentInstance.panel()).toBe('attendance');
      expect((fixture.nativeElement as HTMLElement).style.zIndex).toBe('');
    });

    it('opens no sheet for the minute-taker without the right to change it', async () => {
      const { fixture } = await setup(
        { meeting: meeting({ canManage: false, isProtokollant: false }) },
        [MEDIA.phone],
      );
      fixture.componentRef.setInput('panel', 'protokollant');
      fixture.detectChanges();
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });
});
