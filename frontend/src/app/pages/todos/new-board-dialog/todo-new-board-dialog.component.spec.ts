import { HttpErrorResponse } from '@angular/common/http';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TodosApiService } from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { board } from '../../../../testing/todo-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { TodoNewBoardDialogComponent } from './todo-new-board-dialog.component';

async function setup() {
  const created = board({ id: 'b-9', name: 'Ersti-Woche', kind: 'free', gremiumId: null });
  const api = {
    entryOptions: jest.fn(() => of({ gremien: [{ id: 'g-1', name: 'AStA', logoUrl: null }], persons: [] })),
    createBoard: jest.fn(() => of(created)),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const onCreated = jest.fn();
  const view = await render(TodoNewBoardDialogComponent, {
    inputs: { open: true },
    on: { created: onCreated },
    providers: [
      { provide: TodosApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, api, toast, onCreated, created, cmp: view.fixture.componentInstance };
}

describe('TodoNewBoardDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** § 001061, 001074: a name and the members of the one picker, each with a role. */
  it('creates a free board with a Gremium and a person', async () => {
    const view = await setup();
    const dialog = screen.getByRole('dialog', { name: 'Neues Board' });
    const create = within(dialog).getByRole('button', { name: 'Anlegen' });
    expect(create).toBeDisabled();
    fireEvent.input(within(dialog).getByLabelText(/Name/), { target: { value: 'Ersti-Woche' } });
    view.cmp.add({ hit: { kind: 'gremium', id: 'g-1', name: 'AStA', logoUrl: null }, role: 'edit' });
    view.cmp.add({ hit: { kind: 'person', id: 'p-2', name: 'Lea Schmid' }, role: 'edit' });
    view.cmp.setRole({ entry: view.cmp.entries()[0], role: 'read' });
    view.fixture.detectChanges();
    expect(within(dialog).getByRole('button', { name: 'Rolle von AStA: Lesen' })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Lea Schmid entfernen' }));
    view.cmp.add({ hit: { kind: 'person', id: 'p-3', name: 'Jonas Weber' }, role: 'edit' });
    view.fixture.detectChanges();
    expect(await runAxe(view.container)).toHaveNoViolations();
    fireEvent.click(create);
    expect(view.api.createBoard).toHaveBeenCalledWith('Ersti-Woche', [
      { gremiumId: 'g-1', role: 'read' },
      { principalId: 'p-3', role: 'edit' },
    ]);
    expect(view.onCreated).toHaveBeenCalledWith(view.created);
    expect(view.toast.success).toHaveBeenCalledWith('Board angelegt.');
    expect(view.cmp.open()).toBe(false);
  });

  it('says so when the right to create is missing', async () => {
    const view = await setup();
    view.api.createBoard.mockReturnValueOnce(
      throwError(() => new HttpErrorResponse({ status: 403, error: { code: 'board_create_required' } })),
    );
    view.cmp.name.set('X');
    view.cmp.submit();
    expect(view.toast.error).toHaveBeenCalledWith('Du darfst keine Boards anlegen.');
    expect(view.cmp.open()).toBe(true);
  });
});
