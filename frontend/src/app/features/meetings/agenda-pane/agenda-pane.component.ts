import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  model,
  output,
  signal,
} from '@angular/core';
import type { AgendaItem, Meeting, Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import {
  TodosApiService,
  type LinkEnd,
  type TodoCardDetail,
  type TodoLinkTarget,
} from '@core/api/todos.service';
import { BodyPortalDirective } from '@shared/ui/body-portal/body-portal.directive';
import { ToastService } from '@stupa-makers/ui-kit';
import {
  AgendaPaneViewComponent,
  type AgendaLinkEnd,
  type AgendaMove,
  type AgendaTodoLink,
} from '@stupa-makers/ui-kit/views/meeting';
import {
  TodoNewDialogComponent,
  type NewTodoLink,
} from '../../todos/new-dialog/todo-new-dialog.component';
import { TodoLinkPickerComponent } from '../../todos/link-picker/todo-link-picker.component';
import { TodoLinkedRefresh } from '../../todos/linked-list/todo-linked-refresh';

export { canChangeAgenda, canEditTop, type AgendaMove } from '@stupa-makers/ui-kit/views/meeting';

/**
 * The Tagesordnung of a meeting: the kit view `app-agenda-pane-view` (S/framework/views/002275)
 * with the to-do parts of the app. The view emits "To-Do anlegen" and "Verknüpfen"; this
 * component checks `todo.write` and opens the to-do dialog and the link picker.
 */
@Component({
  selector: 'app-agenda-pane',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    AgendaPaneViewComponent,
    TodoNewDialogComponent,
    TodoLinkPickerComponent,
    BodyPortalDirective,
  ],
  templateUrl: './agenda-pane.component.html',
  styleUrl: './agenda-pane.component.scss',
})
export class AgendaPaneComponent {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly linkedRefresh = inject(TodoLinkedRefresh);
  private readonly todosApi = inject(TodosApiService);
  private readonly toast = inject(ToastService);

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  readonly selectedId = input<Uuid | null>(null);
  readonly locked = input(false);
  readonly savingAgenda = input(false);
  readonly renamingTopId = input<Uuid | null>(null);
  readonly renameDraft = model<string>('');
  readonly inSheet = input(false);
  readonly canTick = input(false);

  readonly pick = output<Uuid>();
  readonly add = output<void>();
  readonly startRename = output<AgendaItem>();
  readonly cancelRename = output<void>();
  readonly renameTop = output<AgendaItem>();
  readonly setNonPublic = output<{ item: AgendaItem; nonPublic: boolean }>();
  readonly setDone = output<{ item: AgendaItem; done: boolean }>();
  readonly setDuration = output<{ item: AgendaItem; minutes: number | null }>();
  readonly move = output<AgendaMove>();
  readonly remove = output<Uuid>();

  /** The person may write To-Dos on the board of the gremium of the meeting. */
  protected readonly canTodo = computed(() => {
    const gremiumId = this.meeting().gremiumId;
    return !!gremiumId && this.auth.canInGremium(gremiumId, 'todo.write');
  });

  protected readonly todoOpen = signal(false);
  protected readonly todoLinks = signal<readonly NewTodoLink[]>([]);
  /** "Verknüpfen" from the menu of an item: the item as a link end (spec 001408). */
  protected readonly linkEnd = signal<LinkEnd | null>(null);
  protected readonly linkOpen = signal(false);

  /** "To-Do anlegen": the new card links the TOP and, for an application item, the application. */
  protected openTodo(links: readonly AgendaTodoLink[]): void {
    this.todoLinks.set(links);
    this.todoOpen.set(true);
  }

  /** "Verknüpfen": the one picker over every kind (spec 001408). */
  protected openLink(end: AgendaLinkEnd): void {
    this.linkEnd.set(end);
    this.linkOpen.set(true);
  }

  /** A pick links the item; the "Verknüpft" lists of both ends read again. */
  protected linkPicked(hit: TodoLinkTarget): void {
    const end = this.linkEnd();
    if (!end) return;
    this.todosApi.link(end, { kind: hit.kind, id: hit.targetId }).subscribe({
      next: () => {
        this.linkOpen.set(false);
        this.linkedRefresh.touch([
          { kind: end.kind, targetId: end.id },
          { kind: hit.kind, targetId: hit.targetId },
        ]);
      },
      error: () => this.toast.show(this.i18n.translate('links.error.add'), 'error'),
    });
  }

  /** The new card shows at once in the "To-Dos" of the TOP and of its application. */
  protected onTodoCreated(card: TodoCardDetail): void {
    this.linkedRefresh.touch(card.links);
  }
}
