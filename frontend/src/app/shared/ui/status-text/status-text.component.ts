import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import type { StatusKind } from '../../status-kind.util';

/**
 * A status as text in its colour: no dot, no pill, no plate.
 *
 * The caller gives the label as content and the colour as `kind`. The functions in
 * `shared/status-kind.util.ts` give both for each status of the platform:
 *
 * ```html
 * @let s = invoiceStatus(invoice.status);
 * <app-status-text [kind]="s.kind">{{ s.key | t }}</app-status-text>
 * ```
 *
 * A tag (a feature of a thing such as NÖ or Pool) is not a status. Use `app-badge` for it.
 */
@Component({
  selector: 'app-status-text',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'st',
    '[class]': "'st--' + kind()",
  },
  templateUrl: './status-text.component.html',
  styleUrl: './status-text.component.scss',
})
export class StatusTextComponent {
  /** The colour of the status. */
  readonly kind = input<StatusKind>('neutral');
}
