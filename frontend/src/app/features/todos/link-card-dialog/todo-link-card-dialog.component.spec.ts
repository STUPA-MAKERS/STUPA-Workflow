import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import { NEVER, of, throwError } from 'rxjs';
import { TodosApiService } from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { TodoLinkedRefresh } from '../linked-list/todo-linked-refresh';
import { TodoLinkCardDialogComponent } from './todo-link-card-dialog.component';

function mineItem(id: string, title: string, boardName: string) {
  return { id, title, boardName, columnName: 'Offen' };
}

async function setup(opts: { fail?: boolean; exclude?: string[]; boardsPending?: boolean } = {}) {
  jest.useFakeTimers();
  const api = {
    boards: jest.fn(() =>
      opts.boardsPending ? NEVER : of([
        { id: 'b-1', name: 'StuPa', canWrite: true },
        { id: 'b-2', name: 'Finanzen', canWrite: false },
      ]),
    ),
    mine: jest.fn(() =>
      of({
        items: [
          mineItem('k-1', 'Beleg prüfen', 'StuPa'),
          mineItem('k-2', 'Nur lesen', 'Finanzen'),
          mineItem('k-3', 'Schon da', 'StuPa'),
        ],
        dueSoonCount: 0,
      }),
    ),
    linkTargets: jest.fn(() =>
      of([
        {
          kind: 'todo',
          targetId: 'k-9',
          title: 'Kasse zählen',
          detail: { boardName: 'StuPa', columnName: 'In Arbeit' },
        },
        { kind: 'todo', targetId: 'k-8', title: 'Ohne Board', detail: {} },
      ]),
    ),
    addLink: jest.fn(() => (opts.fail ? throwError(() => new Error('x')) : of({}))),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(TodoLinkCardDialogComponent, {
    inputs: { open: true, kind: 'expense', targetId: 'e-1', exclude: opts.exclude ?? ['k-3'] },
    providers: [
      { provide: TodosApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  const settle = () => {
    jest.advanceTimersByTime(200);
    view.fixture.detectChanges();
  };
  settle();
  return { ...view, api, toast, settle, cmp: view.fixture.componentInstance };
}

describe('TodoLinkCardDialogComponent (spec 000548)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => jest.useRealTimers());

  it('lists the own cards on writable boards, without the ones that link the element', async () => {
    const { cmp } = await setup();
    expect(cmp.rows()).toEqual([{ id: 'k-1', title: 'Beleg prüfen', sub: 'StuPa · Offen' }]);
    expect(cmp.pick()).toBe('k-1');
  });

  it('searches every readable card from two characters on', async () => {
    const { cmp, api, settle, fixture } = await setup();
    cmp.query.set('Ka');
    fixture.detectChanges();
    settle();
    expect(api.linkTargets).toHaveBeenCalledWith('Ka', 'todo');
    expect(cmp.rows()?.map((r) => r.id)).toEqual(['k-9']);
  });

  it('links the picked card to a Buchung and tells the lists', async () => {
    const { cmp, api, toast } = await setup();
    const touch = jest.spyOn(TestBed.inject(TodoLinkedRefresh), 'touch');
    const linked = jest.fn();
    cmp.linked.subscribe(linked);
    cmp.submit('k-1');
    expect(api.addLink).toHaveBeenCalledWith('k-1', 'expense', 'e-1');
    expect(touch).toHaveBeenCalledWith([{ kind: 'expense', targetId: 'e-1' }]);
    expect(toast.success).toHaveBeenCalledWith('Verknüpft');
    expect(linked).toHaveBeenCalledWith('k-1');
    expect(cmp.open()).toBe(false);
  });

  it('keeps the dialog open on a failure', async () => {
    const { cmp, toast } = await setup({ fail: true });
    cmp.submit('k-1');
    expect(toast.error).toHaveBeenCalledWith('Die Verknüpfung ist fehlgeschlagen.');
    expect(cmp.open()).toBe(true);
    expect(cmp.busy()).toBe(false);
  });

  it('shows the rows as radios in the dialog', async () => {
    await setup();
    expect(screen.getByRole('radiogroup', { name: 'To-Dos' })).toBeInTheDocument();
    expect(screen.getByRole('radio')).toBeChecked();
  });

  it('lists nothing and picks nothing while the boards load', async () => {
    const { cmp } = await setup({ boardsPending: true });
    expect(cmp.rows()).toBeNull();
    expect(cmp.pick()).toBeNull();
  });
});
