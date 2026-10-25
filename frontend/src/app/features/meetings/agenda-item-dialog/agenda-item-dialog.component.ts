import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  ElementRef,
  inject,
  Injector,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { switchMap } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AgendaItem, AssignableApplication, Meeting, Uuid } from '@core/api/models';
import { TodosApiService, type TodoBoard } from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  DialogComponent,
  EmptyStateComponent,
  IconComponent,
  InputComponent,
  ScrollFadeDirective,
  SearchPillComponent,
  SegmentedComponent,
  type SegmentedOption,
  SkeletonComponent,
  SwitchComponent,
  ToastService,
  TruncatedDirective,
} from '@stupa-makers/ui-kit';
import { resolveI18n } from '@shared/forms/i18n-text';
import { problemDetail } from '@core/api/problem';
import { cardsOf, sortedColumns } from '../../todos/todos.util';
import { isoDay, shortDay } from '@shared/date-format';

/** What the new agenda item is: an application of the Gremium, a to-do, or a free text. */
export type AgendaItemKind = 'application' | 'todo' | 'freetext';

/**
 * The empty list of the area: `none` when the kind has nothing to offer at all, `noMatch`
 * when the search hides every row.
 */
export type AgendaEmptyCase = 'none' | 'noMatch';

/** An open card of the gremium board, as a row of the to-do list. */
export interface AgendaTodoOption {
  id: Uuid;
  title: string;
  /** "In Arbeit · fällig 03.11." */
  sub: string;
}

/**
 * "TOP hinzufügen" (frame 6): put an application or a to-do on the agenda, or add a
 * free-text item.
 *
 * The application list is `GET …/agenda/assignable`: the applications of the meeting
 * Gremium in a vote state that are not on an agenda yet. The to-do list is the gremium
 * board of the meeting (`GET /todos/boards?gremiumId=` and the board read): its cards
 * outside the done column that are not on this agenda yet. It loads on the first switch
 * to "To-Do", and the kind shows only with `todo.write` in the gremium. The server makes
 * the item from the card title and links the card to the item. The new item goes to the
 * end of the agenda. "Nicht öffentlich" marks it at once, so the public protocol leaves
 * it out.
 */
@Component({
  selector: 'app-agenda-item-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TruncatedDirective,
    ScrollFadeDirective,
    FormsModule,
    NgTemplateOutlet,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    IconComponent,
    InputComponent,
    SegmentedComponent,
    SwitchComponent,
    SearchPillComponent,
    SkeletonComponent,
    EmptyStateComponent,
  ],
  templateUrl: './agenda-item-dialog.component.html',
  styleUrl: './agenda-item-dialog.component.scss',
})
export class AgendaItemDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly todosApi = inject(TodosApiService);
  private readonly auth = inject(AuthService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  readonly open = input(false);
  readonly meeting = input.required<Meeting>();
  /** The agenda now: a card that is on it already is not offered again. */
  readonly agenda = input<readonly AgendaItem[]>([]);
  readonly closed = output<void>();
  /** The server added the item. Carries the new agenda. */
  readonly added = output<AgendaItem[]>();

  readonly kind = signal<AgendaItemKind>('freetext');
  readonly assignable = signal<AssignableApplication[]>([]);
  readonly loading = signal(false);
  readonly todosLoading = signal(false);
  readonly query = signal('');
  readonly pick = signal<Uuid | null>(null);
  readonly freetext = signal('');
  readonly nonPublic = signal(false);
  readonly saving = signal(false);

  /** The open cards of the gremium board; `null` until the first switch to "To-Do". */
  readonly todos = signal<AgendaTodoOption[] | null>(null);
  readonly todoQuery = signal('');
  readonly todoPick = signal<Uuid | null>(null);

  /** The person may read and write the gremium board of the meeting. */
  readonly canTodo = computed(() => {
    const gremiumId = this.meeting().gremiumId;
    return !!gremiumId && this.auth.canInGremium(gremiumId, 'todo.write');
  });

  readonly kindOptions = computed<SegmentedOption[]>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    return [
      { value: 'application', label: t('meetings.agenda.kindApplication') },
      ...(this.canTodo() ? [{ value: 'todo', label: t('meetings.agenda.kindTodo') }] : []),
      { value: 'freetext', label: t('meetings.agenda.kindFreetext') },
    ];
  });

  /** The cards whose title holds the search text, without the cards on the agenda. */
  readonly shownTodos = computed<AgendaTodoOption[]>(() => {
    const onAgenda = new Set(this.agenda().map((a) => a.todoId));
    const needle = this.todoQuery().trim().toLocaleLowerCase();
    return (this.todos() ?? []).filter(
      (c) => !onAgenda.has(c.id) && (!needle || c.title.toLocaleLowerCase().includes(needle)),
    );
  });

  /** The picked card, but only while the list shows it (see `visiblePick`). */
  readonly visibleTodoPick = computed<Uuid | null>(() => {
    const pick = this.todoPick();
    return pick !== null && this.shownTodos().some((c) => c.id === pick) ? pick : null;
  });

  /** The applications whose title holds the search text. */
  readonly shown = computed<AssignableApplication[]>(() => {
    const needle = this.query().trim().toLocaleLowerCase();
    const rows = this.assignable();
    return needle ? rows.filter((a) => (a.title ?? '').toLocaleLowerCase().includes(needle)) : rows;
  });

  /**
   * The picked application, but only while the list shows it. A search that filters
   * the pick out of the list leaves no row checked, so the submit must not send it.
   */
  readonly visiblePick = computed<Uuid | null>(() => {
    const pick = this.pick();
    return pick !== null && this.shown().some((a) => a.applicationId === pick) ? pick : null;
  });

  /** The search text of the current kind, trimmed. */
  readonly activeQuery = computed(() =>
    (this.kind() === 'todo' ? this.todoQuery() : this.query()).trim(),
  );

  /**
   * Why the list of the current kind is empty. A kind without any row is `none` also
   * while a search text is set, because clearing the search would show nothing either.
   */
  readonly emptyCase = computed<AgendaEmptyCase>(() => {
    const all = this.kind() === 'todo' ? (this.todos() ?? []).length : this.assignable().length;
    return all && this.activeQuery() ? 'noMatch' : 'none';
  });

  readonly valid = computed(() => {
    switch (this.kind()) {
      case 'application':
        return this.visiblePick() !== null;
      case 'todo':
        return this.visibleTodoPick() !== null;
      default:
        return !!this.freetext().trim();
    }
  });

  constructor() {
    effect(() => {
      if (this.open()) untracked(() => this.reset());
    });
  }

  private reset(): void {
    this.kind.set('freetext');
    this.query.set('');
    this.pick.set(null);
    this.freetext.set('');
    this.nonPublic.set(false);
    this.saving.set(false);
    this.todos.set(null);
    this.todoQuery.set('');
    this.todoPick.set(null);
    this.assignable.set([]);
    this.loading.set(true);
    this.api.listAssignableApplications(this.meeting().id).subscribe({
      next: (rows) => {
        this.loading.set(false);
        this.assignable.set(rows);
      },
      error: () => {
        this.loading.set(false);
        this.assignable.set([]);
      },
    });
  }

  setKind(value: string | null): void {
    if (value === 'application' || value === 'freetext') this.kind.set(value);
    if (value === 'todo' && this.canTodo()) {
      this.kind.set('todo');
      if (this.todos() === null) this.loadTodos();
    }
  }

  /**
   * The open cards of the gremium board, by column and then by rank. No gremium board,
   * or a failed read, gives an empty list.
   */
  private loadTodos(): void {
    const gremiumId = this.meeting().gremiumId;
    this.todos.set([]);
    this.todosLoading.set(true);
    this.todosApi
      .boards(gremiumId)
      .pipe(
        switchMap((boards) => {
          const own = boards.find((b) => b.kind === 'gremium' && b.gremiumId === gremiumId);
          if (!own) throw new Error('no gremium board');
          return this.todosApi.board(own.id);
        }),
      )
      .subscribe({
        next: (board) => {
          this.todosLoading.set(false);
          this.todos.set(this.openCards(board));
        },
        error: () => this.todosLoading.set(false),
      });
  }

  private openCards(board: TodoBoard): AgendaTodoOption[] {
    const today = isoDay(new Date());
    const locale = this.i18n.formatLocale();
    return sortedColumns(board.columns)
      .filter((col) => !col.isDone)
      .flatMap((col) =>
        cardsOf(board, col.id).map((card) => ({
          id: card.id,
          title: card.title,
          sub: card.dueDate
            ? `${col.name} · ${this.i18n.translate('meetings.agenda.todoDue', { date: shortDay(card.dueDate, locale, today) })}`
            : col.name,
        })),
      );
  }

  /**
   * The flow state of an assignable application, as the muted second line of its row.
   * The board shows it in the accent, but the accent means "done" or "live" (see
   * `status-kind.util.ts`), and an application that waits for its agenda item is
   * neither.
   */
  stateOf(a: AssignableApplication): string {
    return resolveI18n(a.stateLabel, this.i18n.locale());
  }

  /**
   * A click on the "Nicht öffentlich" row outside its label and its switch toggles the
   * switch, so the whole row is the target. The label and the switch toggle it
   * themselves, so a click on them is left alone.
   */
  toggleFromRow(event: MouseEvent): void {
    if ((event.target as HTMLElement).closest('label, button')) return;
    this.nonPublic.update((on) => !on);
  }

  /** "Filter zurücksetzen": clears the search of the current kind. */
  clearSearch(): void {
    if (this.kind() === 'todo') this.todoQuery.set('');
    else this.query.set('');
    this.focusAfterRender('.aid__area input');
  }

  /**
   * "Als Freitext anlegen": switches to a free-text item. A search text becomes the
   * title, so nothing that was typed is lost.
   */
  asFreetext(): void {
    const q = this.activeQuery();
    this.kind.set('freetext');
    if (q) this.freetext.set(q);
    this.focusAfterRender('#aid-title');
  }

  /** The button that had the focus is gone after the change, so the focus moves on. */
  private focusAfterRender(selector: string): void {
    afterNextRender(
      () => this.host.nativeElement.querySelector<HTMLElement>(selector)?.focus(),
      { injector: this.injector },
    );
  }

  cancel(): void {
    this.closed.emit();
  }

  submit(): void {
    if (!this.valid() || this.saving()) return;
    const meetingId = this.meeting().id;
    const pick = this.visiblePick();
    const todo = this.visibleTodoPick();
    const kind = this.kind();
    const req =
      kind === 'application' && pick !== null
        ? this.api.addAgendaItem(meetingId, pick, this.nonPublic())
        : kind === 'todo' && todo !== null
          ? this.api.addAgendaTodo(meetingId, todo, this.nonPublic())
          : this.api.addAgendaFreetext(meetingId, this.freetext().trim(), this.nonPublic());
    this.saving.set(true);
    req.subscribe({
      next: (rows) => {
        this.saving.set(false);
        this.added.emit(rows);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        const detail = problemDetail(err);
        const base = this.i18n.translate('meetings.toast.actionFailed');
        this.toast.error(detail ? `${base}: ${detail}` : base);
      },
    });
  }
}
