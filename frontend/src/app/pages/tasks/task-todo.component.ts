import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';
import { TodoCardDetailComponent } from '../../features/todos/card-detail/todo-card-detail.component';
import { TasksComponent } from './tasks.component';

/**
 * The right pane of `/tasks/todo/:cardId`: the card detail of the boards (frame 10), with
 * "Im Board öffnen". A change or an archive reads the group "To-Dos" of the page again; an
 * archived card closes the pane.
 */
@Component({
  selector: 'app-task-todo',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TodoCardDetailComponent],
  templateUrl: './task-todo.component.html',
  styleUrl: './task-todo.component.scss',
})
export class TaskTodoComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly page = inject(TasksComponent, { optional: true });

  readonly cardId = toSignal(this.route.paramMap.pipe(map((p) => p.get('cardId'))), {
    initialValue: this.route.snapshot.paramMap.get('cardId'),
  });

  close(): void {
    void this.router.navigate(['/tasks']);
  }

  refresh(): void {
    this.page?.loadTodos();
  }

  onArchived(): void {
    this.refresh();
    this.close();
  }
}
