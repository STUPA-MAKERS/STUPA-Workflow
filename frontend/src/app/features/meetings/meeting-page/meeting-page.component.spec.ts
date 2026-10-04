import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type {
  AgendaItem,
  Attendance,
  Meeting,
  Protocol,
} from '@core/api/models';
import { MEDIA } from '@stupa-makers/ui-kit';
import {
  AGENDA,
  ATTENDANCE,
  DELEGATION_CONTEXT,
  item,
  matchMediaQueries,
  meeting,
  protocol,
  vote,
} from '../../../../testing/meeting-fixtures';
import { MeetingPageComponent } from './meeting-page.component';

const OUTPUTS = [
  'back', 'selectTop', 'bodyChange', 'castVote', 'voteOpen', 'voteClose', 'voteCancel',
  'voteDelete', 'voteDialog', 'startSession', 'closeSession', 'finalize', 'openSettings',
  'deleteMeeting', 'toggleBeamer', 'attendanceChange', 'attendanceReset', 'addTop',
  'removeFromAgenda', 'startRename', 'cancelRename', 'renameTop', 'setNonPublic', 'moveTop',
  'dragStart', 'dragOver', 'drop', 'setProtokollant', 'handOver', 'cancelHandover',
] as const;

type Inputs = {
  meeting: Meeting;
  protocol: Protocol | null;
  agenda: AgendaItem[];
  top: AgendaItem | null;
  topIndex: number;
  canEdit: boolean;
  saveState: 'idle' | 'saving' | 'saved' | 'error';
  attendance: Attendance[];
  savingAttendance: boolean;
  viewers: string[];
  casting: string | null;
  deletingVote: string | null;
  finalizing: boolean;
  choices: Record<string, string>;
  savingAgenda: boolean;
  renamingTopId: string | null;
  renameDraft: string;
};

function inputs(over: Partial<Inputs> = {}): Inputs {
  return {
    meeting: meeting({ startedAt: '2026-10-15T16:04:00Z' }),
    protocol: protocol(),
    agenda: AGENDA,
    top: AGENDA[0],
    topIndex: 0,
    canEdit: true,
    saveState: 'saved',
    attendance: ATTENDANCE,
    savingAttendance: false,
    viewers: ['Pia Protokoll', 'Alina Admin'],
    casting: null,
    deletingVote: null,
    finalizing: false,
    choices: {},
    savingAgenda: false,
    renamingTopId: null,
    renameDraft: '',
    ...over,
  };
}

let restoreMedia: (() => void) | null = null;
afterEach(() => {
  restoreMedia?.();
  restoreMedia = null;
});

/** Render the page; `media` lists the width queries that match (none: narrow). */
async function setup(over: Partial<Inputs> = {}, media: string[] = []) {
  restoreMedia = matchMediaQueries(...media);
  const on = Object.fromEntries(OUTPUTS.map((name) => [name, jest.fn()])) as Record<
    (typeof OUTPUTS)[number],
    jest.Mock
  >;
  const view = await render(MeetingPageComponent, {
    inputs: inputs(over),
    on,
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const flushDelegations = () =>
    http.match((r) => r.url.includes('/delegations/')).forEach((req) => req.flush(DELEGATION_CONTEXT));
  return { ...view, on, http, flushDelegations };
}

async function openMenu(): Promise<HTMLElement> {
  await userEvent.click(screen.getByRole('button', { name: 'Sitzungsmenü' }));
  return screen.findByRole('menu');
}

describe('MeetingPageComponent', () => {
  describe('header', () => {
    it('shows title, status, Gremium, date and the real start', async () => {
      const { on } = await setup();
      const bar = screen.getByRole('toolbar', { name: 'Sitzungssteuerung' });
      expect(within(bar).getByRole('heading', { level: 1, name: 'Konstituierende Sitzung' })).toBeInTheDocument();
      expect(within(bar).getByText('Live')).toBeInTheDocument();
      expect(within(bar).getByText(/^StuPa · Do\., 15\.10\.2026 · seit \d\d:04$/)).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Sitzungen' }));
      expect(on.back).toHaveBeenCalled();
    });

    it('shows the planned start before the opening and start and close after the close', async () => {
      const { fixture } = await setup({ meeting: meeting({ status: 'planned', gremiumName: null }) });
      expect(screen.getByText(/^Do\., 15\.10\.2026 · 18:00$/)).toBeInTheDocument();
      fixture.componentRef.setInput(
        'meeting',
        meeting({ status: 'closed', date: null, startedAt: '2026-10-15T16:00:00Z', closedAt: '2026-10-15T18:30:00Z' }),
      );
      fixture.detectChanges();
      expect(screen.getByText(/^StuPa · \d\d:00–\d\d:30$/)).toBeInTheDocument();
      fixture.componentRef.setInput(
        'meeting',
        meeting({ status: 'closed', date: 'kein Datum', startedAt: '2026-10-15T16:00:00Z', closedAt: null }),
      );
      fixture.detectChanges();
      expect(screen.getByText(/^StuPa · kein Datum · \d\d:00$/)).toBeInTheDocument();
      fixture.componentRef.setInput('meeting', meeting({ status: 'planned', startTime: null }));
      fixture.detectChanges();
      expect(screen.getByText(/^StuPa · Do\., 15\.10\.2026$/)).toBeInTheDocument();
    });

    it('lists the people who have the meeting open (N22)', async () => {
      await setup();
      const chip = screen.getByRole('button', { name: '2 live' });
      expect(chip).toHaveAttribute('title', 'Live dabei: Pia Protokoll, Alina Admin');
      await userEvent.click(chip);
      const list = screen.getByRole('list', { name: 'Live dabei' });
      expect(within(list).getByText('Alina Admin')).toBeInTheDocument();
      fireEvent.blur(chip);
      expect(screen.queryByRole('list', { name: 'Live dabei' })).toBeNull();
    });

    it('says when nobody is there and hides the presence from a reader', async () => {
      const { fixture } = await setup({ viewers: [] });
      const chip = screen.getByRole('button', { name: '0 live' });
      expect(chip).toHaveAttribute('title', 'Niemand hat die Sitzung gerade geöffnet.');
      await userEvent.click(chip);
      expect(screen.getAllByText('Niemand hat die Sitzung gerade geöffnet.').length).toBeGreaterThan(0);
      fixture.componentRef.setInput('meeting', meeting({ canWrite: false }));
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: '0 live' })).toBeNull();
    });

    it('closes a live meeting and names an open vote in the tooltip', async () => {
      const { on, fixture } = await setup();
      const close = screen.getByRole('button', { name: 'Sitzung schließen' });
      expect(close).toHaveClass('btn--danger');
      await userEvent.click(close);
      expect(on.closeSession).toHaveBeenCalled();
      fixture.componentRef.setInput('meeting', meeting({ votes: [vote()] }));
      fixture.detectChanges();
      expect(screen.getByRole('button', { name: 'Sitzung schließen' })).toHaveAttribute(
        'title',
        'Erst die offene Abstimmung schließen oder abbrechen.',
      );
    });

    it('finalizes the draft of a closed meeting as a step of its own (O13)', async () => {
      const { on, fixture } = await setup({ meeting: meeting({ status: 'closed' }) });
      expect(screen.queryByRole('button', { name: 'Sitzung schließen' })).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & versenden' }));
      expect(on.finalize).toHaveBeenCalled();
      fixture.componentRef.setInput('protocol', protocol({ status: 'rendering', isLocked: true }));
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Finalisieren & versenden' })).toBeNull();
    });

    it('offers no main action without the lead right', async () => {
      await setup({ meeting: meeting({ canControl: false }) });
      expect(screen.queryByRole('button', { name: 'Sitzung schließen' })).toBeNull();
    });

    it('runs the session menu: settings, attendance, beamer and delete', async () => {
      const { on, flushDelegations } = await setup();
      let menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Sitzung bearbeiten' }));
      expect(on.openSettings).toHaveBeenCalled();
      menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Beamer-Ansicht' }));
      expect(on.toggleBeamer).toHaveBeenCalled();
      menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Sitzung löschen' }));
      expect(on.deleteMeeting).toHaveBeenCalled();
      menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Anwesenheit erfassen' }));
      expect(screen.getByRole('dialog', { name: 'Anwesenheit' })).toBeInTheDocument();
      flushDelegations();
    });

    it('offers only the attendance to a member without the manage right', async () => {
      await setup({ meeting: meeting({ canManage: false }) });
      const menu = await openMenu();
      expect(within(menu).queryByRole('menuitem', { name: 'Sitzung bearbeiten' })).toBeNull();
      expect(within(menu).queryByRole('menuitem', { name: 'Sitzung löschen' })).toBeNull();
    });

    it('keeps the beamer in the header on a wide screen', async () => {
      const { on } = await setup({}, [MEDIA.wide]);
      await userEvent.click(screen.getByRole('button', { name: 'Beamer-Ansicht' }));
      expect(on.toggleBeamer).toHaveBeenCalled();
      const menu = await openMenu();
      expect(within(menu).queryByRole('menuitem', { name: 'Beamer-Ansicht' })).toBeNull();
    });

    it('moves the close and the finalize into the menu on a phone', async () => {
      const { on, fixture } = await setup({}, [MEDIA.phone]);
      expect(screen.queryByRole('button', { name: 'Sitzung schließen' })).toBeNull();
      let menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Sitzung schließen' }));
      expect(on.closeSession).toHaveBeenCalled();
      fixture.componentRef.setInput('meeting', meeting({ status: 'closed' }));
      fixture.detectChanges();
      menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Finalisieren & versenden' }));
      expect(on.finalize).toHaveBeenCalled();
    });
  });

  describe('planned', () => {
    const planned = (over: Partial<Meeting> = {}) => meeting({ status: 'planned', ...over });

    it('shows the checklist and keeps the opening disabled without a minute-taker', async () => {
      await setup({ meeting: planned({ protokollantId: null, protokollantName: null }), protocol: null });
      expect(screen.getByRole('heading', { name: 'Sitzung vorbereiten' })).toBeInTheDocument();
      const starts = screen.getAllByRole('button', { name: 'Sitzung eröffnen' });
      expect(starts).toHaveLength(2);
      starts.forEach((b) => expect(b).toBeDisabled());
      // No sheet and no vote column before the opening.
      expect(screen.queryByText('Noch kein TOP geöffnet')).toBeNull();
      expect(screen.queryByRole('complementary')).toBeNull();
    });

    it('opens from the header and from the checklist once a minute-taker is set', async () => {
      const { on } = await setup({ meeting: planned(), protocol: null });
      const starts = screen.getAllByRole('button', { name: 'Sitzung eröffnen' });
      await userEvent.click(starts[0]);
      await userEvent.click(starts[1]);
      expect(on.startSession).toHaveBeenCalledTimes(2);
    });

    it('opens the matching place from every card', async () => {
      const { flushDelegations } = await setup({ meeting: planned(), protocol: null });
      await userEvent.click(screen.getByRole('button', { name: 'Tagesordnung bearbeiten' }));
      const sheet = await screen.findByRole('dialog', { name: 'Tagesordnung' });
      expect(within(sheet).getByRole('heading', { name: 'Tagesordnung · 3 TOPs' })).toBeInTheDocument();
      await userEvent.click(within(sheet).getByRole('button', { name: 'Schließen' }));
      await userEvent.click(screen.getByRole('button', { name: 'Ändern' }));
      expect(screen.getByRole('dialog', { name: 'Protokollführung wählen' })).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Erfassen' }));
      expect(screen.getByRole('dialog', { name: 'Anwesenheit' })).toBeInTheDocument();
      flushDelegations();
    });

    it('focuses the agenda pane on a wide screen and marks no row', async () => {
      await setup({ meeting: planned(), protocol: null }, [MEDIA.wide]);
      expect(screen.getByRole('button', { name: 'Begrüßung' })).not.toHaveAttribute('aria-current');
      await userEvent.click(screen.getByRole('button', { name: 'Tagesordnung bearbeiten' }));
      expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Tagesordnung · 3 TOPs' }));
    });

    it('shows a reader without session rights the sheet instead of the checklist', async () => {
      await setup({ meeting: planned({ canControl: false, canManage: false }), protocol: null });
      expect(screen.queryByRole('heading', { name: 'Sitzung vorbereiten' })).toBeNull();
      expect(screen.getByText(/beim Start der Sitzung angelegt/)).toBeInTheDocument();
    });
  });

  describe('live', () => {
    it('shows the agenda beside the sheet on a wide screen and opens an item', async () => {
      const { on } = await setup({}, [MEDIA.wide]);
      expect(screen.getByRole('region', { name: 'Tagesordnung' })).toBeInTheDocument();
      expect(screen.queryByTitle('Tagesordnung öffnen')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Bericht des Finanzreferats' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
    });

    it('opens the agenda as a sheet below the wide layout and closes it on a pick', async () => {
      const { on } = await setup();
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      const sheet = await screen.findByRole('dialog', { name: 'Tagesordnung' });
      await userEvent.click(within(sheet).getByRole('button', { name: 'Bericht des Finanzreferats' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
      expect(screen.queryByRole('dialog', { name: 'Tagesordnung' })).toBeNull();
    });

    it('passes the agenda changes on', async () => {
      const { on } = await setup({}, [MEDIA.wide]);
      await userEvent.click(screen.getByRole('button', { name: 'TOP hinzufügen' }));
      expect(on.addTop).toHaveBeenCalled();
      const rows = screen.getAllByRole('listitem');
      await userEvent.click(within(rows[1]).getByRole('button', { name: /Aktionen für/ }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Nach unten' }));
      expect(on.moveTop).toHaveBeenCalledWith({ from: 1, to: 2 });
      await userEvent.click(within(rows[1]).getByRole('button', { name: /Aktionen für/ }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'TOP umbenennen' }));
      expect(on.startRename).toHaveBeenCalledWith(AGENDA[1]);
      await userEvent.click(within(rows[1]).getByRole('button', { name: /Aktionen für/ }));
      await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Nicht öffentlich (NÖ)' }));
      expect(on.setNonPublic).toHaveBeenCalledWith({ item: AGENDA[1], nonPublic: true });
      await userEvent.click(within(rows[1]).getByRole('button', { name: /Aktionen für/ }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'TOP entfernen' }));
      expect(on.removeFromAgenda).toHaveBeenCalledWith('t-2');
      rows[0].dispatchEvent(new Event('dragstart'));
      rows[1].dispatchEvent(new Event('dragover'));
      rows[1].dispatchEvent(new Event('drop'));
      expect(on.dragStart).toHaveBeenCalledWith(0);
      expect(on.dragOver).toHaveBeenCalled();
      expect(on.drop).toHaveBeenCalledWith(1);
    });

    it('passes the inline rename on', async () => {
      const { on } = await setup({ renamingTopId: 't-1', renameDraft: 'Neu' }, [MEDIA.wide]);
      const input = screen.getByRole('textbox', { name: 'TOP umbenennen' });
      await userEvent.type(input, '{Enter}');
      expect(on.renameTop).toHaveBeenCalledWith(AGENDA[0]);
      await userEvent.type(input, '{Escape}');
      expect(on.cancelRename).toHaveBeenCalled();
    });

    it('steps through the agenda from the dock', async () => {
      const { on } = await setup({ top: AGENDA[1], topIndex: 1 });
      await userEvent.click(screen.getByRole('button', { name: 'Nächster TOP' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-3');
      await userEvent.click(screen.getByRole('button', { name: 'Vorheriger TOP' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-1');
      expect(screen.getByText('1 Wörter')).toBeInTheDocument();
    });

    it('steps nowhere without an open item and counts no words', async () => {
      const { fixture, on } = await setup({ top: null, topIndex: -1 });
      fixture.componentInstance.step(1);
      expect(on.selectTop).not.toHaveBeenCalled();
      expect(screen.queryByText(/Wörter/)).toBeNull();
      fixture.componentRef.setInput('top', AGENDA[0]);
      fixture.componentRef.setInput('topIndex', 0);
      fixture.detectChanges();
      fixture.componentInstance.step(-1);
      expect(on.selectTop).not.toHaveBeenCalled();
    });

    it('passes the edits of the sheet on and makes the editor read-only for a reader', async () => {
      const { container, fixture } = await setup();
      expect(container.querySelector('.mde__host--disabled')).toBeNull();
      fixture.componentRef.setInput('canEdit', false);
      fixture.detectChanges();
      expect(container.querySelector('.mde__host--disabled')).toBeTruthy();
      fixture.componentRef.setInput('canEdit', true);
      fixture.componentRef.setInput('protocol', protocol({ isLocked: true, status: 'rendering' }));
      fixture.detectChanges();
      expect(container.querySelector('.mde__host--disabled')).toBeTruthy();
    });

    it('passes the dock actions on', async () => {
      const { on, flushDelegations } = await setup({ meeting: meeting({ currentAgendaItemId: 't-2' }) });
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Jetzt' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
      await userEvent.click(screen.getByTitle('Protokollführung übergeben'));
      await userEvent.click(screen.getByRole('button', { name: /Mika Mitglied/ }));
      expect(on.handOver).toHaveBeenCalledWith({ principalId: 'pr-2', mode: 'now' });
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      const popover = screen.getByRole('dialog', { name: 'Anwesenheit' });
      const [, mika] = within(popover).getAllByRole('group', { name: 'Anwesenheit' });
      await userEvent.click(within(mika).getByRole('button', { name: 'Unentschuldigt' }));
      expect(on.attendanceChange).toHaveBeenCalled();
      await userEvent.click(within(mika).getByRole('button', { name: 'Auf „Offen“ zurücksetzen' }));
      expect(on.attendanceReset).toHaveBeenCalled();
      flushDelegations();
    });

    it('passes the keeper pick and the discard of a planned handover on', async () => {
      const plan = {
        principalId: 'pr-2', name: 'Mika Mitglied', fromAt: null, toAt: null,
        fromAgendaItemId: null, toAgendaItemId: null, fromPosition: null, toPosition: null,
      };
      const { on, fixture } = await setup({ meeting: meeting({ plannedHandover: plan }) });
      await userEvent.click(screen.getByTitle('Protokollführung übergeben'));
      await userEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
      expect(on.cancelHandover).toHaveBeenCalled();
      fixture.componentRef.setInput('meeting', meeting({ status: 'planned', protokollantId: null }));
      fixture.componentRef.setInput('protocol', null);
      fixture.detectChanges();
      await userEvent.click(screen.getByRole('button', { name: 'Zuweisen' }));
      await userEvent.click(screen.getByRole('button', { name: /Alina Admin/ }));
      expect(on.setProtokollant).toHaveBeenCalledWith('pr-3');
    });
  });

  describe('votes', () => {
    it('shows the open vote first and runs it', async () => {
      const votes = [
        vote({ id: 'v-0', status: 'cancelled', question: 'Vertagen?' }),
        vote({ id: 'v-1' }),
        vote({ id: 'v-x', agendaItemId: 't-2', question: 'Anderer TOP?' }),
      ];
      const { on } = await setup({ meeting: meeting({ votes }) });
      const cards = screen.getAllByRole('heading', { level: 3 });
      expect(cards.map((h) => h.textContent)).toEqual(['Wird der Nachtragshaushalt beschlossen?', 'Vertagen?']);
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung schließen' }));
      expect(on.voteClose).toHaveBeenCalledWith('v-1');
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung abbrechen' }));
      expect(on.voteCancel).toHaveBeenCalledWith('v-1');
      await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
      expect(on.castVote).toHaveBeenCalledWith({ voteId: 'v-1', choice: 'yes' });
      await userEvent.click(screen.getByRole('button', { name: 'Beschlussfrage löschen' }));
      expect(on.voteDelete).toHaveBeenCalledWith('v-0');
      // A second vote waits until the open one ends.
      expect(screen.queryByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeNull();
    });

    it('opens a planned vote', async () => {
      const { on } = await setup({ meeting: meeting({ votes: [vote({ status: 'draft' })] }) });
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung öffnen' }));
      expect(on.voteOpen).toHaveBeenCalledWith('v-1');
    });

    it('shows the own ballot in the dock: this session, the server, a secret one', async () => {
      const { fixture } = await setup({ meeting: meeting({ votes: [vote()] }), choices: { 'v-1': 'no' } });
      expect(screen.getByText('Deine Stimme', { exact: false })).toHaveTextContent('Deine Stimme: Nein');
      fixture.componentRef.setInput('choices', {});
      fixture.componentRef.setInput('meeting', meeting({ votes: [vote({ myBallot: { cast: true, choice: 'yes' } })] }));
      fixture.detectChanges();
      expect(screen.getByText('Deine Stimme', { exact: false })).toHaveTextContent('Deine Stimme: Ja');
      fixture.componentRef.setInput('meeting', meeting({ votes: [vote({ myBallot: { cast: true, choice: null } })] }));
      fixture.detectChanges();
      expect(screen.getByText('Deine Stimme', { exact: false })).toHaveTextContent('Deine Stimme: abgegeben');
      fixture.componentRef.setInput('meeting', meeting({ votes: [vote({ myBallot: { cast: false, choice: null } })] }));
      fixture.detectChanges();
      expect(screen.queryByText(/Deine Stimme:/)).toBeNull();
    });

    it('offers a decision question on a free-text item, and one vote per application item', async () => {
      const { on, fixture } = await setup();
      await userEvent.click(screen.getByRole('button', { name: 'Beschlussfrage hinzufügen' }));
      expect(on.voteDialog).toHaveBeenCalledWith(AGENDA[0]);
      fixture.componentRef.setInput('top', AGENDA[2]);
      fixture.componentRef.setInput('topIndex', 2);
      fixture.detectChanges();
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung öffnen' }));
      expect(on.voteDialog).toHaveBeenCalledWith(AGENDA[2]);
      fixture.componentRef.setInput(
        'meeting',
        meeting({ votes: [vote({ agendaItemId: 't-3', status: 'closed', result: 'passed' })] }),
      );
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Abstimmung öffnen' })).toBeNull();
    });

    it('offers no vote before the opening, after the close, when locked or without the right', async () => {
      const { fixture } = await setup({ meeting: meeting({ status: 'closed' }) });
      expect(screen.queryByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeNull();
      expect(screen.queryByRole('complementary')).toBeNull();
      fixture.componentRef.setInput('meeting', meeting({ canManageVotes: false }));
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeNull();
      fixture.componentRef.setInput('meeting', meeting());
      fixture.componentRef.setInput('protocol', protocol({ isLocked: true, status: 'rendering' }));
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeNull();
      fixture.componentRef.setInput('protocol', protocol());
      fixture.componentRef.setInput('top', null);
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeNull();
    });

    it('carries the result into the text until it is there, then goes quiet', async () => {
      const closed = vote({ status: 'closed', result: 'passed', counts: { yes: 3, no: 1, abstain: 0 }, leading: 'yes', revealed: true });
      // A trailing hard break from a phone keyboard must not survive as an empty line.
      const { on, fixture } = await setup({ meeting: meeting({ votes: [closed] }), top: item({ body: 'Aussprache.\\\n' }) });
      await userEvent.click(screen.getByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' }));
      const payload = on.bodyChange.mock.calls[0][0] as { itemId: string; body: string };
      expect(payload.itemId).toBe('t-1');
      expect(payload.body).toBe(
        'Aussprache.\n\n> [!abstimmung] **Wird der Nachtragshaushalt beschlossen?**\n> yes: 3, no: 1, abstain: 0',
      );
      fixture.componentRef.setInput('top', item({ body: payload.body }));
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' })).toBeNull();
      // An empty text takes the result alone.
      fixture.componentRef.setInput('top', item({ body: null }));
      fixture.detectChanges();
      await userEvent.click(screen.getByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' }));
      const bodies = on.bodyChange.mock.calls.map((c) => (c[0] as { body: string }).body);
      expect(bodies.some((b) => b.startsWith('> [!abstimmung]'))).toBe(true);
    });

    it('inserts nothing without an open item and offers no insert to a reader', async () => {
      const closed = vote({ status: 'closed', result: 'passed', counts: { yes: 3 } });
      const { on, fixture } = await setup({ meeting: meeting({ votes: [closed] }), canEdit: false });
      expect(screen.queryByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' })).toBeNull();
      fixture.componentRef.setInput('top', null);
      fixture.detectChanges();
      fixture.componentInstance.insertResult(closed);
      expect(on.bodyChange).not.toHaveBeenCalled();
    });
  });

  it('keeps the height of the dock as room below the page on a phone', async () => {
    const callbacks: (() => void)[] = [];
    const original = globalThis.ResizeObserver;
    Object.defineProperty(globalThis, 'ResizeObserver', {
      writable: true,
      value: class {
        constructor(cb: () => void) {
          callbacks.push(cb);
        }
        observe(): void {}
        disconnect(): void {}
      },
    });
    try {
      const { fixture } = await setup();
      const dock = fixture.nativeElement.querySelector('app-session-dock') as HTMLElement;
      Object.defineProperty(dock, 'offsetHeight', { value: 96 });
      callbacks.forEach((cb) => cb());
      fixture.detectChanges();
      expect((fixture.nativeElement as HTMLElement).style.getPropertyValue('--fx-dock-h')).toBe('96px');
    } finally {
      Object.defineProperty(globalThis, 'ResizeObserver', { writable: true, value: original });
    }
  });
});
