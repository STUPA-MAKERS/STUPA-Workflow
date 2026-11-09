import { CdkDrag, CdkDragPlaceholder, CdkDropList, type CdkDragDrop } from '@angular/cdk/drag-drop';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  ElementRef,
  inject,
  input,
  model,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { AgendaItem, Meeting, MeetingVote, Uuid } from '@core/api/models';
import { TodosApiService, type TodoCardDetail } from '@core/api/todos.service';
import {
  BadgeComponent,
  ConfirmDialogComponent,
  EmptyStateComponent,
  IconComponent,
  ListItemComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
} from '@stupa-makers/ui-kit';
import {
  TodoNewDialogComponent,
  type NewTodoLink,
} from '../../todos/new-dialog/todo-new-dialog.component';
import { BodyPortalDirective } from '@shared/ui/body-portal/body-portal.directive';
import { TodoLinkCardDialogComponent } from '../../todos/link-card-dialog/todo-link-card-dialog.component';
import { TodoLinkedRefresh } from '../../todos/linked-list/todo-linked-refresh';
import { TopBadgeComponent } from '../top-badge/top-badge.component';

/** The ids of the row menu items of an agenda item. */
type AgendaAction = 'done' | 'rename' | 'up' | 'down' | 'nonPublic' | 'remove' | 'todo' | 'link';

/**
 * Add, rename, reorder and remove agenda items: the meeting lead with write access, while
 * the meeting is planned or live and the protocol is not locked.
 */
export function canChangeAgenda(meeting: Meeting, locked: boolean): boolean {
  return meeting.canWrite && !locked && meeting.status !== 'closed';
}

/** A move of an agenda item from one position to another (0-based). */
export interface AgendaMove {
  readonly from: number;
  readonly to: number;
}

/**
 * The agenda of the session page ("Tagesordnung").
 *
 * A row shows the number, the title, the kind ("Antrag" or "Freitext"), an open vote
 * and the tag NÖ. The number is filled for the item that the room handles now, and a
 * ticked item shows a check ("TOP abhaken"). Only a stored tick marks an item as done,
 * never its place before "now". A click opens the item in the sheet.
 *
 * A writer of the minutes (`canTick`) ticks an item and removes the tick with the first
 * entry of the row menu.
 *
 * The row menu holds every agenda change (N21): rename (free text only), move up and
 * down, the non-public switch and the remove. Drag and drop also reorders: the
 * list is a drop list of `@angular/cdk/drag-drop`, with the lifted row and the dashed
 * drop box of the to-do board. A touch starts the drag only after a long press, so a
 * swipe still scrolls the agenda; the menu moves without a pointer. Only a
 * planned or live meeting changes its agenda; a closed meeting keeps the
 * non-public switch while the protocol is a draft. An item with an open or
 * closed vote stays on the agenda, so its remove is disabled with the reason. The remove
 * asks first ("TOP entfernen?"), because the text of the item goes with it.
 *
 * "To-Do anlegen" is in the menu of every item for a person with `todo.write`
 * in the gremium of the meeting, also on a closed meeting: it opens "Neues To-Do" on the
 * gremium board, linked to the TOP and to its application.
 *
 * Both dialogs live in the body, because the scroll fade of the agenda would clip them.
 */
@Component({
  selector: 'app-agenda-pane',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TopBadgeComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    CdkDrag,
    CdkDragPlaceholder,
    CdkDropList,
    FormsModule,
    TranslatePipe,
    BadgeComponent,
    IconComponent,
    ListItemComponent,
    RowMenuComponent,
    TodoNewDialogComponent,
    TodoLinkCardDialogComponent,
    BodyPortalDirective,
  ],
  templateUrl: './agenda-pane.component.html',
  styleUrl: './agenda-pane.component.scss',
})
export class AgendaPaneComponent {
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);
  private readonly linkedRefresh = inject(TodoLinkedRefresh);
  private readonly todosApi = inject(TodosApiService);

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  /** The item open in the sheet. */
  readonly selectedId = input<Uuid | null>(null);
  /** The protocol is final or renders: nothing on the agenda changes. */
  readonly locked = input(false);
  readonly savingAgenda = input(false);
  readonly renamingTopId = input<Uuid | null>(null);
  readonly renameDraft = model<string>('');
  private readonly renameInput = viewChild<ElementRef<HTMLInputElement>>('renameInput');
  /**
   * The rename field takes the focus when it opens. The `autofocus` attribute works only on
   * page load, and the template lint refuses it (§ NF/accessibility/conformance/000492).
   */
  private readonly focusRename = effect(() => this.renameInput()?.nativeElement.focus());
  /**
   * Inside the agenda sheet, whose header names the agenda and holds the add: the heading
   * is for screen readers only, and the pane shows no add of its own.
   */
  readonly inSheet = input(false);
  /** The viewer may tick an item: the gate of the item text (`editable` of the page). */
  readonly canTick = input(false);

  /**
   * Open an item in the sheet. No output of the pane has the name of a DOM event: a
   * native event that bubbles out of the pane (`select` from the rename field, `drop`
   * from a row) would else reach the same binding with an Event in place of the value.
   */
  readonly pick = output<Uuid>();
  /** Open "TOP hinzufügen". */
  readonly add = output<void>();
  readonly startRename = output<AgendaItem>();
  readonly cancelRename = output<void>();
  readonly renameTop = output<AgendaItem>();
  readonly setNonPublic = output<{ item: AgendaItem; nonPublic: boolean }>();
  readonly setDone = output<{ item: AgendaItem; done: boolean }>();
  readonly move = output<AgendaMove>();
  readonly remove = output<Uuid>();

  /** A touch lifts a row after this long press; a mouse lifts it at once. */
  protected readonly dragDelay = { touch: 400, mouse: 0 };

  /** "Neues To-Do" from the menu of an item: open, and the links it starts with. */
  protected readonly todoOpen = signal(false);
  protected readonly todoLinks = signal<readonly NewTodoLink[]>([]);
  /** "To-Do verknüpfen" from the menu of an item: the item, and the cards that link it already. */
  protected readonly linkItem = signal<AgendaItem | null>(null);
  protected readonly linkOpen = signal(false);
  protected readonly linkExclude = signal<readonly Uuid[]>([]);
  /** The item that "TOP entfernen?" asks about. */
  protected readonly removing = signal<AgendaItem | null>(null);
  /** The person may write To-Dos on the board of the gremium of the meeting. */
  protected readonly canCreateTodo = computed(() => {
    const gremiumId = this.meeting().gremiumId;
    return !!gremiumId && this.auth.canInGremium(gremiumId, 'todo.write');
  });

  /** Set the non-public flag: the meeting lead with write access, protocol not locked. */
  protected readonly canEditAgenda = computed(() => this.meeting().canWrite && !this.locked());
  /** Add, rename, reorder and remove: also only while the meeting is planned or live. */
  protected readonly canChangeAgenda = computed(() =>
    canChangeAgenda(this.meeting(), this.locked()),
  );

  /**
   * The id of the item that the room handles now. Only a live or closed meeting has
   * one: a planned meeting shows no "now" and no handled item, also when it holds a
   * stale id.
   */
  private readonly nowId = computed(() => {
    const m = this.meeting();
    return m.status === 'planned' ? null : m.currentAgendaItemId;
  });
  /** A row lifts while the agenda may change, is not saving and the row is not in rename. */
  protected canDrag(item: AgendaItem): boolean {
    return this.canChangeAgenda() && !this.savingAgenda() && this.renamingTopId() !== item.id;
  }

  /** A row dropped at another place of the agenda. */
  protected dropped(event: Pick<CdkDragDrop<unknown>, 'previousIndex' | 'currentIndex'>): void {
    if (event.previousIndex === event.currentIndex || this.savingAgenda()) return;
    this.move.emit({ from: event.previousIndex, to: event.currentIndex });
  }

  protected title(item: AgendaItem): string {
    return item.title || this.i18n.translate('meetings.agenda.untitled');
  }

  /**
   * "Antrag · Abstimmung offen", "To-Do". The number badge already names the TOP, and a
   * free-text item needs no kind: it gets a sub line only for an open vote, else none.
   */
  protected sub(item: AgendaItem): string | null {
    const kind = item.applicationId
      ? [this.i18n.translate('meetings.agenda.kindApplication')]
      : item.todoId
        ? [this.i18n.translate('meetings.agenda.kindTodo')]
        : [];
    const open = this.votesFor(item.id).some((v) => v.status === 'open')
      ? [this.i18n.translate('meetings.agenda.voteOpen')]
      : [];
    const parts = [...kind, ...open];
    return parts.length ? parts.join(' · ') : null;
  }

  /** The item the room handles now. */
  protected isNow(item: AgendaItem): boolean {
    return this.nowId() !== null && item.id === this.nowId();
  }

  /** A ticked item counts as done ("TOP abhaken"). */
  protected isDone(item: AgendaItem): boolean {
    return !!item.doneAt;
  }

  protected votesFor(itemId: Uuid): MeetingVote[] {
    return this.meeting().votes.filter((v) => v.agendaItemId === itemId);
  }

  /**
   * The reason why the item cannot be removed, or `null`.
   *
   * An open or closed vote keeps the item (409 `agenda_item_has_vote`). A draft or
   * cancelled vote goes with the item, but only for a person with the vote right
   * (`canManageVotes`); the agenda right alone gets 403.
   */
  protected removeBlockedReason(itemId: Uuid): TranslationKey | null {
    const votes = this.votesFor(itemId);
    if (votes.some((v) => v.status === 'open' || v.status === 'closed')) {
      return 'meetings.agenda.removeBlocked';
    }
    if (!this.meeting().canManageVotes && votes.length > 0) {
      return 'meetings.agenda.removeNeedsVoteRight';
    }
    return null;
  }

  /** The row menus in agenda order, built once per change of their inputs. */
  protected readonly menus = computed(() => this.agenda().map((item, i) => this.menu(item, i)));

  /** The row menu of an item. Empty when nothing on the agenda may change. */
  private menu(item: AgendaItem, index: number): readonly RowMenuSection[] {
    const todo: RowMenuItem = { id: 'todo', label: this.i18n.translate('meetings.agenda.todo'), icon: 'circleok' };
    const link: RowMenuItem = { id: 'link', label: this.i18n.translate('meetings.agenda.link'), icon: 'link' };
    const key: TranslationKey = item.doneAt ? 'meetings.agenda.markOpen' : 'meetings.agenda.markDone';
    const done: RowMenuItem = { id: 'done', label: this.i18n.translate(key), icon: 'check' };
    return [
      ...(this.canTick() ? [{ items: [done] }] : []),
      ...(this.canCreateTodo() ? [{ items: [todo, link] }] : []),
      ...this.agendaMenu(item, index),
    ];
  }

  private agendaMenu(item: AgendaItem, index: number): readonly RowMenuSection[] {
    if (!this.canEditAgenda()) return [];
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const nonPublic: RowMenuItem = {
      id: 'nonPublic',
      label: t('meetings.agenda.nonPublicLabel'),
      icon: 'lock',
      checked: item.nonPublic === true,
    };
    if (!this.canChangeAgenda()) return [{ items: [nonPublic] }];

    const up: RowMenuItem = { id: 'up', label: t('meetings.agenda.moveUp'), icon: 'up' };
    const down: RowMenuItem = { id: 'down', label: t('meetings.agenda.moveDown'), icon: 'down' };
    const edit: readonly RowMenuItem[] = [
      { id: 'rename', label: t('meetings.agenda.rename'), icon: 'edit' },
      ...(index > 0 ? [up] : []),
      ...(index < this.agenda().length - 1 ? [down] : []),
    ];
    const blocked = this.removeBlockedReason(item.id);
    return [
      { items: edit },
      { items: [nonPublic] },
      {
        items: [
          {
            id: 'remove',
            label: t('meetings.agenda.remove'),
            icon: 'trash',
            danger: true,
            disabledReason: blocked ? t(blocked) : null,
          },
        ],
      },
    ];
  }

  protected menuLabel(item: AgendaItem): string {
    return this.i18n.translate('meetings.agenda.rowMenu', { title: this.title(item) });
  }

  protected onAction(item: AgendaItem, index: number, action: RowMenuItem): void {
    const id = action.id as AgendaAction;
    if (id !== 'todo' && id !== 'link' && this.savingAgenda()) return;
    switch (id) {
      case 'todo':
        this.openTodo(item, index);
        break;
      case 'link':
        this.openLink(item);
        break;
      case 'done':
        this.setDone.emit({ item, done: !item.doneAt });
        break;
      case 'rename':
        this.startRename.emit(item);
        break;
      case 'up':
        this.move.emit({ from: index, to: index - 1 });
        break;
      case 'down':
        this.move.emit({ from: index, to: index + 1 });
        break;
      case 'nonPublic':
        this.setNonPublic.emit({ item, nonPublic: !item.nonPublic });
        break;
      case 'remove':
        this.removing.set(item);
        break;
    }
  }

  /** "Entfernen" in "TOP entfernen?": the page removes the item. */
  protected confirmRemove(): void {
    const item = this.removing();
    this.removing.set(null);
    if (item) this.remove.emit(item.id);
  }

  /**
   * "Neues To-Do" linked to the TOP and, for an application item, to the application.
   * The chips read "Antrag · <title>" and "<meeting> · TOP n".
   */
  private openTodo(item: AgendaItem, index: number): void {
    const title = this.title(item);
    const top = this.i18n.translate('todos.link.top', { n: index + 1 });
    const application: readonly NewTodoLink[] = item.applicationId
      ? [
          {
            kind: 'application',
            targetId: item.applicationId,
            label: `${this.i18n.translate('todos.linkKind.application')} · ${item.applicationTitle || title}`,
          },
        ]
      : [];
    const agendaItem: NewTodoLink = {
      kind: 'agenda_item',
      targetId: item.id,
      label: `${this.meeting().title} · ${top}`,
    };
    this.todoLinks.set([...application, agendaItem]);
    this.todoOpen.set(true);
  }

  /**
   * "To-Do verknüpfen": the search over the cards that the person writes (spec 000548). The
   * cards that link the item already leave the list once the server answers.
   */
  private openLink(item: AgendaItem): void {
    this.linkExclude.set([]);
    this.linkItem.set(item);
    this.linkOpen.set(true);
    this.todosApi.linked('agenda_item', item.id).subscribe({
      next: (cards) => {
        if (this.linkItem()?.id === item.id) this.linkExclude.set(cards.map((c) => c.id));
      },
      error: () => undefined,
    });
  }

  /** The new card shows at once in the "To-Dos" of the TOP and of its application. */
  protected onTodoCreated(card: TodoCardDetail): void {
    this.linkedRefresh.touch(card.links);
  }
}
