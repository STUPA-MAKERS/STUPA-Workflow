import { CdkDrag, CdkDropList } from '@angular/cdk/drag-drop';
import type { ComponentFixture } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of } from 'rxjs';
import type { AgendaItem, Meeting } from '@core/api/models';
import { TodosApiService } from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';
import { BOARDS, MEMBERS, board } from '../../../../testing/todo-fixtures';
import { AGENDA, item, meeting, vote } from '../../../../testing/meeting-fixtures';
import { AgendaPaneComponent } from './agenda-pane.component';

const OUTPUTS = [
  'pick', 'add', 'startRename', 'cancelRename', 'renameTop', 'setNonPublic', 'move',
  'remove',
] as const;

/** Whether each row may be lifted, in agenda order. */
function draggable(fixture: ComponentFixture<AgendaPaneComponent>): boolean[] {
  return fixture.debugElement
    .queryAll(By.directive(CdkDrag))
    .map((d) => !d.injector.get(CdkDrag).disabled);
}

/** Drop the row at `from` at `to`, as the drop list reports it. */
function drop(fixture: ComponentFixture<AgendaPaneComponent>, from: number, to: number): void {
  fixture.debugElement
    .query(By.directive(CdkDropList))
    .triggerEventHandler('cdkDropListDropped', { previousIndex: from, currentIndex: to });
}

interface Inputs {
  meeting: Meeting;
  agenda: AgendaItem[];
  selectedId: string | null;
  locked: boolean;
  savingAgenda: boolean;
  renamingTopId: string | null;
  renameDraft: string;
}

async function setup(over: Partial<Inputs> = {}, canTodo?: boolean) {
  const on = Object.fromEntries(OUTPUTS.map((name) => [name, jest.fn()])) as Record<
    (typeof OUTPUTS)[number],
    jest.Mock
  >;
  const view = await render(AgendaPaneComponent, {
    inputs: {
      meeting: meeting(),
      agenda: AGENDA,
      selectedId: 't-1',
      locked: false,
      savingAgenda: false,
      renamingTopId: null,
      renameDraft: '',
      ...over,
    },
    on,
    providers:
      canTodo === undefined
        ? []
        : [
            { provide: AuthService, useValue: { canInGremium: jest.fn(() => canTodo) } },
            {
              provide: TodosApiService,
              useValue: {
                boards: jest.fn(() => of(BOARDS)),
                board: jest.fn(() => of(board())),
                members: jest.fn(() => of(MEMBERS)),
                linkTargets: jest.fn(() => of([])),
              },
            },
          ],
  });
  return { ...view, on };
}

/** Open the row menu of the agenda item at `index` and give the menu. */
async function openMenu(index: number): Promise<HTMLElement> {
  const rows = screen.getAllByRole('listitem');
  await userEvent.click(within(rows[index]).getByRole('button', { name: /Aktionen für/ }));
  return screen.findByRole('menu');
}

describe('AgendaPaneComponent', () => {
  it('counts the items and shows the kind of an application, an open vote and the NÖ tag', async () => {
    await setup({ meeting: meeting({ votes: [vote({ agendaItemId: 't-3' })] }) });
    expect(screen.getByRole('heading', { name: 'Tagesordnung · 3 TOPs' })).toBeInTheDocument();
    // The number badge names the TOP; a free-text item has no sub line at all.
    const rows = screen.getAllByRole('listitem');
    expect(rows[0].querySelector('.li__subText')).toBeNull();
    expect(screen.queryByText(/Freitext|TOP 1/)).toBeNull();
    expect(screen.getByText('Antrag · Abstimmung offen')).toBeInTheDocument();
    const noe = screen.getByText('NÖ');
    expect(noe.closest('li')).toHaveTextContent('Antrag Kulturfestival');
  });

  it('says one item in the singular and shows the empty hint', async () => {
    await setup({ agenda: [AGENDA[0]] });
    expect(screen.getByRole('heading', { name: 'Tagesordnung · 1 TOP' })).toBeInTheDocument();
  });

  it('shows the empty agenda hint', async () => {
    await setup({ agenda: [] });
    expect(screen.getByText('Noch keine Anträge auf der Tagesordnung.')).toBeInTheDocument();
  });

  it('marks the item that runs now and the items before it as handled (O19)', async () => {
    const { container } = await setup({ meeting: meeting({ currentAgendaItemId: 't-2' }) });
    const rows = screen.getAllByRole('listitem');
    expect(rows[0]).toHaveClass('ap__row--done');
    expect(within(rows[0]).getByText('behandelt')).toBeInTheDocument();
    expect(within(rows[1]).getByText('jetzt')).toBeInTheDocument();
    expect(rows[2]).not.toHaveClass('ap__row--done');
    expect(container.querySelector('.ap__num--now')?.closest('li')).toBe(rows[1]);
  });

  it('marks no item as handled or now in a planned meeting, also with a stale id', async () => {
    const { container } = await setup({
      meeting: meeting({ status: 'planned', currentAgendaItemId: 't-3' }),
    });
    const rows = screen.getAllByRole('listitem');
    rows.forEach((row) => expect(row).not.toHaveClass('ap__row--done'));
    expect(screen.queryByText('behandelt')).toBeNull();
    expect(screen.queryByText('jetzt')).toBeNull();
    expect(container.querySelector('.ap__num--now')).toBeNull();
  });

  it('marks nothing as handled while no item runs', async () => {
    await setup({ meeting: meeting({ currentAgendaItemId: null }) });
    expect(screen.queryByText('behandelt')).toBeNull();
  });

  it('opens an item, marks the selected one and adds through the dialog', async () => {
    const { on } = await setup();
    expect(screen.getByRole('button', { name: 'Begrüßung' })).toHaveAttribute('aria-current', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Bericht des Finanzreferats' }));
    expect(on.pick).toHaveBeenCalledWith('t-2');
    await userEvent.click(screen.getByRole('button', { name: 'TOP hinzufügen' }));
    expect(on.add).toHaveBeenCalled();
  });

  it('names an untitled item', async () => {
    await setup({ agenda: [item({ title: null })] });
    expect(screen.getByRole('button', { name: 'Unbenannter TOP' })).toBeInTheDocument();
  });

  it('puts the focus on its heading', async () => {
    const { fixture } = await setup();
    fixture.componentInstance.focus();
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: /Tagesordnung/ }));
  });

  describe('row menu', () => {
    it('renames a freetext item, moves it and switches NÖ', async () => {
      const { on } = await setup();
      let menu = await openMenu(1);
      expect(within(menu).getByRole('menuitem', { name: 'Nach oben' })).toBeInTheDocument();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'TOP umbenennen' }));
      expect(on.startRename).toHaveBeenCalledWith(AGENDA[1]);

      menu = await openMenu(1);
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Nach oben' }));
      expect(on.move).toHaveBeenCalledWith({ from: 1, to: 0 });
      menu = await openMenu(1);
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'Nach unten' }));
      expect(on.move).toHaveBeenCalledWith({ from: 1, to: 2 });

      menu = await openMenu(1);
      const np = within(menu).getByRole('menuitemcheckbox', { name: 'Nicht öffentlich (NÖ)' });
      expect(np).toHaveAttribute('aria-checked', 'false');
      await userEvent.click(np);
      expect(on.setNonPublic).toHaveBeenCalledWith({ item: AGENDA[1], nonPublic: true });

      menu = await openMenu(2);
      await userEvent.click(within(menu).getByRole('menuitemcheckbox', { name: 'Nicht öffentlich (NÖ)' }));
      expect(on.setNonPublic).toHaveBeenCalledWith({ item: AGENDA[2], nonPublic: false });
    });

    it('offers no move beyond the edges and no rename for an application item', async () => {
      await setup();
      let menu = await openMenu(0);
      expect(within(menu).queryByRole('menuitem', { name: 'Nach oben' })).toBeNull();
      await userEvent.keyboard('{Escape}');
      menu = await openMenu(2);
      expect(within(menu).queryByRole('menuitem', { name: 'Nach unten' })).toBeNull();
      expect(within(menu).queryByRole('menuitem', { name: 'TOP umbenennen' })).toBeNull();
    });

    it('removes an item without votes', async () => {
      const { on } = await setup();
      const menu = await openMenu(1);
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'TOP entfernen' }));
      expect(on.remove).toHaveBeenCalledWith('t-2');
    });

    it('disables the remove of an item with an open or closed vote and says why (O25)', async () => {
      const votes = [
        vote({ agendaItemId: 't-1', status: 'closed', result: 'passed' }),
        vote({ id: 'v-2', agendaItemId: 't-2', status: 'cancelled' }),
        vote({ id: 'v-3', agendaItemId: 't-3', status: 'open' }),
      ];
      const { on } = await setup({ meeting: meeting({ votes }) });
      let menu = await openMenu(0);
      const blocked = within(menu).getByRole('menuitem', { name: 'TOP entfernen' });
      expect(blocked).toHaveAttribute('aria-disabled', 'true');
      expect(blocked.getAttribute('title')).toMatch(/bleibt auf der Tagesordnung/);
      await userEvent.click(blocked);
      expect(on.remove).not.toHaveBeenCalled();
      await userEvent.keyboard('{Escape}');
      // A cancelled vote goes with its item.
      menu = await openMenu(1);
      expect(within(menu).getByRole('menuitem', { name: 'TOP entfernen' })).not.toHaveAttribute('aria-disabled');
      await userEvent.keyboard('{Escape}');
      menu = await openMenu(2);
      expect(within(menu).getByRole('menuitem', { name: 'TOP entfernen' })).toHaveAttribute('aria-disabled', 'true');
    });

    it('disables the remove of an item with votes without the vote right', async () => {
      const votes = [vote({ id: 'v-2', agendaItemId: 't-2', status: 'cancelled' })];
      await setup({ meeting: meeting({ votes, canManageVotes: false }) });
      const menu = await openMenu(1);
      const remove = within(menu).getByRole('menuitem', { name: 'TOP entfernen' });
      expect(remove).toHaveAttribute('aria-disabled', 'true');
      expect(remove.getAttribute('title')).toMatch(/Nur wer die Abstimmungen/);
    });

    it('ignores a choice while the agenda saves', async () => {
      const { on, fixture } = await setup();
      const menu = await openMenu(1);
      fixture.componentRef.setInput('savingAgenda', true);
      fixture.detectChanges();
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'TOP entfernen' }));
      expect(on.remove).not.toHaveBeenCalled();
    });

    it('keeps only the NÖ switch once the meeting is closed (O22)', async () => {
      const { container, fixture } = await setup({ meeting: meeting({ status: 'closed' }) });
      expect(screen.queryByRole('button', { name: 'TOP hinzufügen' })).toBeNull();
      expect(container.querySelector('.ap__grip')).toBeNull();
      expect(draggable(fixture)).toEqual([false, false, false]);
      expect(fixture.debugElement.query(By.directive(CdkDropList)).injector.get(CdkDropList).disabled).toBe(true);
      const menu = await openMenu(0);
      expect(within(menu).getAllByRole('menuitemcheckbox')).toHaveLength(1);
      expect(within(menu).queryByRole('menuitem')).toBeNull();
    });

    it('has no menu once the protocol is locked or without write access', async () => {
      await setup({ locked: true });
      expect(screen.queryByRole('button', { name: /Aktionen für/ })).toBeNull();
    });

    it('has no menu for a reader', async () => {
      await setup({ meeting: meeting({ canWrite: false }) });
      expect(screen.queryByRole('button', { name: /Aktionen für/ })).toBeNull();
      expect(screen.queryByRole('button', { name: 'TOP hinzufügen' })).toBeNull();
    });
  });

  it('renames inline: enter saves, escape cancels, blur saves', async () => {
    const { on, fixture } = await setup({ renamingTopId: 't-1', renameDraft: 'Begrüßung neu' });
    const input = screen.getByRole('textbox', { name: 'TOP umbenennen' });
    expect(input).toHaveValue('Begrüßung neu');
    await userEvent.type(input, '!');
    fireEvent.keyUp(input, { key: 'Enter' });
    expect(on.renameTop).toHaveBeenCalledWith(AGENDA[0]);
    fireEvent.keyUp(input, { key: 'Escape' });
    expect(on.cancelRename).toHaveBeenCalled();
    fireEvent.blur(input);
    expect(on.renameTop).toHaveBeenCalledTimes(2);
    // A row in rename is no drag source.
    expect(draggable(fixture)).toEqual([false, true, true]);
  });

  it('reorders by drag and drop with the lift and the drop box of the board (frame 7)', async () => {
    const { on, fixture } = await setup();
    expect(draggable(fixture)).toEqual([true, true, true]);
    const row = fixture.debugElement.queryAll(By.directive(CdkDrag))[0].injector.get(CdkDrag);
    expect(row.previewClass).toBe('ap__preview');
    expect(row.dragStartDelay).toEqual({ touch: 400, mouse: 0 });
    drop(fixture, 2, 0);
    expect(on.move).toHaveBeenCalledWith({ from: 2, to: 0 });
    // A drop at the same place moves nothing.
    drop(fixture, 1, 1);
    expect(on.move).toHaveBeenCalledTimes(1);
  });

  it('lifts no row and drops nothing while the agenda saves', async () => {
    const { on, fixture } = await setup({ savingAgenda: true });
    expect(draggable(fixture)).toEqual([false, false, false]);
    drop(fixture, 0, 1);
    expect(on.move).not.toHaveBeenCalled();
  });

  it('names a to-do item in the sub line', async () => {
    await setup({ agenda: [item({ id: 't-7', title: 'Raum buchen', todoId: 'k-1' })] });
    expect(screen.getByText('To-Do')).toBeInTheDocument();
  });

  describe('To-Do anlegen', () => {
    it('opens "Neues To-Do" linked to the TOP and its application', async () => {
      const view = await setup({ locked: true }, true);
      const menu = await openMenu(2);
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'To-Do anlegen' }));
      view.fixture.detectChanges();
      expect(screen.getByRole('dialog', { name: 'Neues To-Do' })).toBeInTheDocument();
      expect(screen.getByText('TOP 3 · Antrag Kulturfestival')).toBeInTheDocument();
      expect(screen.getByText('Antrag Kulturfestival', { selector: '.tn__chipText' })).toBeInTheDocument();
      expect(view.on.remove).not.toHaveBeenCalled();
    });

    it('links a free-text TOP only, also while the agenda saves', async () => {
      const view = await setup({ savingAgenda: true }, true);
      const menu = await openMenu(0);
      const items = within(menu).getAllByRole('menuitem').map((i) => i.textContent?.trim());
      expect(items[0]).toBe('To-Do anlegen');
      await userEvent.click(within(menu).getByRole('menuitem', { name: 'To-Do anlegen' }));
      view.fixture.detectChanges();
      expect(document.querySelectorAll('.tn__chip')).toHaveLength(1);
    });

    it('is not offered without todo.write or without a gremium', async () => {
      await setup({ locked: true }, false);
      expect(screen.queryAllByRole('button', { name: /Aktionen für/ })).toHaveLength(0);
    });

    it('is not offered for a meeting without a gremium', async () => {
      await setup({ locked: true, meeting: meeting({ gremiumId: null }) }, true);
      expect(screen.queryAllByRole('button', { name: /Aktionen für/ })).toHaveLength(0);
    });
  });
});

