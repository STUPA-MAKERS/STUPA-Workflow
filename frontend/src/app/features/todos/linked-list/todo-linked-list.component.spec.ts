import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { TodosApiService, type TodoLinkedCard } from '@core/api/todos.service';
import { TestBed } from '@angular/core/testing';
import { TodoLinkedListComponent } from './todo-linked-list.component';
import { TodoLinkedRefresh } from './todo-linked-refresh';

function card(over: Partial<TodoLinkedCard> = {}): TodoLinkedCard {
  return {
    id: 'k-1',
    boardId: 'b-1',
    boardName: 'Studierendenparlament',
    title: 'Raum buchen',
    columnName: 'In Arbeit',
    isDone: false,
    dueDate: '2026-10-17',
    assignees: [{ principalId: 'p-1', displayName: 'Mara Keller' }, { principalId: null, displayName: null }],
    event: null,
    balance: null,
    ...over,
  };
}

async function setup(answer: () => Observable<TodoLinkedCard[]>, extra: Record<string, unknown> = {}) {
  const api = { linked: jest.fn(answer) };
  const view = await render(TodoLinkedListComponent, {
    inputs: { kind: 'application', targetId: 'a-1', headingId: 'ad-todos', ...extra },
    providers: [provideRouter([]), { provide: TodosApiService, useValue: api }],
  });
  return { ...view, api, cmp: view.fixture.componentInstance };
}

describe('TodoLinkedListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the linked cards with board, column, due date and people, each a link to its card', async () => {
    const { api, cmp } = await setup(() => of([card(), card({ id: 'k-2', title: 'Erledigt', isDone: true, dueDate: null, assignees: [] })]));
    expect(api.linked).toHaveBeenCalledWith('application', 'a-1');
    expect(screen.getByRole('heading', { name: 'Verknüpft' })).toHaveAttribute('id', 'ad-todos');
    expect(screen.getByRole('link', { name: 'Raum buchen' })).toHaveAttribute('href', '/todos?card=k-1');
    expect(screen.getByText('Studierendenparlament · In Arbeit · fällig 17.10.')).toBeInTheDocument();
    expect(screen.getByText('Studierendenparlament · In Arbeit')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Erledigt' }).closest('li')).toHaveClass('tl__row--done');
    expect(cmp.names(card())).toEqual(['Mara Keller', 'Gelöschte Person']);
    expect(cmp.ids(card())).toEqual(['p-1', null]);
    expect(document.querySelectorAll('app-avatar-stack')).toHaveLength(1);
  });

  it('leaves out the heading on request and keeps the name of the section', async () => {
    await setup(() => of([card()]), { showTitle: false });
    const heading = screen.getByRole('heading', { name: 'Verknüpft' });
    expect(heading.closest('.section__head')).toHaveClass('section__head--hidden');
    expect(screen.getByRole('group', { name: 'Verknüpft' })).toBeInTheDocument();
  });

  it('shows the cards of the page without a read of its own', async () => {
    const { api, fixture } = await setup(() => of([card({ id: 'k-8', title: 'Vom Server' })]), {
      items: [card()],
      avatarSize: 'xs',
    });
    expect(api.linked).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: 'Raum buchen' })).toBeInTheDocument();
    expect(document.querySelector('app-avatar')).toHaveClass('av--xs');
    TestBed.inject(TodoLinkedRefresh).touch([{ kind: 'application', targetId: 'a-1' }]);
    fixture.componentRef.setInput('items', [card({ id: 'k-2', title: 'Zweite' })]);
    fixture.detectChanges();
    expect(api.linked).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: 'Zweite' })).toBeInTheDocument();
  });

  it('shows a linked Event with its dates, board, place and balance (spec 000489)', async () => {
    const event = { startsOn: '2026-11-20', endsOn: '2026-11-21', place: 'Mensa', participants: null, seriesId: null, seriesName: null };
    await setup(() => of([card({ id: 'ev', title: 'Erstiparty', event, balance: '-725.40' }), card()]));
    const rows = [...document.querySelectorAll('.tl__row')];
    expect(rows[0]).toHaveClass('tl__row--event');
    expect(rows[0]).toHaveTextContent('Erstiparty');
    expect(screen.getByText('Veranstaltung · 20.11.–21.11.2026 · Studierendenparlament')).toBeInTheDocument();
    expect(rows[0].querySelector('.tl__neg')?.textContent).toContain('−725,40');
    expect(rows[0]).toHaveTextContent('Mensa');
  });

  it('shows nothing without linked cards', async () => {
    const { container } = await setup(() => of([]));
    expect(container.querySelector('section')).toBeNull();
  });

  it('shows nothing when the read fails', async () => {
    const { container } = await setup(() => throwError(() => new Error('x')));
    expect(container.querySelector('section')).toBeNull();
  });

  it('reads again for another target and drops a late answer', async () => {
    const late = new Subject<TodoLinkedCard[]>();
    let first = true;
    const { api, fixture, cmp } = await setup(() => {
      if (first) {
        first = false;
        return late;
      }
      return of([card({ id: 'k-9', title: 'Neu' })]);
    });
    fixture.componentRef.setInput('kind', 'agenda_item');
    fixture.componentRef.setInput('targetId', 'ai-1');
    fixture.detectChanges();
    expect(api.linked).toHaveBeenLastCalledWith('agenda_item', 'ai-1');
    late.next([card()]);
    expect(cmp.cards().map((c) => c.id)).toEqual(['k-9']);
  });

  it('reads again, keeping the list, when a card is linked to its target elsewhere', async () => {
    let answer = [card()];
    const { api, fixture, cmp } = await setup(() => of(answer));
    const refresh = TestBed.inject(TodoLinkedRefresh);
    expect(api.linked).toHaveBeenCalledTimes(1);
    refresh.touch([{ kind: 'agenda_item', targetId: 'a-1' }]);
    fixture.detectChanges();
    expect(api.linked).toHaveBeenCalledTimes(1);
    refresh.touch([]);
    fixture.detectChanges();
    expect(api.linked).toHaveBeenCalledTimes(1);
    const late = new Subject<TodoLinkedCard[]>();
    api.linked.mockReturnValueOnce(late);
    refresh.touch([{ kind: 'application', targetId: 'a-1' }]);
    fixture.detectChanges();
    expect(api.linked).toHaveBeenCalledTimes(2);
    expect(cmp.cards().map((c) => c.id)).toEqual(['k-1']);
    answer = [card(), card({ id: 'k-2', title: 'Neu' })];
    late.next(answer);
    fixture.detectChanges();
    expect(screen.getByRole('link', { name: 'Neu' })).toBeInTheDocument();
  });

  it('does not read twice for a change made before it was shown', async () => {
    const { api, fixture } = await setup(() => of([card()]));
    TestBed.inject(TodoLinkedRefresh).touch([{ kind: 'application', targetId: 'a-1' }]);
    fixture.detectChanges();
    const before = api.linked.mock.calls.length;
    const second = TestBed.createComponent(TodoLinkedListComponent);
    second.componentRef.setInput('kind', 'application');
    second.componentRef.setInput('targetId', 'a-1');
    second.detectChanges();
    second.detectChanges();
    expect(api.linked).toHaveBeenCalledTimes(before + 1);
    expect(second.componentInstance.cards().map((c) => c.id)).toEqual(['k-1']);
  });
});

describe('TodoLinkedListComponent actions (specs 000547, 000548)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  async function withActions(writes: boolean, linked: TodoLinkedCard[] = []) {
    const api = {
      linked: jest.fn(() => of(linked)),
      boards: jest.fn(() => of([{ id: 'b-1', name: 'StuPa', kind: 'gremium', gremiumId: 'g-1', canWrite: writes }])),
    };
    const view = await render(TodoLinkedListComponent, {
      inputs: { kind: 'application', targetId: 'a-1', headingId: 'ad-todos', actions: true, gremiumId: 'g-1', linkLabel: 'Lerncafé' },
      providers: [provideRouter([]), { provide: TodosApiService, useValue: api }],
    });
    return { ...view, api, cmp: view.fixture.componentInstance };
  }

  it('shows "Mit To-Do verknüpfen" and "To-Do anlegen" also without a linked card', async () => {
    const { cmp } = await withActions(true);
    expect(screen.getByRole('heading', { name: 'Verknüpft' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mit To-Do verknüpfen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'To-Do anlegen' })).toBeInTheDocument();
    expect(cmp.showActions()).toBe(true);
  });

  it('opens the create dialog of an Antrag with the link and the board of its Gremium', async () => {
    const { cmp, fixture } = await withActions(true);
    screen.getByRole('button', { name: 'To-Do anlegen' }).click();
    fixture.detectChanges();
    expect(cmp.newOpen()).toBe(true);
    expect(cmp.newLinks()).toEqual([{ kind: 'application', targetId: 'a-1', label: 'Antrag · Lerncafé' }]);
    expect(cmp.gremiumId()).toBe('g-1');
    expect(document.querySelector('app-todo-new-dialog')).not.toBeNull();
  });

  it('opens the link dialog without the cards that link the element already', async () => {
    const { cmp, fixture } = await withActions(true, [card()]);
    screen.getByRole('button', { name: 'Mit To-Do verknüpfen' }).click();
    fixture.detectChanges();
    expect(cmp.linkOpen()).toBe(true);
    expect(cmp.linkedIds()).toEqual(['k-1']);
    expect(document.querySelector('app-todo-link-card-dialog')).not.toBeNull();
  });

  /** Spec 000582: the section with actions and no row shows the empty state. */
  it('shows the empty state below the actions when nothing is linked', async () => {
    await withActions(true);
    expect(screen.getByRole('heading', { name: 'Verknüpft' })).toBeInTheDocument();
    expect(screen.getByText('Keine To-Dos verknüpft')).toBeInTheDocument();
  });

  it('hides the actions from a person who writes no board', async () => {
    await withActions(false);
    expect(screen.queryByRole('button', { name: 'To-Do anlegen' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Verknüpft' })).toBeNull();
  });

  it('reads no boards without actions, and shows the empty state it is given', async () => {
    const api = { linked: jest.fn(() => of([])), boards: jest.fn(() => of([])) };
    await render(TodoLinkedListComponent, {
      inputs: { kind: 'meeting', targetId: 'm-1', emptyHeading: 'Keine To-Dos zu dieser Sitzung' },
      providers: [provideRouter([]), { provide: TodosApiService, useValue: api }],
    });
    expect(api.boards).not.toHaveBeenCalled();
    expect(screen.getByText('Keine To-Dos zu dieser Sitzung')).toBeInTheDocument();
  });

  it('reads the list again after a new card', async () => {
    const { cmp, api } = await withActions(true);
    expect(api.linked).toHaveBeenCalledTimes(1);
    cmp.created();
    TestBed.tick();
    expect(api.linked).toHaveBeenCalledTimes(2);
  });
});
