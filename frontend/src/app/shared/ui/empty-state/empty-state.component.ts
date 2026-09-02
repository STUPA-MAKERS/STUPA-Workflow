import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';

/**
 * One shape for "there is nothing here".
 *
 * It covers both cases the platform has: a page that cannot show what was asked for
 * (a missing application, a 404) and a list that is legitimately empty. Both used to be
 * written by hand per page, so a missing application rendered as one line of muted text
 * in the top-left corner of an otherwise blank page, while the 404 page was centred with
 * a heading and a way out.
 *
 * The action is projected, so the caller decides whether there is a way forward and what
 * it is.
 */
@Component({
  selector: 'app-empty-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  templateUrl: './empty-state.component.html',
  styleUrl: './empty-state.component.scss',
})
export class EmptyStateComponent {
  /** Short statement of what is missing. Never an error code on its own. */
  readonly heading = input.required<string>();
  /** One sentence of context: why the reader is here and what to do next. */
  readonly body = input<string | null>(null);
  /** Large muted glyph above the heading. */
  readonly icon = input<IconName>('document');
  /** Displayed above the heading, for a code such as 404. */
  readonly code = input<string | null>(null);
}
