import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import type { Uuid } from '@core/api/models';
import type { TodoBoard, TodoCardTile, TodoColumn, TodoLabel } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AvatarStackComponent } from '@shared/ui/avatar/avatar.component';
import { IconComponent } from '@stupa-makers/ui-kit';
import {
  dueInfo,
  linkLine,
  personName,
  sortedColumns,
  type DueInfo,
  type Translate,
} from '../../../features/todos/todos.util';

export type DueSort = 'none' | 'asc' | 'desc';

interface ListRow {
  card: TodoCardTile;
  link: string | null;
  labels: TodoLabel[];
  due: DueInfo | null;
  names: string[];
  ids: (Uuid | null)[];
}

interface ListGroup {
  column: TodoColumn;
  rows: ListRow[];
}

/**
 * "Liste" (frame 8): the cards of the board as a table, one group per column, with
 * Titel, Verknüpft, Label, Fällig and Wer. "Fällig" sorts (up, down, board order). The
 * done group starts folded. The circle before a title moves the card into the done
 * column, or back into the first column.
 */
@Component({
  selector: 'app-todo-list-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, AvatarStackComponent, IconComponent],
  templateUrl: './todo-list-view.component.html',
  styleUrl: './todo-list-view.component.scss',
})
export class TodoListViewComponent {
  private readonly i18n = inject(I18nService);
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly board = input.required<TodoBoard>();
  readonly cards = input.required<ReadonlyMap<Uuid, readonly TodoCardTile[]>>();
  readonly labels = input<ReadonlyMap<Uuid, TodoLabel>>(new Map());
  readonly today = input.required<string>();

  readonly openCard = output<Uuid>();
  readonly toggleDone = output<TodoCardTile>();

  readonly sort = signal<DueSort>('none');
  /** Open groups among the done columns (they start folded). */
  readonly openDone = signal<ReadonlySet<Uuid>>(new Set());

  readonly groups = computed<ListGroup[]>(() => {
    const locale = this.i18n.formatLocale();
    const today = this.today();
    return sortedColumns(this.board().columns).map((column) => {
      const rows = (this.cards().get(column.id) ?? []).map<ListRow>((card) => ({
        card,
        link: card.primaryLink ? linkLine(card.primaryLink, today, locale, this.t) : null,
        labels: card.labelIds.map((id) => this.labels().get(id)).filter((l): l is TodoLabel => !!l),
        due: card.dueDate ? dueInfo(card.dueDate, today, locale, this.t, column.isDone) : null,
        names: card.assignees.map((a) => personName(a, this.t)),
        ids: card.assignees.map((a) => a.principalId),
      }));
      return { column, rows: this.sorted(rows) };
    });
  });

  private sorted(rows: ListRow[]): ListRow[] {
    const dir = this.sort();
    if (dir === 'none') return rows;
    // Cards without a date go last in both directions.
    return [...rows].sort((a, b) => {
      const x = a.card.dueDate;
      const y = b.card.dueDate;
      if (!x && !y) return 0;
      if (!x) return 1;
      if (!y) return -1;
      return dir === 'asc' ? x.localeCompare(y) : y.localeCompare(x);
    });
  }

  nextSort(): void {
    this.sort.update((s) => (s === 'none' ? 'asc' : s === 'asc' ? 'desc' : 'none'));
  }

  ariaSort(): 'ascending' | 'descending' | 'none' {
    const s = this.sort();
    return s === 'asc' ? 'ascending' : s === 'desc' ? 'descending' : 'none';
  }

  folded(group: ListGroup): boolean {
    return group.column.isDone && !this.openDone().has(group.column.id);
  }

  toggleGroup(group: ListGroup): void {
    this.openDone.update((set) => {
      const next = new Set(set);
      if (next.has(group.column.id)) next.delete(group.column.id);
      else next.add(group.column.id);
      return next;
    });
  }
}
