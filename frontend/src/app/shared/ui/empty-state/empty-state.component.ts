import { booleanAttribute, ChangeDetectionStrategy, Component, computed, input, numberAttribute } from '@angular/core';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';

/** Bar widths in percent of the ghost rows, title and sub line. Uneven, so they read as text. */
const GHOST_ROWS: readonly { title: number; sub: number }[] = [
  { title: 62, sub: 34 },
  { title: 48, sub: 28 },
  { title: 70, sub: 40 },
  { title: 52, sub: 30 },
  { title: 44, sub: 26 },
];

/**
 * The shape of the ghost rows: the real rows of the list they stand in for.
 *
 * - `row`: title and sub line, a short tag at the end (most lists).
 * - `choice`: a radio ring before the text (a list to pick one from).
 * - `person`: an avatar before the name (members, guests, users).
 * - `date`: a date block before the title (meetings, protocols).
 * - `agenda`: a number before the title (agenda items).
 * - `file`: a file square before the name (attachments, logos).
 * - `table`: cells in columns (data tables).
 * - `card`: a card with title, sub line and a foot of chips (to-do cards).
 * - `chat`: message bubbles, left and right (a conversation).
 * - `text`: lines of running text (a protocol text).
 */
export type EmptyStateShape =
  | 'row'
  | 'choice'
  | 'person'
  | 'date'
  | 'agenda'
  | 'file'
  | 'table'
  | 'card'
  | 'chat'
  | 'text';

/**
 * One shape for "there is nothing here", in two looks.
 *
 * A list: faint ghost rows in the shape of list rows stand for the list that is missing,
 * and over them sit the message and, if the caller projects one, one way on (a tonal
 * button). It serves an empty list and a search without a match. It is the
 * "Geister-Zeilen" state of the "TOP hinzufügen" dialog.
 *
 * `plain`: no ghost rows, a muted glyph above the message. It serves everything that is
 * not a list: a detail pane with nothing open, a missing record (`code`), a page the
 * reader has no access to. Ghost rows there would promise a list that never comes.
 *
 * Set `fill` when the empty state is the whole page or pane. The host then takes the free
 * height of its flex-column parent and centres the block in it vertically. Without it, the
 * block keeps its own height, for a card, a tab or a dialog.
 */
@Component({
  selector: 'app-empty-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  templateUrl: './empty-state.component.html',
  styleUrl: './empty-state.component.scss',
  host: { '[class.es-host--fill]': 'fill()', '[class.es-host--plain]': 'plain()' },
})
export class EmptyStateComponent {
  /** Short statement of what is missing. Never an error code on its own. */
  readonly heading = input.required<string>();
  /** One short line of context, only where the heading alone leaves the reader stuck. */
  readonly body = input<string | null>(null);
  /** Displayed above the heading, for a code such as 404. */
  readonly code = input<string | null>(null);
  /** No ghost rows: the look for everything that is not an empty list. */
  readonly plain = input(false, { transform: booleanAttribute });
  /** Muted glyph above the message of a `plain` state. A `code` takes its place. */
  readonly icon = input<IconName>('file');
  /** The shape of the ghost rows, after the real rows of the list. */
  readonly shape = input<EmptyStateShape>('row');
  /** Number of ghost rows, 1 to 5. A small box (a dashboard tile) passes fewer. */
  readonly rows = input(5, { transform: numberAttribute });
  /**
   * Fill the free height of the parent and centre in it. The parent must be a flex
   * column that has that height.
   */
  readonly fill = input(false, { transform: booleanAttribute });
  /**
   * Heading level of the message, 1 to 3. Without it, a `fill` state is an `h2` and any
   * other state a plain line, so a list inside a page adds no heading.
   */
  readonly level = input<number | undefined, unknown>(undefined, {
    transform: (v: unknown) => (v == null || v === '' ? undefined : numberAttribute(v)),
  });

  protected readonly headingLevel = computed(() => {
    const level = this.level();
    if (level === undefined || Number.isNaN(level)) return this.fill() ? 2 : 0;
    return Math.min(3, Math.max(1, Math.round(level)));
  });

  protected readonly ghosts = computed(() =>
    GHOST_ROWS.slice(0, Math.min(GHOST_ROWS.length, Math.max(1, this.rows() || 1))),
  );
}
