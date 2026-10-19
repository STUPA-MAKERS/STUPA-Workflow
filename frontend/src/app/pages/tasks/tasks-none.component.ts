import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DetailNoneComponent, type DetailNoneState } from '@shared/ui/detail-none/detail-none.component';
import { TasksComponent } from './tasks.component';

/**
 * The detail pane of `/tasks` before a task is open. Only the side-by-side layout shows
 * it; one pane at a time, the list fills the screen.
 *
 * Without open tasks it shows the empty state of the page ("Keine offenen Aufgaben"),
 * else a hint that no task is open. While the list loads or after an error it shows
 * only the empty sheet: the list pane says what happens.
 */
@Component({
  selector: 'app-tasks-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DetailNoneComponent],
  templateUrl: './tasks-none.component.html',
  styleUrl: '../../shared/ui/detail-none/detail-none-host.scss',
})
export class TasksNoneComponent {
  private readonly page = inject(TasksComponent, { optional: true });

  protected readonly state = computed<DetailNoneState>(() => {
    const page = this.page;
    if (!page || page.loading() || page.error()) return 'busy';
    return page.tasks().length || page.todos().length ? 'pick' : 'empty';
  });
}
