import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { TodosApiService, type TodoLinkedCard } from '@core/api/todos.service';
import { detail, link } from '../../../testing/todo-fixtures';
import { EventLinkState } from './event-link.state';
import { TodoLinkedRefresh } from './linked-list/todo-linked-refresh';

const EVENT = { startsOn: '2026-11-20', endsOn: '2026-11-21', place: 'Mensa', participants: null, seriesId: null, seriesName: null };

function linkedEvent(): TodoLinkedCard {
  return {
    id: 'ev-old',
    boardId: 'b-9',
    boardName: 'AStA',
    title: 'Sommerfest',
    columnName: 'Offen',
    isDone: false,
    dueDate: null,
    assignees: [],
    event: EVENT,
    balance: '0.00',
  };
}

function setup(linked: TodoLinkedCard[] = []) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    writableEvents: jest.fn(() =>
      of([{ id: 'ev-1', boardId: 'b-1', boardName: 'StuPa', title: 'Erstiparty', startsOn: '2026-11-20', endsOn: null }]),
    ),
    linked: jest.fn(() => of(linked)),
    card: jest.fn(() => of(detail({ id: 'ev-old', links: [link({ id: 'l-7', kind: 'expense', targetId: 'x-1' })] }))),
    addLink: jest.fn(() => of(detail())),
    removeLink: jest.fn(() => of(detail())),
  };
  TestBed.configureTestingModule({ providers: [{ provide: TodosApiService, useValue: api }] });
  const state = TestBed.runInInjectionContext(() => new EventLinkState());
  const touched = jest.spyOn(TestBed.inject(TodoLinkedRefresh), 'touch');
  return { api, state, touched };
}

describe('EventLinkState', () => {
  it('lists the writable Events and links the picked one to a new booking (spec 000480)', () => {
    const { api, state, touched } = setup();
    state.load(null);
    expect(state.options()).toEqual([
      { value: '', label: 'Keine Veranstaltung' },
      { value: 'ev-1', label: 'Erstiparty · 20.11.2026 · StuPa' },
    ]);
    expect(api.linked).not.toHaveBeenCalled();
    state.value.set('ev-1');
    state.apply('x-1').subscribe();
    expect(api.addLink).toHaveBeenCalledWith('ev-1', 'expense', 'x-1');
    expect(api.removeLink).not.toHaveBeenCalled();
    expect(touched).toHaveBeenCalledWith([{ kind: 'expense', targetId: 'x-1' }]);
    expect(state.changed()).toBe(false);
  });

  it('moves the link of an edited booking from its Event to another, and sends nothing without a change', () => {
    const { api, state } = setup([linkedEvent()]);
    state.load('x-1');
    expect(state.value()).toBe('ev-old');
    expect(state.options()[1]).toEqual({ value: 'ev-old', label: 'Sommerfest · AStA' });
    state.apply('x-1').subscribe();
    expect(api.addLink).not.toHaveBeenCalled();
    state.value.set('ev-1');
    state.apply('x-1').subscribe();
    expect(api.removeLink).toHaveBeenCalledWith('ev-old', 'l-7');
    expect(api.addLink).toHaveBeenCalledWith('ev-1', 'expense', 'x-1');
  });

  it('removes the link when the pick goes back to none', () => {
    const { api, state } = setup([linkedEvent()]);
    state.load('x-1');
    state.value.set('');
    state.apply('x-1').subscribe();
    expect(api.removeLink).toHaveBeenCalledWith('ev-old', 'l-7');
    expect(api.addLink).not.toHaveBeenCalled();
  });
});
