import { booleanAttribute, ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent, type IconName } from '@stupa-makers/ui-kit';

/**
 * The tone of a note: the icon takes the warning or the error colour, the surface a tint of
 * it. `ok` confirms a result (an import that worked): the icon in the accent colour, the
 * text in the full text colour, the surface untinted.
 */
export type NoteKind = 'neutral' | 'ok' | 'warn' | 'error';

/** The surface the note sits on: 2 on a page or a pane, 3 inside a sheet (surface 2). */
export type NoteSurface = 2 | 3;

/**
 * A short note with an icon: a rule that applies here, a reason why an action is not
 * possible. Only text with a function; a note never repeats the page title.
 *
 * The note adds no live region. A page that shows a note as the answer to an action
 * gives it `role="status"` or `role="alert"` itself.
 *
 * A load error of a page or a pane is `kind="error"` with `retryable`: the note then shows
 * an "Erneut versuchen" text button at its end and emits `retry` when it is pressed.
 * Another action goes in the same place as projected content with the `noteAction`
 * attribute: `<app-button noteAction variant="text" size="sm">Öffnen</app-button>`.
 */
@Component({
  selector: 'app-note',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, ButtonComponent, TranslatePipe],
  host: {
    '[class]': "'note--' + kind()",
    '[class.note--s3]': 'surface() === 3',
  },
  templateUrl: './note.component.html',
  styleUrl: './note.component.scss',
})
export class NoteComponent {
  readonly icon = input<IconName>('info');
  readonly kind = input<NoteKind>('neutral');
  readonly surface = input<NoteSurface>(2);
  /** Shows the "Erneut versuchen" button. */
  readonly retryable = input(false, { transform: booleanAttribute });
  /** Emits when the "Erneut versuchen" button is pressed. */
  readonly retry = output();
}
