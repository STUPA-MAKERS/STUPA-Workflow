import { HttpErrorResponse } from '@angular/common/http';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TodosApiService } from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { summary } from '../../../../testing/todo-fixtures';
import { TodoArchivedBoardsComponent } from './todo-archived-boards.component';
import { toastMock } from '../../../../testing/toast';

const ARCHIVED = [
  summary({ id: 'b-7', name: 'Ersti-Woche', kind: 'free', gremiumId: null, canConfigure: true, archived: true }),
  summary({ id: 'b-8', name: 'Sommerfest', kind: 'free', gremiumId: null, canConfigure: false, archived: true }),
];

async function setup(admin: boolean) {
  const api = {
    archivedBoards: jest.fn(() => of(ARCHIVED)),
    restoreBoard: jest.fn(() => of({ ...ARCHIVED[0], archived: false })),
    deleteBoard: jest.fn(() => of(undefined)),
  };
  const toast = toastMock();
  const restored = jest.fn();
  const emptied = jest.fn();
  const view = await render(TodoArchivedBoardsComponent, {
    inputs: { open: true },
    on: { restored, emptied },
    providers: [
      { provide: TodosApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: { isAdmin: () => admin } },
    ],
  });
  return { ...view, api, toast, restored, emptied, cmp: view.fixture.componentInstance };
}

describe('TodoArchivedBoardsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** § 001068: a manager restores, only an admin deletes. */
  it('restores a board that the person manages and offers no delete to a non-admin', async () => {
    const view = await setup(false);
    const list = screen.getByRole('list', { name: 'Archivierte Boards' });
    expect(within(list).getAllByRole('button', { name: 'Wiederherstellen' })).toHaveLength(1);
    expect(within(list).queryByRole('button', { name: /löschen/ })).toBeNull();
    fireEvent.click(within(list).getByRole('button', { name: 'Wiederherstellen' }));
    expect(view.api.restoreBoard).toHaveBeenCalledWith('b-7');
    expect(view.restored).toHaveBeenCalled();
    expect(view.cmp.boards().map((b) => b.id)).toEqual(['b-8']);
  });

  it('deletes a board as an admin after the question and says when the server refuses', async () => {
    const view = await setup(true);
    fireEvent.click(screen.getByRole('button', { name: 'Sommerfest löschen' }));
    view.fixture.detectChanges();
    const ask = screen.getByRole('dialog', { name: 'Board löschen?' });
    fireEvent.click(within(ask).getByRole('button', { name: 'Löschen' }));
    expect(view.api.deleteBoard).toHaveBeenCalledWith('b-8');
    view.api.deleteBoard.mockReturnValueOnce(
      throwError(() => new HttpErrorResponse({ status: 403, error: { code: 'board_delete_admin_only' } })),
    );
    view.cmp.deleting.set(view.cmp.boards()[0]);
    view.cmp.confirmDelete();
    expect(view.toast.error).toHaveBeenCalledWith('Nur Admins können ein Board löschen.');
    view.cmp.deleting.set(view.cmp.boards()[0]);
    view.api.deleteBoard.mockReturnValueOnce(of(undefined));
    view.cmp.confirmDelete();
    expect(view.emptied).toHaveBeenCalled();
  });

  it('says when the list does not load and when a restore fails', async () => {
    const view = await setup(false);
    view.api.restoreBoard.mockReturnValueOnce(throwError(() => new Error('down')));
    view.cmp.restore(view.cmp.boards()[0]);
    expect(view.toast.error).toHaveBeenCalledWith('Die Änderung konnte nicht gespeichert werden.');
    expect(view.cmp.busy()).toBeNull();
    view.api.archivedBoards.mockReturnValueOnce(throwError(() => new Error('down')));
    view.fixture.componentRef.setInput('open', false);
    view.fixture.detectChanges();
    view.fixture.componentRef.setInput('open', true);
    view.fixture.detectChanges();
    expect(view.toast.error).toHaveBeenCalledWith('Die archivierten Boards konnten nicht geladen werden.');
  });

  it('does nothing without a board to delete and says so when the delete fails', async () => {
    const view = await setup(true);
    view.cmp.confirmDelete();
    expect(view.api.deleteBoard).not.toHaveBeenCalled();
    view.api.deleteBoard.mockReturnValueOnce(throwError(() => new Error('down')));
    view.cmp.deleting.set(view.cmp.boards()[0]);
    view.cmp.confirmDelete();
    expect(view.toast.error).toHaveBeenLastCalledWith('Die Änderung konnte nicht gespeichert werden.');
  });
});
