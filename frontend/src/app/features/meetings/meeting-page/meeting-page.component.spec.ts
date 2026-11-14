import { provideHttpClient } from '@angular/common/http';
import { renderDeferred } from '../../../../testing/defer';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import type { ComponentFixture } from '@angular/core/testing';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type {
  AgendaItem,
  Attendance,
  Meeting,
  Protocol,
} from '@core/api/models';
import type { LiveViewer } from '@core/ws/ws-messages';
import { By } from '@angular/platform-browser';
import { AvatarComponent, MEDIA } from '@stupa-makers/ui-kit';
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
  'setProtokollant', 'pickHandover', 'cancelHandover',
  'attendanceConflictResolved', 'nextTop', 'setDone', 'voteSource',
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
  viewers: LiveViewer[];
  casting: string | null;
  deletingVote: string | null;
  finalizing: boolean;
  choices: Record<string, string>;
  savingAgenda: boolean;
  renamingTopId: string | null;
  renameDraft: string;
  attendanceConflict: string | null;
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
    viewers: [
      { id: 'p-pia', name: 'Pia Protokoll' },
      { id: null, name: 'Alina Admin' },
    ],
    casting: null,
    deletingVote: null,
    finalizing: false,
    choices: {},
    savingAgenda: false,
    renamingTopId: null,
    renameDraft: '',
    attendanceConflict: null,
    ...over,
  };
}

let restoreMedia: (() => void) | null = null;
afterEach(() => {
  restoreMedia?.();
  restoreMedia = null;
});

/** Render the page; `media` lists the width queries that match (none: narrow). */
/** Start the rename of the first TOP from its row menu, as the page does after the click. */
async function startAgendaRename(fixture: ComponentFixture<MeetingPageComponent>): Promise<void> {
  const rows = screen.getAllByRole('listitem');
  await userEvent.click(within(rows[0]).getByRole('button', { name: /Aktionen für/ }));
  await userEvent.click(await screen.findByRole('menuitem', { name: 'TOP umbenennen' }));
  fixture.componentRef.setInput('renamingTopId', 't-1');
  fixture.detectChanges();
}

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
  const flushDelegations = () => {
    http.match((r) => r.url.includes('/delegations/')).forEach((req) => req.flush(DELEGATION_CONTEXT));
    http.match((r) => r.url.endsWith('/delegations')).forEach((req) => req.flush([]));
  };
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
      expect(within(bar).getByText(/^StuPa · Do, 15\.10\.2026 · seit \d\d:04$/)).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Sitzungen' }));
      expect(on.back).toHaveBeenCalled();
    });

    it('shows the planned start before the opening and start and close after the close', async () => {
      const { fixture } = await setup({ meeting: meeting({ status: 'planned', gremiumName: null }) });
      expect(screen.getByText(/^Do, 15\.10\.2026 · 18:00$/)).toBeInTheDocument();
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
      expect(screen.getByText(/^StuPa · Do, 15\.10\.2026$/)).toBeInTheDocument();
    });

    it('lists the people who have the meeting open', async () => {
      const { fixture } = await setup();
      const chip = screen.getByRole('button', { name: '2 live' });
      expect(chip).toHaveAttribute('title', 'Live dabei: Pia Protokoll, Alina Admin');
      await userEvent.click(chip);
      const list = screen.getByRole('list', { name: 'Live dabei' });
      expect(within(list).getByText('Alina Admin')).toBeInTheDocument();
      const avatars = fixture.debugElement
        .query(By.css('.mp__viewers'))
        .queryAll(By.directive(AvatarComponent))
        .map((d) => (d.componentInstance as AvatarComponent).principalId());
      expect(avatars).toEqual(['p-pia', null]);
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

    /**
     * The open vote is on another item than the one in the sheet. No line stands beside the button:
     * the reason is its tooltip only.
     */
    it('closes a live meeting, and an open vote on any item blocks the close', async () => {
      const { on, fixture } = await setup();
      const close = screen.getByRole('button', { name: 'Sitzung schließen' });
      expect(close).toHaveClass('btn--danger');
      expect(close).toBeEnabled();
      await userEvent.click(close);
      expect(on.closeSession).toHaveBeenCalledTimes(1);
      fixture.componentRef.setInput('meeting', meeting({ votes: [vote({ agendaItemId: AGENDA[1].id })] }));
      fixture.detectChanges();
      const blocked = screen.getByRole('button', { name: 'Sitzung schließen' });
      expect(blocked).toBeDisabled();
      expect(blocked).toHaveAttribute('title', 'Erst die offene Abstimmung schließen oder abbrechen.');
      expect(screen.queryByText('Erst die offene Abstimmung schließen oder abbrechen.')).toBeNull();
      await userEvent.click(blocked);
      expect(on.closeSession).toHaveBeenCalledTimes(1);
    });

    it('finalizes the draft of a closed meeting as a step of its own', async () => {
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

    it('opens the cards that link the meeting in a sheet from the menu (spec 000551)', async () => {
      const { http, fixture } = await setup({}, [MEDIA.wide]);
      const menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'To-Dos' }));
      fixture.detectChanges();
      const linked = http.expectOne((r) => r.url.endsWith('/api/todos/linked') && r.params.get('kind') === 'meeting');
      linked.flush([
        {
          id: 'k-1',
          boardId: 'b-1',
          boardName: 'StuPa',
          title: 'Raum für die Sitzung buchen',
          columnName: 'Offen',
          isDone: false,
          dueDate: null,
          assignees: [],
          event: null,
          balance: null,
        },
      ]);
      http.expectOne((r) => r.url.endsWith('/api/todos/boards')).flush([{ id: 'b-1', name: 'StuPa', kind: 'gremium', gremiumId: 'g-1', canWrite: true }]);
      fixture.detectChanges();
      const sheet = await screen.findByRole('dialog', { name: 'To-Dos' });
      expect(within(sheet).getByRole('link', { name: 'Raum für die Sitzung buchen' })).toHaveAttribute('href', '/todos?card=k-1');
      expect(within(sheet).getByRole('button', { name: 'Mit To-Do verknüpfen' })).toBeInTheDocument();
      expect(within(sheet).getByRole('button', { name: 'To-Do anlegen' })).toBeInTheDocument();
      expect(document.querySelector('.mp__agenda app-todo-linked-list[kind="meeting"]')).toBeNull();
    });

    /** A final protocol needs `meeting.delete_finalized`: the server then sends no `canDelete`. */
    it('offers no delete without canDelete', async () => {
      await setup({ meeting: meeting({ canDelete: false }) });
      const menu = await openMenu();
      expect(within(menu).getByRole('menuitem', { name: 'Sitzung bearbeiten' })).toBeInTheDocument();
      expect(within(menu).queryByRole('menuitem', { name: 'Sitzung löschen' })).toBeNull();
    });

    /** The beamer route needs session.manage, so a minute-taker without it gets no beamer. */
    it('offers only the attendance to a member without the manage right', async () => {
      await setup({ meeting: meeting({ canManage: false, canDelete: false }) });
      const menu = await openMenu();
      expect(within(menu).queryByRole('menuitem', { name: 'Sitzung bearbeiten' })).toBeNull();
      expect(within(menu).queryByRole('menuitem', { name: 'Sitzung löschen' })).toBeNull();
      expect(within(menu).queryByRole('menuitem', { name: 'Beamer-Ansicht' })).toBeNull();
    });

    it('shows no beamer button on a wide screen without the manage right', async () => {
      await setup({ meeting: meeting({ canManage: false }) }, [MEDIA.wide]);
      expect(screen.queryByRole('button', { name: 'Beamer-Ansicht' })).toBeNull();
    });

    it('keeps the beamer in the dock on a wide screen', async () => {
      const { on } = await setup({}, [MEDIA.wide]);
      await userEvent.click(screen.getByRole('button', { name: 'Beamer-Ansicht' }));
      expect(on.toggleBeamer).toHaveBeenCalled();
      const menu = await openMenu();
      expect(within(menu).queryByRole('menuitem', { name: 'Beamer-Ansicht' })).toBeNull();
    });

    it('disables the close in the phone menu while a vote is open', async () => {
      const { on } = await setup({ meeting: meeting({ votes: [vote()] }) }, [MEDIA.phone]);
      const menu = await openMenu();
      const close = within(menu).getByRole('menuitem', { name: /Sitzung schließen/ });
      expect(close).toHaveAttribute('aria-disabled', 'true');
      expect(close).toHaveTextContent('Erst die offene Abstimmung schließen oder abbrechen.');
      await userEvent.click(close);
      expect(on.closeSession).not.toHaveBeenCalled();
    });

    it('opens the agenda and the attendance as bottom sheets on a phone', async () => {
      const { flushDelegations } = await setup({}, [MEDIA.phone]);
      await userEvent.click(within(await openMenu()).getByRole('menuitem', { name: 'Tagesordnung' }));
      const agenda = screen.getByRole('dialog', { name: 'Tagesordnung' });
      expect(agenda).toHaveClass('ss--bottom');
      await userEvent.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).toBeNull();
      const menu = await openMenu();
      expect(within(menu).queryByRole('menuitem', { name: 'Anwesenheit erfassen' })).toBeNull();
      await userEvent.keyboard('{Escape}');
      await userEvent.click(screen.getByRole('button', { name: 'Anwesenheit' }));
      expect(screen.getByRole('dialog', { name: 'Anwesenheit' })).toHaveClass('ss--bottom');
      flushDelegations();
    });

    /** "Aa" turns the phone dock into the format tools; the back arrow turns it back. */
    it('swaps the phone dock row for the format tools and back', async () => {
      const { fixture } = await setup({}, [MEDIA.phone]);
      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('.ts__bar')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Format' }));
      const tools = screen.getByRole('toolbar', { name: 'Format' });
      expect(within(tools).getByRole('button', { name: 'Fett' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Nächster TOP' })).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zur Navigation' }));
      expect(screen.getByRole('button', { name: 'Nächster TOP' })).toBeInTheDocument();
    });

    /** The protocol has the phone page to itself: the vote cards open as a bottom sheet. */
    it('opens the vote cards from the phone dock instead of above the text', async () => {
      const { fixture } = await setup({}, [MEDIA.phone]);
      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('aside.mp__votes')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmungen' }));
      const sheet = screen.getByRole('dialog', { name: 'Abstimmungen' });
      expect(sheet).toHaveClass('ss--bottom');
      expect(sheet.querySelector('.mp__votes--sheet')).not.toBeNull();
    });

    /** The phone dock holds "Erledigt" and the view switch as icon buttons, the sheet not. */
    it('ticks the item and switches the view from the phone dock', async () => {
      const { on, fixture } = await setup({}, [MEDIA.phone]);
      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('.ts__done')).toBeNull();
      expect(host.querySelector('.ts__mode')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Erledigt' }));
      expect(on.setDone).toHaveBeenCalledWith(expect.objectContaining({ done: true }));
      const raw = screen.getByRole('button', { name: 'Markdown' });
      await userEvent.click(raw);
      expect(raw.closest('button') ?? raw).toHaveAttribute('aria-pressed', 'true');
      expect(host.querySelector('.ts__raw')).not.toBeNull();
    });

    /** The dock has no chips on a phone, so the minute-taker is an entry of the menu. */
    it('hands the minutes over from the phone menu, and offers no handover without the right', async () => {
      const { fixture } = await setup({}, [MEDIA.phone]);
      let menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Protokollführung übergeben' }));
      expect(await screen.findByRole('dialog', { name: 'Protokollführung übergeben' })).toHaveClass('ss--bottom');
      fixture.componentRef.setInput('meeting', meeting({ canManage: false, isProtokollant: false }));
      fixture.detectChanges();
      await userEvent.keyboard('{Escape}');
      menu = await openMenu();
      expect(within(menu).queryByRole('menuitem', { name: /Protokollführung/ })).toBeNull();
    });

    it('keeps the minute-taker out of the menu on a tablet, where the dock has the chip', async () => {
      await setup();
      const menu = await openMenu();
      expect(within(menu).queryByRole('menuitem', { name: /Protokollführung/ })).toBeNull();
    });

    it('opens the agenda from the start edge below the wide layout', async () => {
      await setup();
      await userEvent.click(within(await openMenu()).getByRole('menuitem', { name: 'Tagesordnung' }));
      expect(screen.getByRole('dialog', { name: 'Tagesordnung' })).toHaveClass('ss--start');
    });

    /** A closed meeting has nothing for the beamer. */
    it('moves the close into the menu on a phone; the finalize stays in the protocol bar', async () => {
      const { on, fixture } = await setup({}, [MEDIA.phone]);
      expect(screen.queryByRole('button', { name: 'Sitzung schließen' })).toBeNull();
      let menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Sitzung schließen' }));
      expect(on.closeSession).toHaveBeenCalled();
      fixture.componentRef.setInput('meeting', meeting({ status: 'closed' }));
      fixture.detectChanges();
      menu = await openMenu();
      expect(within(menu).queryByRole('menuitem', { name: 'Finalisieren & versenden' })).toBeNull();
      expect(within(menu).queryByRole('menuitem', { name: 'Beamer-Ansicht' })).toBeNull();
      await userEvent.keyboard('{Escape}');
      await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & versenden' }));
      expect(on.finalize).toHaveBeenCalled();
    });

    it('shows no beamer for a closed meeting on a wide screen', async () => {
      await setup({ meeting: meeting({ status: 'closed' }) }, [MEDIA.wide]);
      expect(screen.queryByRole('button', { name: 'Beamer-Ansicht' })).toBeNull();
    });
  });

  describe('planned', () => {
    const planned = (over: Partial<Meeting> = {}) => meeting({ status: 'planned', ...over });

    /** The opening is a menu item on every screen; the page opens on the item, not on a checklist. */
    it.each([[[]], [[MEDIA.wide]], [[MEDIA.phone]]])(
      'keeps the opening in the menu, disabled without a minute-taker (%j)',
      async (media) => {
        const { on } = await setup({ meeting: planned({ protokollantId: null, protokollantName: null }), protocol: null }, media);
        expect(screen.queryByRole('button', { name: 'Sitzung eröffnen' })).toBeNull();
        expect(screen.queryByRole('heading', { name: 'Sitzung vorbereiten' })).toBeNull();
        const menu = await openMenu();
        const start = within(menu).getByRole('menuitem', { name: 'Sitzung eröffnen' });
        expect(start).toHaveAttribute('aria-disabled', 'true');
        expect(within(menu).getAllByText('Erst die Protokollführung zuweisen.').length).toBeGreaterThan(0);
        await userEvent.click(start);
        expect(on.startSession).not.toHaveBeenCalled();
      },
    );

    it('opens from the menu once a minute-taker is set', async () => {
      const { on } = await setup({ meeting: planned(), protocol: null }, [MEDIA.wide]);
      const menu = await openMenu();
      const start = within(menu).getByRole('menuitem', { name: 'Sitzung eröffnen' });
      expect(start).not.toHaveAttribute('aria-disabled');
      await userEvent.click(start);
      expect(on.startSession).toHaveBeenCalledTimes(1);
    });

    /** The disabled item says when the open window opens. */
    it('keeps the opening disabled before the open window and says when it opens', async () => {
      const soon = (min: number): string => new Date(Date.now() + min * 60_000).toISOString();
      const { on } = await setup({ meeting: planned({ opensAt: soon(30), confirmUntil: soon(80) }), protocol: null });
      const menu = await openMenu();
      const start = within(menu).getByRole('menuitem', { name: 'Sitzung eröffnen' });
      expect(start).toHaveAttribute('aria-disabled', 'true');
      expect(start.getAttribute('title')).toMatch(/^Möglich ab /);
      await userEvent.click(start);
      expect(on.startSession).not.toHaveBeenCalled();
    });

    it('shows no opening to a reader without session control', async () => {
      await setup({ meeting: planned({ canControl: false, canManage: false }), protocol: null });
      expect(within(await openMenu()).queryByRole('menuitem', { name: 'Sitzung eröffnen' })).toBeNull();
    });

    /** The minute-taker and the attendance stay in the dock on a wider screen and in the menu on a phone. */
    it('reaches the minute-taker from the phone menu and the attendance from the phone dock', async () => {
      const { flushDelegations } = await setup({ meeting: planned(), protocol: null }, [MEDIA.phone]);
      const menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Protokollführung wählen' }));
      expect(screen.getByRole('dialog', { name: 'Protokollführung wählen' })).toBeInTheDocument();
      await userEvent.keyboard('{Escape}');
      expect(within(await openMenu()).queryByRole('menuitem', { name: 'Anwesenheit erfassen' })).toBeNull();
      await userEvent.keyboard('{Escape}');
      await userEvent.click(screen.getByRole('button', { name: 'Anwesenheit' }));
      expect(screen.getByRole('dialog', { name: 'Anwesenheit' })).toBeInTheDocument();
      flushDelegations();
    });

    /** The text of the selected item can be written before the start, without a protocol. */
    it('opens on the selected item and marks it in the agenda pane', async () => {
      const { on } = await setup({ meeting: planned({ canManageVotes: true }), protocol: null }, [MEDIA.wide]);
      expect(screen.getByRole('button', { name: 'Begrüßung' })).toHaveAttribute('aria-current');
      expect(screen.getByRole('toolbar', { name: 'Format' })).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Bericht des Finanzreferats' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
      expect(within(await openMenu()).queryByRole('menuitem', { name: 'Zurück zur Vorbereitung' })).toBeNull();
    });

    it('opens a picked item of the agenda sheet', async () => {
      const { on } = await setup({ meeting: planned({ canManageVotes: true }), protocol: null });
      await userEvent.click(screen.getByRole('button', { name: 'Sitzungsmenü' }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Tagesordnung' }));
      const sheet = await screen.findByRole('dialog', { name: 'Tagesordnung' });
      await userEvent.click(within(sheet).getByRole('button', { name: 'Bericht des Finanzreferats' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
      expect(screen.queryByRole('dialog', { name: 'Tagesordnung' })).toBeNull();
    });

    it('prepares a vote of a planned meeting', async () => {
      const { on } = await setup(
        { meeting: planned({ canManageVotes: true }), protocol: null, top: AGENDA[2], topIndex: 2 },
        [MEDIA.wide],
      );
      await userEvent.click(screen.getByRole('button', { name: 'Antrag Kulturfestival' }));
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung vorbereiten' }));
      expect(on.voteDialog).toHaveBeenCalledWith(AGENDA[2]);
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
      await userEvent.click(screen.getByRole('button', { name: 'Sitzungsmenü' }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Tagesordnung' }));
      const sheet = await screen.findByRole('dialog', { name: 'Tagesordnung' });
      await userEvent.click(within(sheet).getByRole('button', { name: 'Bericht des Finanzreferats' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
      expect(screen.queryByRole('dialog', { name: 'Tagesordnung' })).toBeNull();
    });

    /** A closed meeting changes no agenda. */
    it('puts the add into the header of the agenda sheet', async () => {
      const { on, fixture } = await setup();
      await userEvent.click(screen.getByRole('button', { name: 'Sitzungsmenü' }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Tagesordnung' }));
      const sheet = await screen.findByRole('dialog', { name: 'Tagesordnung' });
      const adds = within(sheet).getAllByRole('button', { name: 'TOP hinzufügen' });
      expect(adds).toHaveLength(1);
      expect(adds[0].closest('.ss__head')).toBeTruthy();
      await userEvent.click(adds[0]);
      expect(on.addTop).toHaveBeenCalledTimes(1);
      fixture.componentRef.setInput('meeting', meeting({ status: 'closed' }));
      fixture.detectChanges();
      expect(within(sheet).queryByRole('button', { name: 'TOP hinzufügen' })).toBeNull();
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
      const ask = await screen.findByRole('dialog', { name: 'TOP entfernen?' });
      await userEvent.click(within(ask).getByRole('button', { name: 'Entfernen' }));
      expect(on.removeFromAgenda).toHaveBeenCalledWith('t-2');
    });

    /** Text selected in the rename field fires a native `select` that bubbles. */
    it('passes on no native event that bubbles out of the agenda as a value', async () => {
      const { on, fixture } = await setup({ renameDraft: 'Neu' }, [MEDIA.wide]);
      await startAgendaRename(fixture);
      const input = screen.getByRole('textbox', { name: 'TOP umbenennen' });
      input.dispatchEvent(new Event('select', { bubbles: true }));
      expect(on.selectTop).not.toHaveBeenCalled();
    });

    it('passes the inline rename on', async () => {
      const { on, fixture } = await setup({ renameDraft: 'Neu' }, [MEDIA.wide]);
      await startAgendaRename(fixture);
      const input = screen.getByRole('textbox', { name: 'TOP umbenennen' });
      await userEvent.type(input, '{Enter}');
      expect(on.renameTop).toHaveBeenCalledWith(AGENDA[0]);
      await userEvent.type(input, '{Escape}');
      expect(on.cancelRename).toHaveBeenCalled();
    });

    /**
     * The step forward names the item that the room leaves, so the server ticks it. The step back
     * ticks nothing.
     */
    it('steps through the agenda from the dock', async () => {
      const { on } = await setup({ top: AGENDA[1], topIndex: 1 });
      await userEvent.click(screen.getByRole('button', { name: 'Nächster TOP' }));
      expect(on.nextTop).toHaveBeenCalledWith({ id: 't-3', from: 't-2' });
      expect(on.selectTop).not.toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: 'Vorheriger TOP' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-1');
      expect(on.nextTop).toHaveBeenCalledTimes(1);
    });

    it('steps nowhere without an open item', async () => {
      const { fixture, on } = await setup({ top: null, topIndex: -1 });
      fixture.componentInstance.step(1);
      expect(on.selectTop).not.toHaveBeenCalled();
      fixture.componentRef.setInput('top', AGENDA[0]);
      fixture.componentRef.setInput('topIndex', 0);
      fixture.detectChanges();
      fixture.componentInstance.step(-1);
      expect(on.selectTop).not.toHaveBeenCalled();
      fixture.componentRef.setInput('top', AGENDA[2]);
      fixture.componentRef.setInput('topIndex', 2);
      fixture.detectChanges();
      fixture.componentInstance.step(1);
      expect(on.nextTop).not.toHaveBeenCalled();
    });

    it('ticks the open item from the sheet and from the agenda', async () => {
      const { on } = await setup({}, [MEDIA.wide]);
      await userEvent.click(screen.getByRole('button', { name: 'Erledigt' }));
      expect(on.setDone).toHaveBeenCalledWith({ item: AGENDA[0], done: true });
      const rows = screen.getAllByRole('listitem');
      await userEvent.click(within(rows[1]).getByRole('button', { name: /Aktionen für/ }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Als erledigt markieren' }));
      expect(on.setDone).toHaveBeenCalledWith({ item: AGENDA[1], done: true });
    });

    it('offers no tick to a writer who does not keep the minutes of a live meeting', async () => {
      await setup({ canEdit: false }, [MEDIA.wide]);
      expect(screen.queryByRole('button', { name: 'Erledigt' })).toBeNull();
      const rows = screen.getAllByRole('listitem');
      await userEvent.click(within(rows[1]).getByRole('button', { name: /Aktionen für/ }));
      await screen.findByRole('menu');
      expect(screen.queryByRole('menuitem', { name: 'Als erledigt markieren' })).toBeNull();
    });

    it('passes the edits of the sheet on and makes the editor read-only for a reader', async () => {
      const { container, fixture } = await setup();
      await renderDeferred(fixture);
      expect(container.querySelector('.mde__host')).toBeTruthy();
      expect(container.querySelector('.mde__host--disabled')).toBeNull();
      fixture.componentRef.setInput('canEdit', false);
      fixture.detectChanges();
      expect(container.querySelector('.mde__host--disabled')).toBeTruthy();
      fixture.componentRef.setInput('canEdit', true);
      fixture.componentRef.setInput('protocol', protocol({ isLocked: true, status: 'rendering' }));
      fixture.detectChanges();
      expect(container.querySelector('.mde__host--disabled')).toBeTruthy();
    });

    /** The page asks when the handover takes effect, with the dialog of MeetingsComponent. */
    it('passes the dock actions on', async () => {
      const { on, flushDelegations } = await setup({ meeting: meeting({ currentAgendaItemId: 't-2' }) });
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Jetzt' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
      await userEvent.click(screen.getByTitle('Protokollführung übergeben'));
      await userEvent.click(screen.getByRole('button', { name: /Mika Mitglied/ }));
      expect(on.pickHandover).toHaveBeenCalledWith('pr-2');
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      const sheet = screen.getByRole('dialog', { name: 'Anwesenheit' });
      const mika = within(sheet).getByRole('radiogroup', { name: 'Anwesenheit von Mika Mitglied' });
      await userEvent.click(within(mika).getByRole('radio', { name: 'Unentschuldigt' }));
      expect(on.attendanceChange).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'absent' }),
      );
      await userEvent.click(within(mika).getByRole('radio', { name: 'Offen' }));
      expect(on.attendanceReset).toHaveBeenCalled();
      flushDelegations();
    });

    it('passes the end of an attendance conflict on', async () => {
      const { on, http, fixture } = await setup({ attendanceConflict: 'pr-2' });
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      http.match((r) => r.url.includes('/delegations/')).forEach((req) => req.flush(DELEGATION_CONTEXT));
      http.match((r) => r.url.endsWith('/delegations')).forEach((req) =>
        req.flush([
          {
            id: 'd-1', meetingId: 'm-1', meetingTitle: 'x', meetingDate: '2026-10-15', gremiumId: 'g-1',
            gremiumName: 'StuPa', delegatorId: 'pr-2', delegatorName: 'Mika Mitglied', delegateId: 'pr-3',
            delegateName: 'Alina Admin', delegateVoting: false, viaPool: false,
            createdAt: '2026-10-01T00:00:00Z', revocable: true, direction: null,
          },
        ]),
      );
      fixture.detectChanges();
      const sheet = screen.getByRole('dialog', { name: 'Anwesenheit' });
      await userEvent.click(within(within(sheet).getByRole('alert')).getByRole('button', { name: 'Vertretung widerrufen' }));
      http.expectOne('/api/delegations/d-1').flush(null);
      expect(on.attendanceConflictResolved).toHaveBeenCalledWith('pr-2');
      http.match((r) => r.url.endsWith('/delegations')).forEach((req) => req.flush([]));
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
      await userEvent.click(screen.getByRole('button', { name: 'Protokollführung fehlt' }));
      await userEvent.click(screen.getByRole('button', { name: /Alina Admin/ }));
      expect(on.setProtokollant).toHaveBeenCalledWith('pr-3');
    });
  });

  describe('votes', () => {
    /** Spec 000758: the page shows no vote while Abstimmungen is off. */
    it('shows no vote card while Abstimmungen is off', async () => {
      localStorage.setItem('ap.features.off', JSON.stringify(['voting']));
      await setup({ meeting: meeting({ votes: [vote({ id: 'v-1' })] }) }, [MEDIA.wide]);
      localStorage.removeItem('ap.features.off');
      expect(screen.queryByRole('button', { name: 'Abstimmung schließen' })).toBeNull();
      expect(screen.queryByText('Wird der Nachtragshaushalt beschlossen?')).toBeNull();
    });

    /** A second vote can be prepared while the open one runs. */
    it('shows the open vote first and runs it', async () => {
      const votes = [
        vote({ id: 'v-0', status: 'cancelled', question: 'Vertagen?' }),
        vote({ id: 'v-1' }),
        vote({ id: 'v-x', agendaItemId: 't-2', question: 'Anderer TOP?' }),
      ];
      const { on } = await setup({ meeting: meeting({ votes }) }, [MEDIA.wide]);
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
      expect(screen.getByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeEnabled();
    });

    it('opens a planned vote', async () => {
      const { on } = await setup({ meeting: meeting({ votes: [vote({ status: 'draft' })] }) }, [MEDIA.wide]);
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung öffnen' }));
      expect(on.voteOpen).toHaveBeenCalledWith('v-1');
    });

    it('changes a planned vote and repeats a closed one', async () => {
      const draft = vote({ id: 'v-1', status: 'draft' });
      const { on, fixture } = await setup({ meeting: meeting({ votes: [draft] }) }, [MEDIA.wide]);
      await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
      expect(on.voteSource).toHaveBeenCalledWith({ mode: 'edit', vote: draft });
      const closed = vote({ id: 'v-1', status: 'closed', result: 'passed' });
      fixture.componentRef.setInput('meeting', meeting({ votes: [closed] }));
      fixture.detectChanges();
      await userEvent.click(screen.getByRole('button', { name: 'Erneut abstimmen' }));
      expect(on.voteSource).toHaveBeenCalledWith({ mode: 'repeat', vote: closed });
      const again = vote({ id: 'v-2', status: 'open', repeatOfId: 'v-1', attempt: 2 });
      fixture.componentRef.setInput('meeting', meeting({ votes: [closed, again] }));
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Erneut abstimmen' })).toBeNull();
      expect(screen.getByText('Wiederholt')).toBeInTheDocument();
      expect(screen.getByText('2. Abstimmung')).toBeInTheDocument();
      fixture.componentRef.setInput(
        'meeting',
        meeting({ votes: [closed, { ...again, status: 'cancelled' }] }),
      );
      fixture.detectChanges();
      expect(screen.queryByText('Wiederholt')).toBeNull();
      expect(screen.getByRole('button', { name: 'Erneut abstimmen' })).toBeInTheDocument();
    });

    /**
     * A free-text item can still prepare a new question. Once the other vote ends, both come back.
     */
    it('opens no second vote while a vote on another item is open', async () => {
      const votes = [
        vote({ id: 'v-1', status: 'draft' }),
        vote({ id: 'v-x', agendaItemId: 't-2', question: 'Anderer TOP?' }),
      ];
      const { on, fixture } = await setup({ meeting: meeting({ votes }) }, [MEDIA.wide]);
      const open = screen.getByRole('button', { name: 'Abstimmung öffnen' });
      expect(open).toBeDisabled();
      expect(open).toHaveAttribute('title', 'Erst die offene Abstimmung schließen oder abbrechen.');
      await userEvent.click(open);
      expect(on.voteOpen).not.toHaveBeenCalled();
      expect(screen.getByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeEnabled();
      fixture.componentRef.setInput('meeting', meeting({ votes: [votes[1]] }));
      fixture.detectChanges();
      expect(screen.getByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeEnabled();
      fixture.componentRef.setInput(
        'meeting',
        meeting({ votes: [votes[0], { ...votes[1], status: 'closed', result: 'passed' }] }),
      );
      fixture.detectChanges();
      expect(screen.getByRole('button', { name: 'Abstimmung öffnen' })).toBeEnabled();
      expect(screen.getByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeEnabled();
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
      const { on, fixture } = await setup({}, [MEDIA.wide]);
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

    /** §F/finance/budget/000838: the item of a Haushaltsplan holds one vote, like an application item. */
    it('offers one vote on the item of a Haushaltsplan', async () => {
      const top = { ...AGENDA[0], planVersionId: 'pv-1' };
      const { fixture, http } = await setup({ top, meeting: meeting({ votes: [] }) }, [MEDIA.wide]);
      http.match((r) => r.url.endsWith('/budget-plan-versions/pv-1/readable')).forEach((r) => r.flush({ readable: true }));
      expect(screen.getByRole('button', { name: 'Abstimmung öffnen' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeNull();
      fixture.componentRef.setInput(
        'meeting',
        meeting({ votes: [vote({ agendaItemId: top.id, status: 'closed', result: 'passed' })] }),
      );
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Abstimmung öffnen' })).toBeNull();
    });

    /** §F/finance/budget/000876: a draft of a plan is on the agenda for a reading and takes no vote. */
    it('offers no vote on a draft of a Haushaltsplan', async () => {
      const top = { ...AGENDA[0], planVersionId: 'pv-1', planReading: true };
      const { http } = await setup({ top, meeting: meeting({ votes: [] }) }, [MEDIA.wide]);
      http.match((r) => r.url.endsWith('/budget-plan-versions/pv-1/readable')).forEach((r) => r.flush({ readable: true }));
      expect(screen.queryByRole('button', { name: 'Abstimmung öffnen' })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeNull();
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

    /**
     * A trailing hard break from a phone keyboard must not survive as an empty line. An empty text
     * takes the result alone.
     */
    it('carries the result into the text until it is there, then goes quiet', async () => {
      const closed = vote({ status: 'closed', result: 'passed', counts: { yes: 3, no: 1, abstain: 0 }, leading: 'yes', revealed: true });
      const { on, fixture } = await setup({ meeting: meeting({ votes: [closed] }), top: item({ body: 'Aussprache.\\\n' }) }, [MEDIA.wide]);
      await userEvent.click(screen.getByRole('button', { name: 'Ins Protokoll übernehmen' }));
      const payload = on.bodyChange.mock.calls[0][0] as { itemId: string; body: string };
      expect(payload.itemId).toBe('t-1');
      expect(payload.body).toBe(
        'Aussprache.\n\n> [!abstimmung] **Wird der Nachtragshaushalt beschlossen?**\n> yes: 3, no: 1, abstain: 0',
      );
      fixture.componentRef.setInput('top', item({ body: payload.body }));
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Ins Protokoll übernehmen' })).toBeNull();
      fixture.componentRef.setInput('top', item({ body: null }));
      fixture.detectChanges();
      await userEvent.click(screen.getByRole('button', { name: 'Ins Protokoll übernehmen' }));
      const bodies = on.bodyChange.mock.calls.map((c) => (c[0] as { body: string }).body);
      expect(bodies.some((b) => b.startsWith('> [!abstimmung]'))).toBe(true);
    });

    it('inserts nothing without an open item and offers no insert to a reader', async () => {
      const closed = vote({ status: 'closed', result: 'passed', counts: { yes: 3 } });
      const { on, fixture } = await setup({ meeting: meeting({ votes: [closed] }), canEdit: false });
      expect(screen.queryByRole('button', { name: 'Ins Protokoll übernehmen' })).toBeNull();
      fixture.componentRef.setInput('top', null);
      fixture.detectChanges();
      fixture.componentInstance.insertResult(closed);
      expect(on.bodyChange).not.toHaveBeenCalled();
    });
  });

  it('keeps the height of the dock as room below the page on a phone', async () => {
    const callbacks: ((entries: ResizeObserverEntry[]) => void)[] = [];
    const original = globalThis.ResizeObserver;
    Object.defineProperty(globalThis, 'ResizeObserver', {
      writable: true,
      value: class {
        constructor(cb: (entries: ResizeObserverEntry[]) => void) {
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
      callbacks.forEach((cb) => cb([]));
      fixture.detectChanges();
      expect((fixture.nativeElement as HTMLElement).style.getPropertyValue('--fx-dock-h')).toBe('96px');
    } finally {
      Object.defineProperty(globalThis, 'ResizeObserver', { writable: true, value: original });
    }
  });

  describe('public meeting', () => {
    it('offers the QR code in the phone menu and shows it from the attendance sheet', async () => {
      const { fixture } = await setup({ meeting: meeting({ publicJoin: true }) }, [MEDIA.phone]);
      const menu = await openMenu();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'QR-Code zum Beitreten' }));
      const page = fixture.componentInstance;
      expect(page.qrOpen()).toBe(true);
      page.qrOpen.set(false);
      page.panel.set('attendance');
      page.showQr();
      expect(page.panel()).toBe('none');
      expect(page.qrOpen()).toBe(true);
    });
  });
});
