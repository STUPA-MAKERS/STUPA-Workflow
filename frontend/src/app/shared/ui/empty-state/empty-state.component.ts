import { booleanAttribute, ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';

/**
 * One shape for "there is nothing here".
 *
 * It covers both cases the platform has: a page that cannot show what was asked for
 * (a missing application, a 404) and a list that is legitimately empty. One component for
 * both, so the two do not drift into looking like different kinds of answer.
 *
 * The action is projected, so the caller decides whether there is a way forward and what
 * it is.
 *
 * Set `fill` when the empty state is the whole page. The host then takes the free height
 * of its flex-column parent and centres the content vertically in it. Do not set it in a
 * card or a list row: there the empty state stays at the top, where the reader looks.
 */
@Component({
  selector: 'app-empty-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  templateUrl: './empty-state.component.html',
  styleUrl: './empty-state.component.scss',
  host: { '[class.es-host--fill]': 'fill()' },
})
export class EmptyStateComponent {
  /** Short statement of what is missing. Never an error code on its own. */
  readonly heading = input.required<string>();
  /** One sentence of context: why the reader is here and what to do next. */
  readonly body = input<string | null>(null);
  /** Large muted glyph above the heading. */
  readonly icon = input<IconName>('document');
  /** Glyph size in px. A block-level empty state (a card, a tab) passes a smaller one. */
  readonly iconSize = input(32);
  /** Displayed above the heading, for a code such as 404. */
  readonly code = input<string | null>(null);
  /**
   * Fill the free height of the parent and centre in it. The parent must be a flex
   * column that has that height.
   */
  readonly fill = input(false, { transform: booleanAttribute });
}
