import { fireEvent, render, screen, within } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TodosApiService, type TodoBoardEntry } from '@core/api/todos.service';
import { TodoBoardEntriesComponent, entryOf } from './todo-board-entries.component';

const ENTRIES: readonly TodoBoardEntry[] = [
  { id: null, kind: 'team', targetId: 'g-1', name: 'AStA', role: 'manage', fixed: true },
  { id: 'e-1', kind: 'person', targetId: 'p-1', name: 'Astrid Berg', role: 'edit', fixed: false },
];

async function setup(failGremien = false) {
  const api = {
    entryOptions: jest.fn((q?: string) =>
      failGremien && q === undefined
        ? throwError(() => new Error('down'))
        : of({ teams: [{ id: 'g-2', name: 'Fachschaft', logoUrl: null }], persons: [{ id: 'p-2', name: 'Bert' }] }),
    ),
  };
  const added = jest.fn();
  const roleChanged = jest.fn();
  const removed = jest.fn();
  const view = await render(TodoBoardEntriesComponent, {
    inputs: { entries: ENTRIES },
    on: { added, roleChanged, removed },
    providers: [{ provide: TodosApiService, useValue: api }],
  });
  return { ...view, api, added, roleChanged, removed, cmp: view.fixture.componentInstance };
}

describe('TodoBoardEntriesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** § 001064, 001077: the fixed own Gremium shows its role only, a person has a role and a ×. */
  it('lists the entries, changes a role, removes and adds an entry', async () => {
    const view = await setup();
    const list = screen.getByRole('list', { name: 'Mitglieder' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('Verwalten');
    expect(within(rows[0]).queryByRole('button')).toBeNull();
    fireEvent.click(within(rows[1]).getByRole('button', { name: 'Astrid Berg entfernen' }));
    expect(view.removed).toHaveBeenCalledWith(ENTRIES[1]);

    view.cmp.setRole(ENTRIES[1], 'manage');
    expect(view.roleChanged).toHaveBeenCalledWith({ entry: ENTRIES[1], role: 'manage' });
    view.cmp.setRole(ENTRIES[1], 'edit');
    view.cmp.setRole(ENTRIES[1], 'nope');
    expect(view.roleChanged).toHaveBeenCalledTimes(1);

    expect(view.cmp.teams()).toEqual([{ id: 'g-2', name: 'Fachschaft', logoUrl: null }]);
    expect(view.cmp.taken()).toEqual(['g-1', 'p-1']);
    expect(view.cmp.key(ENTRIES[0])).toBe('team:g-1');
    expect(view.cmp.key(ENTRIES[1])).toBe('e-1');
    expect(view.cmp.roleName('nope' as never)).toBe('Bearbeiten');
    const people: unknown[] = [];
    view.cmp.findPeople('be').subscribe((p) => people.push(p));
    expect(people).toEqual([[{ id: 'p-2', name: 'Bert' }]]);
    view.cmp.add({ kind: 'person', id: 'p-2', name: 'Bert' });
    expect(view.added).toHaveBeenCalledWith({ hit: { kind: 'person', id: 'p-2', name: 'Bert' }, role: 'edit' });
  });

  /** § 003063: the members of a team show "Mitglied" and "Verwaltung"; a role outside the list shows the default. */
  it('names the roles of the list it gets', async () => {
    const view = await setup();
    view.fixture.componentRef.setInput('roles', [
      { role: 'edit', label: 'teams.role.member' },
      { role: 'manage', label: 'teams.role.manager' },
    ]);
    expect(view.cmp.roleName('manage')).toBe('Verwaltung');
    expect(view.cmp.roleName('read')).toBe('Mitglied');
    view.fixture.componentRef.setInput('roles', [{ role: 'manage', label: 'teams.role.manager' }]);
    expect(view.cmp.roleName('read')).toBe('Bearbeiten');
  });

  it('offers no Gremien when they cannot load', async () => {
    const view = await setup(true);
    expect(view.cmp.teams()).toEqual([]);
  });

  it('turns a hit into a new entry', () => {
    expect(entryOf({ kind: 'team', id: 'g-2', name: 'Fachschaft', logoUrl: '/l' }, 'read')).toEqual(
      expect.objectContaining({ id: null, kind: 'team', targetId: 'g-2', role: 'read', fixed: false, logoUrl: '/l' }),
    );
    expect(entryOf({ kind: 'person', id: 'p-2', name: 'Bert' }, 'edit')).toEqual(
      expect.objectContaining({ kind: 'person', targetId: 'p-2', role: 'edit' }),
    );
  });
});
