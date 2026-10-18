import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, AssignableApplication, Meeting } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { BOARDS, board, tile } from '../../../../testing/todo-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { AgendaItemDialogComponent } from './agenda-item-dialog.component';

const MEETING = { id: 'm-1', title: '34. Sitzung', status: 'live', votes: [], gremiumId: 'g-1' } as unknown as Meeting;
const APPS: AssignableApplication[] = [
  { applicationId: 'a-1', title: 'Sommerkino auf der Campuswiese', stateLabel: { de: 'Auf Tagesordnung', en: 'On the agenda' } },
  { applicationId: 'a-2', title: 'Erste-Hilfe-Kurs', stateLabel: null },
  { applicationId: 'a-3', title: null },
];

async function setup(
  open = true,
  kind: 'application' | 'freetext' = 'application',
  extra: { canTodo?: boolean; meeting?: Meeting; agenda?: AgendaItem[] } = {},
) {
  const closed = jest.fn();
  const added = jest.fn();
  const canInGremium = jest.fn(() => extra.canTodo ?? false);
  const view = await render(AgendaItemDialogComponent, {
    inputs: { open, meeting: extra.meeting ?? MEETING, ...(extra.agenda ? { agenda: extra.agenda } : {}) },
    on: { closed, added },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: AuthService, useValue: { canInGremium } },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  // The dialog opens on a free-text item. Most specs work on the application list.
  if (kind === 'application') {
    view.fixture.componentInstance.setKind('application');
    view.fixture.detectChanges();
  }
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp: view.fixture.componentInstance, closed, added, toasts, canInGremium };
}

function flushApps(http: HttpTestingController, fixture: { detectChanges(): void }, rows = APPS) {
  http.expectOne('/api/meetings/m-1/agenda/assignable').flush(rows);
  fixture.detectChanges();
}

function submitButton(): HTMLElement {
  return screen
    .getAllByRole('button', { name: 'TOP hinzufügen' })
    .find((b) => b.closest('.dialog__footer')) as HTMLElement;
}

describe('AgendaItemDialogComponent', () => {
  it('lists the assignable applications of the Gremium with their state', async () => {
    const { http, fixture } = await setup();
    const dialog = screen.getByRole('dialog', { name: 'TOP hinzufügen' });
    expect(dialog).not.toHaveTextContent('34. Sitzung');
    expect(screen.getByRole('status')).toHaveTextContent('Wird geladen');
    flushApps(http, fixture);
    const group = screen.getByRole('radiogroup', { name: /Zuweisbare Anträge/ });
    expect(within(group).getAllByRole('radio')).toHaveLength(3);
    expect(within(group).getByText('Auf Tagesordnung')).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it('assigns the picked application, non-public at once', async () => {
    const { http, fixture, added } = await setup();
    flushApps(http, fixture);
    await userEvent.click(screen.getByRole('radio', { name: /Sommerkino/ }));
    await userEvent.click(screen.getByRole('switch', { name: 'Nicht öffentlich (NÖ)' }));
    await userEvent.click(submitButton());
    const req = http.expectOne('/api/meetings/m-1/agenda');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ applicationId: 'a-1', nonPublic: true });
    req.flush([{ id: 't-9', applicationId: 'a-1', title: 'Sommerkino', position: 8, nonPublic: true }]);
    expect(added).toHaveBeenCalledWith([expect.objectContaining({ id: 't-9' })]);
  });

  it('filters the list by the search text and says when nothing matches', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture);
    await userEvent.type(screen.getByRole('searchbox', { name: 'Antrag suchen' }), 'kurs');
    const group = screen.getByRole('radiogroup', { name: /Zuweisbare Anträge/ });
    expect(within(group).getAllByRole('radio')).toHaveLength(1);
    cmp.query.set('zzz');
    fixture.detectChanges();
    expect(screen.getByText('Kein Antrag passt zu „zzz“')).toBeInTheDocument();
  });

  it('does not send a pick that the search hides', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture);
    await userEvent.click(screen.getByRole('radio', { name: /Sommerkino/ }));
    expect(submitButton()).toBeEnabled();
    await userEvent.type(screen.getByRole('searchbox', { name: 'Antrag suchen' }), 'kurs');
    expect(screen.getByRole('radio', { name: /Erste-Hilfe/ })).not.toBeChecked();
    expect(submitButton()).toBeDisabled();
    cmp.submit();
    http.expectNone('/api/meetings/m-1/agenda');
    await userEvent.clear(screen.getByRole('searchbox', { name: 'Antrag suchen' }));
    expect(screen.getByRole('radio', { name: /Sommerkino/ })).toBeChecked();
    expect(submitButton()).toBeEnabled();
  });

  it('says when no application can be assigned, also after a failed load', async () => {
    const { http, fixture } = await setup();
    http.expectOne('/api/meetings/m-1/agenda/assignable').flush(null, { status: 403, statusText: 'x' });
    fixture.detectChanges();
    expect(screen.getByText('Keine zuweisbaren Anträge')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { http, fixture } = await setup();
    flushApps(http, fixture, APPS.slice(0, 2));
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('opens on a free-text item', async () => {
    const { http, fixture, cmp } = await setup(true, 'freetext');
    flushApps(http, fixture);
    expect(cmp.kind()).toBe('freetext');
    expect(screen.getByRole('radio', { name: 'Freitext' })).toBeChecked();
    expect(screen.getByLabelText(/Titel/)).toBeInTheDocument();
  });

  it('adds a free-text item', async () => {
    const { http, fixture, cmp, added } = await setup();
    flushApps(http, fixture);
    await userEvent.click(screen.getByRole('radio', { name: 'Freitext' }));
    expect(submitButton()).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Titel/), '  Verschiedenes ');
    await userEvent.click(submitButton());
    cmp.submit(); // one request at a time
    const req = http.expectOne('/api/meetings/m-1/agenda');
    expect(req.request.body).toEqual({ title: 'Verschiedenes', nonPublic: false });
    req.flush([]);
    expect(added).toHaveBeenCalledWith([]);
  });

  it('accepts only the known kinds', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture);
    cmp.setKind('freetext');
    cmp.setKind('other');
    cmp.setKind(null);
    cmp.setKind('todo'); // only with todo.write in the gremium
    expect(cmp.kind()).toBe('freetext');
    cmp.setKind('application');
    expect(cmp.kind()).toBe('application');
  });

  it('shows the server reason when the add fails', async () => {
    const { http, fixture, cmp, added, toasts } = await setup();
    flushApps(http, fixture);
    cmp.pick.set('a-2');
    cmp.submit();
    http.expectOne('/api/meetings/m-1/agenda').flush({ detail: 'meeting_closed' }, { status: 409, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: meeting_closed');
    cmp.submit();
    http.expectOne('/api/meetings/m-1/agenda').flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
    expect(added).not.toHaveBeenCalled();
  });

  it('starts empty on every opening and closes on cancel', async () => {
    const { http, fixture, cmp, closed } = await setup(false);
    http.expectNone('/api/meetings/m-1/agenda/assignable');
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    flushApps(http, fixture);
    cmp.pick.set('a-1');
    cmp.nonPublic.set(true);
    fixture.componentRef.setInput('open', false);
    fixture.detectChanges();
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    flushApps(http, fixture);
    expect(cmp.pick()).toBeNull();
    expect(cmp.nonPublic()).toBe(false);
    expect(screen.getByRole('button', { name: 'Schließen' })).toBeInTheDocument();
    const footerCancel = screen.getByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(closed).toHaveBeenCalled();
  });
  it('fills the body with the kind control, its segments in equal parts', async () => {
    const { http, fixture } = await setup();
    flushApps(http, fixture);
    const seg = document.querySelector('app-segmented.aid__kind');
    expect(seg).toHaveClass('seg-host--fill');
  });

  it('keeps one area for every kind, so the dialog keeps its height', async () => {
    const { http, fixture, cmp } = await setup();
    const area = () => document.querySelector('.aid__area') as HTMLElement;
    expect(area()).toHaveAttribute('data-kind', 'application');
    // Loading: the rows of the skeleton sit in the area.
    expect(area().querySelector('app-skeleton')).not.toBeNull();
    flushApps(http, fixture);
    expect(area().querySelector('.aid__list')).not.toBeNull();
    cmp.query.set('zzz');
    fixture.detectChanges();
    expect(area().querySelector('app-empty-state')).not.toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: 'Freitext' }));
    expect(area()).toHaveAttribute('data-kind', 'freetext');
    expect(area().querySelector('#aid-title')).not.toBeNull();
    expect(document.querySelectorAll('.aid__area')).toHaveLength(1);
  });

  it('shows no caption above the list', async () => {
    const { http, fixture } = await setup();
    flushApps(http, fixture);
    expect(document.querySelector('.aid__cap')).toBeNull();
    expect(screen.queryByText(/Zuweisbare Anträge/)).toBeNull();
    expect(screen.getByRole('radiogroup', { name: 'Zuweisbare Anträge' })).toBeInTheDocument();
  });

  it('shows ghost rows behind the message of an empty list, hidden from the screen reader', async () => {
    const { http, fixture } = await setup();
    flushApps(http, fixture, []);
    const ghosts = document.querySelector('.es__ghosts') as HTMLElement;
    expect(ghosts).toHaveAttribute('aria-hidden', 'true');
    expect(ghosts.querySelectorAll('.es__ghost')).toHaveLength(5);
    expect(screen.queryByRole('radiogroup', { name: /Zuweisbare Anträge/ })).toBeNull();
    expect(screen.getByRole('button', { name: 'Als Freitext anlegen' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Filter zurücksetzen' })).toBeNull();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('switches an empty list to a free-text item, with the search text as its title', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture, []);
    await userEvent.type(screen.getByRole('searchbox', { name: 'Antrag suchen' }), ' Mensa ');
    // Nothing to find at all: the way on is a free-text item, not a reset.
    expect(screen.getByText('Keine zuweisbaren Anträge')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Als Freitext anlegen' }));
    expect(cmp.kind()).toBe('freetext');
    expect(cmp.freetext()).toBe('Mensa');
    // ngModel writes the field after a microtask.
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByLabelText(/Titel/)).toHaveValue('Mensa');
    expect(screen.getByLabelText(/Titel/)).toHaveFocus();
    expect(submitButton()).toBeEnabled();
  });

  it('switches to a free text without a search text and keeps the title empty', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture, []);
    await userEvent.click(screen.getByRole('button', { name: 'Als Freitext anlegen' }));
    expect(cmp.kind()).toBe('freetext');
    expect(cmp.freetext()).toBe('');
  });

  it('resets the search when nothing matches it', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture);
    await userEvent.type(screen.getByRole('searchbox', { name: 'Antrag suchen' }), 'Kühlschrank');
    expect(screen.getByText('Kein Antrag passt zu „Kühlschrank“')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Als Freitext anlegen' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
    expect(cmp.query()).toBe('');
    expect(cmp.kind()).toBe('application');
    expect(within(screen.getByRole('radiogroup', { name: /Zuweisbare Anträge/ })).getAllByRole('radio')).toHaveLength(3);
    expect(screen.getByRole('searchbox', { name: 'Antrag suchen' })).toHaveFocus();
  });

  it('toggles "Nicht öffentlich" from anywhere on its row, once per click', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture);
    const row = document.querySelector('app-switch.aid__np') as HTMLElement;
    const sw = screen.getByRole('switch', { name: 'Nicht öffentlich (NÖ)' });
    await userEvent.click(row);
    expect(cmp.nonPublic()).toBe(true);
    expect(sw).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByText('Nicht öffentlich (NÖ)'));
    expect(cmp.nonPublic()).toBe(false);
    await userEvent.click(sw);
    expect(cmp.nonPublic()).toBe(true);
  });

  it('shows the state of an application as the second line of its row', async () => {
    const { http, fixture } = await setup();
    flushApps(http, fixture);
    const row = screen.getByRole('radio', { name: /Sommerkino/ }).closest('label') as HTMLElement;
    expect(row.querySelector('.aid__sub')).toHaveTextContent('Auf Tagesordnung');
    const bare = screen.getByRole('radio', { name: /Erste-Hilfe/ }).closest('label') as HTMLElement;
    expect(bare.querySelector('.aid__sub')).toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: /Erste-Hilfe/ }));
    expect(bare).toHaveClass('aid__row--on');
  });
  describe('kind To-Do', () => {
    const AGENDA_TODO = [{ id: 't-1', applicationId: null, todoId: 'k-5', title: 'Schon da', position: 0 }] as AgendaItem[];
    const BOARD = board({
      cards: [
        tile({ id: 'k-1', columnId: 'c-2', title: 'Haushaltsplan 2027: Entwurf Kapitel 3', dueDate: '2026-11-03' }),
        tile({ id: 'k-2', columnId: 'c-1', title: 'Kassenprüfer anfragen', dueDate: '2027-01-15' }),
        tile({ id: 'k-3', columnId: 'c-3', title: 'Wahlordnung lesen' }),
        tile({ id: 'k-4', columnId: 'c-4', title: 'Erledigt schon' }),
        tile({ id: 'k-5', columnId: 'c-1', title: 'Schon auf der Tagesordnung' }),
      ],
    });

    async function todoSetup(extra: { meeting?: Meeting } = {}) {
      const view = await setup(true, 'freetext', { canTodo: true, agenda: AGENDA_TODO, ...extra });
      flushApps(view.http, view.fixture);
      await userEvent.click(screen.getByRole('radio', { name: 'To-Do' }));
      return view;
    }

    function flushBoard(http: HttpTestingController, fixture: { detectChanges(): void }) {
      http.expectOne((r) => r.url === '/api/todos/boards' && r.params.get('gremiumId') === 'g-1').flush(BOARDS);
      http.expectOne('/api/todos/boards/b-1').flush(BOARD);
      fixture.detectChanges();
    }

    it('is offered only with todo.write in the gremium of the meeting', async () => {
      const { http, fixture, cmp, canInGremium } = await setup(true, 'freetext');
      flushApps(http, fixture);
      expect(screen.queryByRole('radio', { name: 'To-Do' })).toBeNull();
      expect(canInGremium).toHaveBeenCalledWith('g-1', 'todo.write');
      expect(screen.getAllByRole('radio')).toHaveLength(2);
      // Nothing loaded yet: no cards.
      expect(cmp.shownTodos()).toEqual([]);
    });

    it('is not offered for a meeting without a gremium, and the kind stays', async () => {
      const { http, fixture, cmp, canInGremium } = await setup(true, 'freetext', {
        canTodo: true,
        meeting: { ...MEETING, gremiumId: null } as unknown as Meeting,
      });
      flushApps(http, fixture);
      expect(screen.queryByRole('radio', { name: 'To-Do' })).toBeNull();
      expect(canInGremium).not.toHaveBeenCalled();
      cmp.setKind('todo');
      expect(cmp.kind()).toBe('freetext');
      http.expectNone('/api/todos/boards');
    });

    it('lists the open cards of the gremium board by column, without done cards and cards on the agenda', async () => {
      const { http, fixture } = await todoSetup();
      expect(screen.getByRole('status')).toHaveTextContent('Wird geladen');
      flushBoard(http, fixture);
      expect(within(screen.getByRole('radiogroup', { name: 'Offene To-Dos' })).getAllByRole('radio')).toHaveLength(3);
      const group = screen.getByRole('radiogroup', { name: /Offene To-Dos/ });
      const radios = within(group).getAllByRole('radio');
      expect(radios.map((r) => r.closest('label')?.querySelector('.aid__title')?.textContent)).toEqual([
        'Kassenprüfer anfragen',
        'Haushaltsplan 2027: Entwurf Kapitel 3',
        'Wahlordnung lesen',
      ]);
      expect(within(group).getByText('Offen · fällig 15.01.2027')).toBeInTheDocument();
      expect(within(group).getByText('Wartet')).toBeInTheDocument();
      expect(within(group).getByText(/^In Arbeit · fällig 03\.11\./)).toBeInTheDocument();
      expect(screen.queryByText('Erledigt schon')).toBeNull();
      expect(screen.queryByText('Schon auf der Tagesordnung')).toBeNull();
      expect(screen.getByRole('searchbox', { name: 'To-Do suchen' })).toBeInTheDocument();
    });

    it('puts the picked card on the agenda, non-public at once', async () => {
      const { http, fixture, added, cmp } = await todoSetup();
      flushBoard(http, fixture);
      expect(submitButton()).toBeDisabled();
      await userEvent.click(screen.getByRole('radio', { name: /Wahlordnung/ }));
      expect(screen.getByRole('radio', { name: /Wahlordnung/ }).closest('label')).toHaveClass('aid__row--on');
      await userEvent.click(screen.getByRole('switch', { name: 'Nicht öffentlich (NÖ)' }));
      await userEvent.click(submitButton());
      const req = http.expectOne('/api/meetings/m-1/agenda');
      expect(req.request.body).toEqual({ todoId: 'k-3', nonPublic: true });
      req.flush([{ id: 't-9', applicationId: null, todoId: 'k-3', title: 'Wahlordnung lesen', position: 1 }]);
      expect(added).toHaveBeenCalledWith([expect.objectContaining({ todoId: 'k-3' })]);
      // Back on "To-Do" the list stays loaded.
      cmp.setKind('freetext');
      cmp.setKind('todo');
      http.expectNone('/api/todos/boards');
    });

    it('filters by the search text, says when nothing matches, and does not send a hidden pick', async () => {
      const { http, fixture, cmp } = await todoSetup();
      flushBoard(http, fixture);
      await userEvent.click(screen.getByRole('radio', { name: /Kassenprüfer/ }));
      expect(submitButton()).toBeEnabled();
      await userEvent.type(screen.getByRole('searchbox', { name: 'To-Do suchen' }), 'haushalt');
      expect(within(screen.getByRole('radiogroup', { name: 'Offene To-Dos' })).getAllByRole('radio')).toHaveLength(1);
      expect(submitButton()).toBeDisabled();
      cmp.submit();
      http.expectNone('/api/meetings/m-1/agenda');
      cmp.todoQuery.set('zzz');
      fixture.detectChanges();
      expect(screen.getByText('Kein To-Do passt zu „zzz“')).toBeInTheDocument();
    });

    it('says there are no open to-dos without a gremium board', async () => {
      const { http, fixture, cmp } = await todoSetup();
      http.expectOne((r) => r.url === '/api/todos/boards').flush([BOARDS[0], BOARDS[2]]);
      fixture.detectChanges();
      expect(screen.getByText('Keine offenen To-Dos')).toBeInTheDocument();
      expect(cmp.todosLoading()).toBe(false);
    });

    it('says there are no open to-dos after a failed read', async () => {
      const { http, fixture } = await todoSetup();
      http.expectOne((r) => r.url === '/api/todos/boards').flush(BOARDS);
      http.expectOne('/api/todos/boards/b-1').flush(null, { status: 404, statusText: 'x' });
      fixture.detectChanges();
      expect(screen.getByText('Keine offenen To-Dos')).toBeInTheDocument();
    });

    it('offers a free-text item when the board has no open card', async () => {
      const { http, fixture, cmp } = await todoSetup();
      http.expectOne((r) => r.url === '/api/todos/boards').flush([BOARDS[0], BOARDS[2]]);
      fixture.detectChanges();
      expect(screen.queryByRole('radiogroup', { name: 'Offene To-Dos' })).toBeNull();
      expect(document.querySelector('.es__ghosts')).toHaveAttribute('aria-hidden', 'true');
      await userEvent.type(screen.getByRole('searchbox', { name: 'To-Do suchen' }), 'Grillfest');
      expect(screen.getByText('Keine offenen To-Dos')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Als Freitext anlegen' }));
      expect(cmp.kind()).toBe('freetext');
      expect(cmp.freetext()).toBe('Grillfest');
    });

    it('resets the to-do search when nothing matches it', async () => {
      const { http, fixture, cmp } = await todoSetup();
      flushBoard(http, fixture);
      await userEvent.type(screen.getByRole('searchbox', { name: 'To-Do suchen' }), 'Mensa');
      expect(screen.getByText('Kein To-Do passt zu „Mensa“')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
      expect(cmp.todoQuery()).toBe('');
      expect(cmp.kind()).toBe('todo');
      expect(within(screen.getByRole('radiogroup', { name: 'Offene To-Dos' })).getAllByRole('radio')).toHaveLength(3);
    });

    it('starts again on every opening', async () => {
      const { http, fixture, cmp } = await todoSetup();
      flushBoard(http, fixture);
      cmp.todoPick.set('k-1');
      cmp.todoQuery.set('x');
      fixture.componentRef.setInput('open', false);
      fixture.detectChanges();
      fixture.componentRef.setInput('open', true);
      fixture.detectChanges();
      flushApps(http, fixture);
      expect(cmp.todos()).toBeNull();
      expect(cmp.todoPick()).toBeNull();
      expect(cmp.todoQuery()).toBe('');
      expect(cmp.kind()).toBe('freetext');
    });

    it('has no axe violations', async () => {
      const { http, fixture } = await todoSetup();
      flushBoard(http, fixture);
      await userEvent.click(screen.getByRole('radio', { name: /Wahlordnung/ }));
      expect(await runAxe(document.body)).toHaveNoViolations();
    });
  });
});
