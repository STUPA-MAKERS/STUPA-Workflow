import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { EventsApiService } from '@core/api/events.service';
import { TodosApiService } from '@core/api/todos.service';
import { linkRow } from '../../../testing/todo-fixtures';
import { EventLinkState } from './event-link.state';
import { TodoLinkedRefresh } from './linked-list/todo-linked-refresh';

const OLD = linkRow({ id: 'l-7', kind: 'event', targetId: 'ev-old', title: 'Sommerfest' });

function setup(links = [OLD], fail = false) {
  localStorage.setItem('ap.locale', 'de');
  const events = {
    refs: jest.fn(() =>
      fail
        ? throwError(() => ({ status: 500 }))
        : of([
            { id: 'ev-1', number: 'V-1', title: 'Erstiparty', teamName: 'Kultur', startsOn: '2026-11-20', endsOn: null, startTime: null, endTime: null },
          ]),
    ),
  };
  const api = {
    links: jest.fn(() => (fail ? throwError(() => ({ status: 500 })) : of({ canLink: true, links }))),
    link: jest.fn(() => of({ canLink: true, links: [linkRow({ id: 'l-9', kind: 'expense', targetId: 'x-1' })] })),
    unlink: jest.fn(() => of(undefined)),
  };
  TestBed.configureTestingModule({
    providers: [
      { provide: TodosApiService, useValue: api },
      { provide: EventsApiService, useValue: events },
    ],
  });
  const state = TestBed.runInInjectionContext(() => new EventLinkState());
  const touched = jest.spyOn(TestBed.inject(TodoLinkedRefresh), 'touch');
  return { api, events, state, touched };
}

describe('EventLinkState', () => {
  afterEach(() => localStorage.clear());

  /** §F/collaboration/events/003033: the picker lists the Events that the person writes. */
  it('lists the open Events and links the picked one to a new booking', () => {
    const { api, state, touched } = setup();
    state.load(null);
    expect(state.options()).toEqual([
      { value: '', label: 'Keine Veranstaltung' },
      { value: 'ev-1', label: 'Erstiparty · 20.11.2026 · Kultur' },
    ]);
    expect(api.links).not.toHaveBeenCalled();
    state.value.set('ev-1');
    expect(state.changed()).toBe(true);
    state.apply('x-1').subscribe();
    expect(api.link).toHaveBeenCalledWith({ kind: 'event', id: 'ev-1' }, { kind: 'expense', id: 'x-1' });
    expect(api.unlink).not.toHaveBeenCalled();
    expect(touched).toHaveBeenCalledWith([
      { kind: 'expense', targetId: 'x-1' },
      { kind: 'event', targetId: 'ev-1' },
    ]);
    expect(state.changed()).toBe(false);
  });

  it('moves the link of an edited booking from its Event to another, and sends nothing without a change', () => {
    const { api, state, touched } = setup();
    state.load('x-1');
    expect(api.links).toHaveBeenCalledWith('expense', 'x-1');
    expect(state.value()).toBe('ev-old');
    expect(state.options()[1]).toEqual({ value: 'ev-old', label: 'Sommerfest' });
    state.apply('x-1').subscribe();
    expect(api.link).not.toHaveBeenCalled();
    state.value.set('ev-1');
    state.apply('x-1').subscribe();
    expect(api.unlink).toHaveBeenCalledWith('l-7');
    expect(api.link).toHaveBeenCalledWith({ kind: 'event', id: 'ev-1' }, { kind: 'expense', id: 'x-1' });
    expect(touched).toHaveBeenCalledWith([
      { kind: 'expense', targetId: 'x-1' },
      { kind: 'event', targetId: 'ev-old' },
      { kind: 'event', targetId: 'ev-1' },
    ]);
  });

  it('removes the link when the pick goes back to none', () => {
    const { api, state } = setup();
    state.load('x-1');
    state.value.set('');
    state.apply('x-1').subscribe();
    expect(api.unlink).toHaveBeenCalledWith('l-7');
    expect(api.link).not.toHaveBeenCalled();
  });

  it('keeps the current Event once in the options', () => {
    const { state } = setup([linkRow({ id: 'l-8', kind: 'event', targetId: 'ev-1', title: null as never })]);
    state.load('x-1');
    expect(state.options().map((o) => o.value)).toEqual(['', 'ev-1']);
  });

  it('keeps none for a booking without a linked Event', () => {
    const { state } = setup([linkRow()]);
    state.load('x-2');
    expect(state.value()).toBe('');
  });

  it('shows only "Keine Veranstaltung" when the reads fail', () => {
    const { state } = setup([], true);
    state.load('x-1');
    expect(state.options()).toEqual([{ value: '', label: 'Keine Veranstaltung' }]);
  });
});
