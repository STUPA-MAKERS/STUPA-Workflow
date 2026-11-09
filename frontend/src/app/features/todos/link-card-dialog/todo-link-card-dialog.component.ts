import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
} from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { catchError, combineLatest, debounceTime, map, of, switchMap, type Observable } from 'rxjs';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoLinkKind, type TodoLinkTarget } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { TodoLinkedRefresh } from '../linked-list/todo-linked-refresh';
import { type PickRow, TodoPickDialogComponent } from '../pick-dialog/todo-pick-dialog.component';

/** The fewest characters that search the server; a shorter query lists the own cards. */
const MIN_QUERY = 2;

/**
 * "Mit To-Do verknüpfen" of the section "Verknüpft" (spec 000548): pick a card that the
 * person writes, and the card gets a link to the element. Without a query the dialog
 * lists the cards assigned to the person; a query searches every readable card. A card
 * on a board the person only reads, and a card that links the element already, does not
 * show.
 */
@Component({
  selector: 'app-todo-link-card-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TodoPickDialogComponent],
  templateUrl: './todo-link-card-dialog.component.html',
})
export class TodoLinkCardDialogComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly refresh = inject(TodoLinkedRefresh);

  readonly open = model(false);
  readonly kind = input.required<Exclude<TodoLinkKind, 'todo'>>();
  readonly targetId = input.required<Uuid>();
  /** The cards that link the element already. */
  readonly exclude = input<readonly Uuid[]>([]);
  readonly linked = output<Uuid>();

  readonly query = signal('');
  readonly pick = signal<Uuid | null>(null);
  readonly busy = signal(false);

  /** The names of the boards the person writes; the search answers with board names. */
  private readonly writable = toSignal(
    this.api.boards().pipe(
      map((boards) => new Set(boards.filter((b) => b.canWrite).map((b) => b.name))),
      catchError(() => of(new Set<string>())),
    ),
    { initialValue: null },
  );

  private readonly hits = toSignal(
    combineLatest([
      toObservable(this.query).pipe(
        debounceTime(150),
        switchMap((q) => this.search(q)),
      ),
      toObservable(this.writable),
    ]).pipe(
      map(([hits, names]) =>
        names ? hits.filter((h) => names.has(h.detail.boardName ?? '')) : null,
      ),
    ),
    { initialValue: null },
  );

  readonly rows = computed<PickRow[] | null>(() => {
    const hits = this.hits();
    if (!hits) return null;
    const skip = new Set(this.exclude());
    return hits
      .filter((h) => !skip.has(h.targetId))
      .map((h) => ({
        id: h.targetId,
        title: h.title,
        sub: [h.detail.boardName, h.detail.columnName].filter(Boolean).join(' · '),
      }));
  });

  readonly heading = this.i18n.translate('todos.linkCard.title');
  readonly searchLabel = this.i18n.translate('todos.linkCard.search');
  readonly listLabel = this.i18n.translate('todos.linkCard.list');
  readonly emptyHeading = this.i18n.translate('todos.linkCard.none');
  readonly submitLabel = this.i18n.translate('todos.linkCard.submit');

  constructor() {
    effect(() => {
      const rows = this.rows();
      untracked(() => {
        if (!rows?.some((r) => r.id === this.pick())) this.pick.set(rows?.[0]?.id ?? null);
      });
    });
  }

  private search(q: string): Observable<TodoLinkTarget[]> {
    const src: Observable<TodoLinkTarget[]> =
      q.trim().length >= MIN_QUERY
        ? this.api.linkTargets(q.trim(), 'todo')
        : this.api.mine().pipe(
            map((m) =>
              m.items.map((c) => ({
                kind: 'todo' as const,
                targetId: c.id,
                title: c.title,
                detail: { boardName: c.boardName, columnName: c.columnName },
              })),
            ),
          );
    return src.pipe(catchError(() => of([] as TodoLinkTarget[])));
  }

  submit(cardId: Uuid): void {
    this.busy.set(true);
    this.api.addLink(cardId, this.kind(), this.targetId()).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(this.i18n.translate('todos.linkCard.done'));
        this.refresh.touch([{ kind: this.kind(), targetId: this.targetId() }]);
        this.linked.emit(cardId);
        this.open.set(false);
      },
      error: () => {
        this.busy.set(false);
        this.toast.error(this.i18n.translate('todos.linkCard.error'));
      },
    });
  }
}
