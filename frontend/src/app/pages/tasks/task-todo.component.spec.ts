import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of } from 'rxjs';
import { TodosApiService } from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { MEMBERS, detail } from '../../../testing/todo-fixtures';
import { provideFakeTodoLive } from '../../../testing/todo-live';
import { TaskTodoComponent } from './task-todo.component';
import { TasksComponent } from './tasks.component';

@Component({ standalone: true, template: '' })
class ListStub {}

async function start(withPage: boolean, split = true) {
  const page = { loadTodos: jest.fn(), split: () => split };
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([
        { path: 'tasks', component: ListStub },
        { path: 'tasks/todo/:cardId', component: TaskTodoComponent },
      ]),
      { provide: TodosApiService, useValue: { card: jest.fn(() => of(detail())), members: jest.fn(() => of(MEMBERS)) } },
      provideFakeTodoLive(),
      { provide: ToastService, useValue: { success: jest.fn(), error: jest.fn() } },
      ...(withPage ? [{ provide: TasksComponent, useValue: page }] : []),
    ],
  });
  const harness = await RouterTestingHarness.create();
  const cmp = await harness.navigateByUrl('/tasks/todo/k-1', TaskTodoComponent);
  harness.detectChanges();
  return { harness, cmp, page, router: TestBed.inject(Router) };
}

describe('TaskTodoComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the card of the route in pane mode and refreshes the group on a change', async () => {
    const { cmp, page, harness } = await start(true);
    expect(cmp.cardId()).toBe('k-1');
    const detailEl = harness.routeNativeElement?.querySelector('app-todo-card-detail');
    expect(detailEl).toHaveClass('cd--pane');
    cmp.refresh();
    expect(page.loadTodos).toHaveBeenCalledTimes(1);
  });

  it('is a sheet side by side and lies on the page one pane at a time', async () => {
    const wide = await start(true);
    expect(wide.harness.routeNativeElement).toHaveClass('tt--split');
    // The card detail gets the split: only on the sheet its bar bleeds into the padding.
    expect(wide.harness.routeNativeElement?.querySelector('app-sheet-bar')).toHaveClass('sheet-bar--bleed');
    TestBed.resetTestingModule();
    const narrow = await start(true, false);
    expect(narrow.harness.routeNativeElement).not.toHaveClass('tt--split');
    expect(narrow.harness.routeNativeElement?.querySelector('app-sheet-bar')).not.toHaveClass('sheet-bar--bleed');
  });

  it('closes to the list and refreshes after an archive', async () => {
    const { cmp, page, router, harness } = await start(true);
    cmp.onArchived();
    await harness.fixture.whenStable();
    expect(page.loadTodos).toHaveBeenCalled();
    expect(router.url).toBe('/tasks');
  });

  it('works without the page around it', async () => {
    const { cmp, router, harness } = await start(false);
    expect(cmp.split()).toBe(false);
    cmp.refresh();
    cmp.close();
    await harness.fixture.whenStable();
    expect(router.url).toBe('/tasks');
  });
});
