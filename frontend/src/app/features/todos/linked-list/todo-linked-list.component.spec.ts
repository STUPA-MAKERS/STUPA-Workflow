import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { TodosApiService, type TodoLinkedCard } from '@core/api/todos.service';
import { TodoLinkedListComponent } from './todo-linked-list.component';

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
    ...over,
  };
}

async function setup(answer: () => Observable<TodoLinkedCard[]>) {
  const api = { linked: jest.fn(answer) };
  const view = await render(TodoLinkedListComponent, {
    inputs: { kind: 'application', targetId: 'a-1', headingId: 'ad-todos' },
    providers: [provideRouter([]), { provide: TodosApiService, useValue: api }],
  });
  return { ...view, api, cmp: view.fixture.componentInstance };
}

describe('TodoLinkedListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the linked cards with board, column, due date and people, each a link to its card', async () => {
    const { api, cmp } = await setup(() => of([card(), card({ id: 'k-2', title: 'Erledigt', isDone: true, dueDate: null, assignees: [] })]));
    expect(api.linked).toHaveBeenCalledWith('application', 'a-1');
    expect(screen.getByRole('heading', { name: 'To-Dos' })).toHaveAttribute('id', 'ad-todos');
    expect(screen.getByRole('link', { name: 'Raum buchen' })).toHaveAttribute('href', '/todos/b-1?card=k-1');
    expect(screen.getByText('Studierendenparlament · In Arbeit · fällig 17.10.')).toBeInTheDocument();
    expect(screen.getByText('Studierendenparlament · In Arbeit')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Erledigt' }).closest('li')).toHaveClass('tl__row--done');
    expect(cmp.names(card())).toEqual(['Mara Keller', 'Gelöschte Person']);
    expect(cmp.ids(card())).toEqual(['p-1', null]);
    expect(document.querySelectorAll('app-avatar-stack')).toHaveLength(1);
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
});
