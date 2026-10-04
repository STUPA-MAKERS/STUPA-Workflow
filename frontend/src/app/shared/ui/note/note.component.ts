import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';

/** The tone of a note: the icon takes the warning or the error colour, the surface a tint of it. */
export type NoteKind = 'neutral' | 'warn' | 'error';

/**
 * A short note with an icon: a rule that applies here, a reason why an action is not
 * possible. Only text with a function; a note never repeats the page title.
 *
 * The note adds no live region. A page that shows a note as the answer to an action
 * gives it `role="status"` or `role="alert"` itself.
 */
@Component({
  selector: 'app-note',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  host: {
    '[class]': "'note--' + kind()",
  },
  templateUrl: './note.component.html',
  styleUrl: './note.component.scss',
})
export class NoteComponent {
  readonly icon = input<IconName>('info');
  readonly kind = input<NoteKind>('neutral');
}
