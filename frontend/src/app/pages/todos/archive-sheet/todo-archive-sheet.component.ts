import { ChangeDetectionStrategy, Component, effect, inject, input, model, output, signal, untracked } from '@angular/core';
import type { Page, Uuid } from '@core/api/models';
import { TodosApiService, type TodoCardDetail, type TodoCardTile } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { liveSearch } from '@shared/live-search';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import {
  ButtonComponent,
  IconComponent,
  MEDIA,
  mediaQuery,
  ToastService,
} from '@stupa-makers/ui-kit';
import { isoDay, shortDay } from '../../../features/todos/todos.util';
import { NoteComponent } from '@shared/ui/note/note.component';

/** One page of the archive. */
export const ARCHIVE_PAGE = 50;

/**
 * "Archiv": the archived cards of a board, newest first, with a search. A row opens the
 * card; "Wiederherstellen" puts it back on the board.
 */
@Component({
  selector: 'app-todo-archive-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NoteComponent, TranslatePipe, ButtonComponent, EmptyStateComponent, IconComponent, SearchPillComponent, SideSheetComponent],
  templateUrl: './todo-archive-sheet.component.html',
  styleUrl: './todo-archive-sheet.component.scss',
})
export class TodoArchiveSheetComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = model(false);
  readonly boardId = input.required<Uuid>();
  readonly openCard = output<Uuid>();
  readonly restored = output<TodoCardDetail>();

  readonly phone = mediaQuery(MEDIA.phone);
  readonly items = signal<TodoCardTile[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly failed = signal(false);
  private readonly today = isoDay(new Date());

  readonly search = liveSearch<Page<TodoCardTile>>({
    run: (q) => {
      this.loading.set(true);
      return this.api.archive(this.boardId(), q, 0, ARCHIVE_PAGE);
    },
    result: (page) => this.take(page, false),
    reset: () => this.load(),
    error: () => this.fail(),
  });

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.search.sync('');
        this.load();
      });
    });
  }

  protected load(offset = 0): void {
    this.loading.set(true);
    this.failed.set(false);
    this.api.archive(this.boardId(), this.search.applied(), offset, ARCHIVE_PAGE).subscribe({
      next: (page) => this.take(page, offset > 0),
      error: () => this.fail(),
    });
  }

  private take(page: Page<TodoCardTile>, append: boolean): void {
    this.loading.set(false);
    this.failed.set(false);
    this.items.set(append ? [...this.items(), ...page.items] : page.items);
    this.total.set(page.total);
  }

  private fail(): void {
    this.loading.set(false);
    this.failed.set(true);
  }

  more(): void {
    this.load(this.items().length);
  }

  doneOn(card: TodoCardTile): string {
    if (!card.completedAt) return '';
    const d = new Date(card.completedAt);
    if (Number.isNaN(d.getTime())) return '';
    return this.i18n.translate('todos.archive.doneOn', {
      date: shortDay(isoDay(d), this.today, this.i18n.formatLocale()),
    });
  }

  restore(card: TodoCardTile): void {
    this.api.restoreCard(card.id).subscribe({
      next: (detail) => {
        this.items.update((list) => list.filter((c) => c.id !== card.id));
        this.total.update((n) => Math.max(0, n - 1));
        this.restored.emit(detail);
      },
      error: () => this.toast.error(this.i18n.translate('todos.error.save')),
    });
  }

  pick(card: TodoCardTile): void {
    this.open.set(false);
    this.openCard.emit(card.id);
  }
}
