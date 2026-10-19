import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import type { Uuid } from '@core/api/models';
import type { TodoCardTile, TodoLabel } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';
import { LINK_ICON, dueInfo, linkLine, personName, shortDay, type Translate } from '../todos.util';
import { TodoLabelComponent } from '../card-facts/todo-label.component';
import { TodoDueComponent } from '../card-facts/todo-due.component';
import { TodoAssigneesComponent } from '../card-facts/todo-assignees.component';

/** The most labels a tile shows; the drawer shows all. */
const TILE_LABELS = 2;

/**
 * One card on the board (frames 0, 1, 11, 34): the labels, the title, the first link,
 * the due date, the checklist, the comments and the people, and in a list of the phone
 * the column tag. A card in the done column
 * shows the done mark and the day it was done instead of the due date.
 *
 * The whole tile is the target: its title is a button that opens the card. The board
 * gives the tile its drag behaviour; the keys of the keyboard drag reach the board
 * through the button.
 */
@Component({
  selector: 'app-todo-card-tile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TodoAssigneesComponent, TodoDueComponent, TodoLabelComponent, TranslatePipe, IconComponent],
  host: {
    class: 'tt',
    '[class.tt--done]': 'done()',
    '[class.tt--lifted]': 'lifted()',
  },
  templateUrl: './todo-card-tile.component.html',
  styleUrl: './todo-card-tile.component.scss',
})
export class TodoCardTileComponent {
  private readonly i18n = inject(I18nService);
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly card = input.required<TodoCardTile>();
  readonly labels = input<ReadonlyMap<Uuid, TodoLabel>>(new Map());
  /** The card sits in the done column. */
  readonly done = input(false);
  /** Today as `YYYY-MM-DD`. */
  readonly today = input.required<string>();
  /** The keyboard drag holds this card. */
  readonly lifted = input(false);
  /**
   * The name of the column of the card, as a tag in the fact bar: a list of the phone
   * shows the cards of every column of a board in one list.
   */
  readonly column = input<string | null>(null);

  /** The title was activated: open the card. */
  readonly open = output<void>();

  readonly tileLabels = computed(() =>
    this.card()
      .labelIds.map((id) => this.labels().get(id))
      .filter((l): l is TodoLabel => !!l)
      .slice(0, TILE_LABELS),
  );

  readonly link = computed(() => {
    const link = this.card().primaryLink;
    if (!link) return null;
    return { icon: LINK_ICON[link.kind], text: linkLine(link, this.today(), this.i18n.formatLocale(), this.t) };
  });

  readonly due = computed(() => {
    const day = this.card().dueDate;
    if (!day || this.done()) return null;
    return dueInfo(day, this.today(), this.i18n.formatLocale(), this.t);
  });

  /** The day the card entered the done column. */
  readonly doneOn = computed(() => {
    const at = this.card().completedAt;
    if (!this.done() || !at) return null;
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return null;
    const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    return shortDay(day, this.today(), this.i18n.formatLocale());
  });

  readonly names = computed(() => this.card().assignees.map((a) => personName(a, this.t)));
  readonly ids = computed(() => this.card().assignees.map((a) => a.principalId));
}
