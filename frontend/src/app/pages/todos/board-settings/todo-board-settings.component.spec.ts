import type { CdkDragDrop } from '@angular/cdk/drag-drop';
import { HttpErrorResponse } from '@angular/common/http';
import { fireEvent, render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TodosApiService, type TodoBoard } from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { board, tile } from '../../../../testing/todo-fixtures';
import { TodoBoardSettingsComponent } from './todo-board-settings.component';

const refuse = (code?: string) =>
  throwError(() => new HttpErrorResponse({ status: 422, error: code ? { code } : null }));

async function setup(b: TodoBoard = board()) {
  const answer = jest.fn(() => of(b));
  const api = {
    patchBoard: answer,
    patchColumn: jest.fn(() => of(b)),
    orderColumns: jest.fn(() => of(b)),
    addColumn: jest.fn(() => of(b)),
    deleteColumn: jest.fn(() => of(b)),
    addLabel: jest.fn(() => of({ id: 'l-9', name: 'Aaa', color: 'red' as const })),
    patchLabel: jest.fn(() => of({ id: 'l-1', name: 'Zzz', color: 'gray' as const })),
    deleteLabel: jest.fn(() => of(undefined)),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const changed = jest.fn();
  const view = await render(TodoBoardSettingsComponent, {
    inputs: { open: false, board: b },
    on: { changed },
    providers: [
      { provide: TodosApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  const cmp = view.fixture.componentInstance;
  cmp.open.set(true);
  view.fixture.detectChanges();
  return { ...view, api, toast, changed, cmp, detect: () => view.fixture.detectChanges() };
}

describe('TodoBoardSettingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the name, the columns with their counts, the labels and the archive', async () => {
    const { cmp } = await setup();
    expect(screen.getByRole('dialog', { name: 'Board-Einstellungen' })).toBeInTheDocument();
    expect(cmp.name()).toBe('Studierendenparlament');
    expect(screen.getByText('2 Karten')).toBeInTheDocument();
    expect(screen.getByText('Erledigt-Spalte')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Label Haushalt bearbeiten' })).toBeInTheDocument();
    expect(screen.getByText('Erledigte Karten nach 30 Tagen archivieren')).toBeInTheDocument();
    expect(cmp.days()).toBe(30);
    fireEvent.click(screen.getByRole('button', { name: 'Fertig' }));
    expect(cmp.open()).toBe(false);
  });

  it('saves a new name, keeps the old one for an empty or the same name', async () => {
    const { cmp, api, changed } = await setup();
    cmp.name.set('  ');
    cmp.saveName();
    expect(cmp.name()).toBe('Studierendenparlament');
    cmp.saveName();
    expect(api.patchBoard).not.toHaveBeenCalled();
    cmp.name.set(' StuPa ');
    cmp.saveName();
    expect(api.patchBoard).toHaveBeenCalledWith('b-1', { name: 'StuPa' });
    expect(changed).toHaveBeenCalled();
    expect(cmp.busy()).toBe(false);
  });

  it('turns the archive on and off and checks the days', async () => {
    const { cmp, api, toast } = await setup(board({ archiveAfterDays: null }));
    expect(cmp.archiveOn()).toBe(false);
    expect(cmp.days()).toBe(30);
    cmp.setArchive(true);
    expect(api.patchBoard).toHaveBeenLastCalledWith('b-1', { archiveAfterDays: 30 });
    cmp.setArchive(false);
    expect(api.patchBoard).toHaveBeenLastCalledWith('b-1', { archiveAfterDays: null });
    cmp.days.set(0);
    cmp.saveDays();
    expect(toast.error).toHaveBeenCalledWith('Zwischen 1 und 365 Tagen.');
    expect(cmp.days()).toBe(30);
    cmp.days.set('abc' as never);
    cmp.saveDays();
    cmp.days.set(400);
    cmp.saveDays();
    expect(toast.error).toHaveBeenCalledTimes(3);
    cmp.days.set(14);
    cmp.saveDays();
    expect(api.patchBoard).toHaveBeenLastCalledWith('b-1', { archiveAfterDays: 14 });
  });

  it('keeps the days of an archive that has them', async () => {
    const { cmp, api } = await setup(board({ archiveAfterDays: 14 }));
    cmp.days.set(14);
    cmp.saveDays();
    expect(api.patchBoard).not.toHaveBeenCalled();
    cmp.days.set(999);
    cmp.saveDays();
    expect(cmp.days()).toBe(14);
    expect(screen.getByRole('spinbutton', { name: 'Tage' })).toBeInTheDocument();
  });

  it('builds the column menu by position and runs it', async () => {
    const { cmp, api, detect } = await setup();
    const cols = cmp.columns();
    expect(cmp.columnMenu(cols[0], 0)[0].items.map((i) => i.id)).toEqual(['rename', 'done', 'down']);
    expect(cmp.columnMenu(cols[3], 3)[0].items.map((i) => i.id)).toEqual(['rename', 'up']);
    expect(cmp.columnMenu(cols[3], 3)[1].items[0].disabledReason).toBe('Die Erledigt-Spalte kann nicht gelöscht werden.');
    expect(cmp.columnMenu(cols[1], 1)[1].items[0].disabledReason).toBeNull();
    cmp.onColumnMenu(cols[1], 1, { id: 'done', label: '' });
    expect(api.patchColumn).toHaveBeenCalledWith('b-1', 'c-2', { isDone: true });
    cmp.onColumnMenu(cols[1], 1, { id: 'up', label: '' });
    expect(api.orderColumns).toHaveBeenLastCalledWith('b-1', ['c-2', 'c-1', 'c-3', 'c-4']);
    cmp.onColumnMenu(cols[1], 1, { id: 'down', label: '' });
    expect(api.orderColumns).toHaveBeenLastCalledWith('b-1', ['c-1', 'c-3', 'c-2', 'c-4']);
    cmp.onColumnMenu(cols[1], 1, { id: 'odd', label: '' });
    cmp.onColumnMenu(cols[1], 1, { id: 'rename', label: '' });
    detect();
    expect(screen.getByRole('textbox', { name: 'Name der Spalte' })).toBeInTheDocument();
    expect(cmp.renameDraft()).toBe('In Arbeit');
    cmp.saveRename(cols[1]);
    expect(cmp.renaming()).toBeNull();
    cmp.renameDraft.set(' ');
    cmp.saveRename(cols[1]);
    expect(api.patchColumn).toHaveBeenCalledTimes(1);
    cmp.onColumnMenu(cols[1], 1, { id: 'rename', label: '' });
    cmp.renameDraft.set('Läuft');
    cmp.saveRename(cols[1]);
    expect(api.patchColumn).toHaveBeenLastCalledWith('b-1', 'c-2', { name: 'Läuft' });
    expect(cmp.renaming()).toBeNull();
  });

  it('reorders by drag', async () => {
    const { cmp, api } = await setup();
    cmp.drop({ previousIndex: 1, currentIndex: 1 } as CdkDragDrop<unknown>);
    expect(api.orderColumns).not.toHaveBeenCalled();
    cmp.drop({ previousIndex: 0, currentIndex: 2 } as CdkDragDrop<unknown>);
    expect(api.orderColumns).toHaveBeenCalledWith('b-1', ['c-2', 'c-3', 'c-1', 'c-4']);
  });

  it('adds a column', async () => {
    const { cmp, api, detect } = await setup();
    fireEvent.click(screen.getByRole('button', { name: /Spalte hinzufügen/ }));
    detect();
    expect(cmp.newColumn()).toBe('');
    cmp.addColumn();
    expect(api.addColumn).not.toHaveBeenCalled();
    cmp.newColumn.set(' Später ');
    cmp.addColumn();
    expect(api.addColumn).toHaveBeenCalledWith('b-1', 'Später');
    expect(cmp.newColumn()).toBeNull();
    cmp.newColumn.set(null);
    cmp.addColumn();
    expect(api.addColumn).toHaveBeenCalledTimes(1);
  });

  it('deletes an empty column at once and asks where the cards of a full one go', async () => {
    const { cmp, api, detect } = await setup();
    const cols = cmp.columns();
    cmp.onColumnMenu(cols[1], 1, { id: 'delete', label: '' });
    expect(api.deleteColumn).toHaveBeenCalledWith('b-1', 'c-2');
    cmp.deleteColumn(cols[0]);
    detect();
    expect(screen.getByText('„Offen“ hat 2 Karten. Wohin sollen sie?')).toBeInTheDocument();
    expect(cmp.moveTo()).toBe('c-2');
    expect(cmp.moveOptions().map((o) => o.value)).toEqual(['c-2', 'c-3', 'c-4']);
    cmp.moveTo.set('c-4');
    cmp.confirmDelete();
    expect(api.deleteColumn).toHaveBeenLastCalledWith('b-1', 'c-1', 'c-4');
    expect(cmp.deleting()).toBeNull();
    cmp.confirmDelete();
    expect(api.deleteColumn).toHaveBeenCalledTimes(2);
  });

  it('cannot delete the only column with cards without a target', async () => {
    const only = board({
      columns: [{ id: 'c-1', name: 'Offen', position: 0, isDone: true, cardCount: 0 }],
      cards: [tile({ columnId: 'c-1' })],
    });
    const { cmp, api } = await setup(only);
    cmp.deleteColumn(cmp.columns()[0]);
    expect(cmp.moveTo()).toBe('');
    cmp.confirmDelete();
    expect(api.deleteColumn).not.toHaveBeenCalled();
  });

  it('adds, edits and deletes a label', async () => {
    const { cmp, api, changed, detect } = await setup();
    fireEvent.click(screen.getByRole('button', { name: /Label hinzufügen/ }));
    detect();
    expect(cmp.labelEdit()).toBe('');
    expect(screen.queryByRole('button', { name: 'Label löschen' })).toBeNull();
    cmp.saveLabel();
    expect(api.addLabel).not.toHaveBeenCalled();
    cmp.labelName.set(' Aaa ');
    fireEvent.click(screen.getByRole('radio', { name: 'Rot' }));
    expect(cmp.labelColor()).toBe('red');
    cmp.saveLabel();
    expect(api.addLabel).toHaveBeenCalledWith('b-1', { name: 'Aaa', color: 'red' });
    expect(changed).toHaveBeenLastCalledWith(
      expect.objectContaining({ labels: [expect.objectContaining({ name: 'Aaa' }), expect.objectContaining({ name: 'Haushalt' }), expect.objectContaining({ name: 'Sitzung' })] }),
    );
    expect(cmp.labelEdit()).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Label Haushalt bearbeiten' }));
    detect();
    expect(cmp.labelName()).toBe('Haushalt');
    expect(cmp.labelColor()).toBe('amber');
    cmp.saveLabel();
    expect(api.patchLabel).toHaveBeenCalledWith('b-1', 'l-1', { name: 'Haushalt', color: 'amber' });
    expect(changed.mock.lastCall[0].labels.map((l: { name: string }) => l.name)).toEqual(['Sitzung', 'Zzz']);

    cmp.editLabel(board().labels[0]);
    detect();
    fireEvent.click(screen.getByRole('button', { name: 'Label löschen' }));
    expect(api.deleteLabel).toHaveBeenCalledWith('b-1', 'l-1');
    const after = changed.mock.lastCall[0] as TodoBoard;
    expect(after.labels.map((l) => l.id)).toEqual(['l-2']);
    expect(after.cards.find((c) => c.id === 'k-2')?.labelIds).toEqual([]);
    expect(cmp.colorName('violet')).toBe('Violett');
  });

  it('does nothing for a label form that is closed or new', async () => {
    const { cmp, api } = await setup();
    cmp.labelEdit.set(null);
    cmp.labelName.set('x');
    cmp.saveLabel();
    cmp.deleteLabel();
    cmp.labelEdit.set('');
    cmp.deleteLabel();
    expect(api.addLabel).not.toHaveBeenCalled();
    expect(api.deleteLabel).not.toHaveBeenCalled();
  });

  it('names the refusal of the server', async () => {
    const { cmp, api, toast } = await setup();
    for (const [code, text] of [
      ['todo_configure_required', 'Du darfst dieses Board nicht einrichten.'],
      ['column_not_empty', 'Die Spalte hat noch Karten.'],
      ['done_column_required', 'Die Erledigt-Spalte kann nicht gelöscht werden.'],
      ['odd', 'Die Einstellung konnte nicht gespeichert werden.'],
      [undefined, 'Die Einstellung konnte nicht gespeichert werden.'],
    ] as const) {
      api.deleteColumn.mockReturnValueOnce(refuse(code));
      cmp.deleteColumn(cmp.columns()[1]);
      expect(toast.error).toHaveBeenLastCalledWith(text);
    }
    api.addLabel.mockReturnValueOnce(refuse('label_exists') as never);
    cmp.editLabel(null);
    cmp.labelName.set('Haushalt');
    cmp.saveLabel();
    expect(toast.error).toHaveBeenLastCalledWith('Dieses Label gibt es schon.');
    api.deleteLabel.mockReturnValueOnce(throwError(() => new Error('net')) as never);
    cmp.editLabel(board().labels[0]);
    cmp.deleteLabel();
    expect(toast.error).toHaveBeenLastCalledWith('Die Einstellung konnte nicht gespeichert werden.');
    expect(cmp.busy()).toBe(false);
  });

  it('starts fresh at each opening', async () => {
    const { cmp, fixture } = await setup();
    cmp.newColumn.set('x');
    cmp.labelEdit.set('');
    cmp.open.set(false);
    fixture.detectChanges();
    cmp.open.set(true);
    fixture.detectChanges();
    expect(cmp.newColumn()).toBeNull();
    expect(cmp.labelEdit()).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(cmp.open()).toBe(false);
  });
});
