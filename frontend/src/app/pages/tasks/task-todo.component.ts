import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';
import { TodoCardDetailComponent } from '../../features/todos/card-detail/todo-card-detail.component';
import { TasksComponent } from './tasks.component';

/**
 * The right pane of `/tasks/todo/:cardId`: the card detail of the boards, with
 * "Im Board öffnen" (on a phone in its ⋮ menu). Side by side it is a sheet; one pane at a
 * time it lies on the page. A change or an archive reads the group "To-Dos" of the page again; an
 * archived card closes the pane.
 */
@Component({
  selector: 'app-task-todo',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TodoCardDetailComponent],
  host: { '[class.tt--split]': 'split()' },
  templateUrl: './task-todo.component.html',
  styleUrl: './task-todo.component.scss',
})
export class TaskTodoComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly page = inject(TasksComponent, { optional: true });

  /** Side by side the detail is a sheet; one pane at a time it lies on the page. */
  readonly split = computed(() => this.page?.split() ?? false);

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
