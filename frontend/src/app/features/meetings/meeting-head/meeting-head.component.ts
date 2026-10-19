import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import type { StatusKind } from '@shared/status-kind.util';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';

/**
 * The head of a meeting view: "Zurück", the title with the status after it, and a quiet
 * sub line. The meeting page and the follow view use it. The controls of the page follow
 * as content.
 *
 * The host is the `header` of the page, so the page keeps its frame rules (padding,
 * height, gap, role). On a small screen the page sets `--mh-title-size` and
 * `--mh-title-line` for the title and `--mh-status-size` for the status.
 *
 * ```html
 * <header appMeetingHead class="mp__head" [heading]="m.title" [statusKind]="status().kind"
 *         [statusText]="status().key | t" [sub]="subLine()" (back)="back.emit()">
 *   <app-row-menu … />
 * </header>
 * ```
 */
@Component({
  // eslint-disable-next-line @angular-eslint/component-selector -- the host is the header of the page, which keeps its frame rules
  selector: 'header[appMeetingHead]',
  standalone: true,
  imports: [ButtonComponent, IconComponent, StatusTextComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './meeting-head.component.html',
  styleUrl: './meeting-head.component.scss',
})
export class MeetingHeadComponent {
  /** The title of the meeting. */
  readonly heading = input.required<string>();
  /** The colour of the status. */
  readonly statusKind = input<StatusKind>('neutral');
  /** The translated status. */
  readonly statusText = input.required<string>();
  /** The sub line, such as the date and the place. `null`: no sub line. */
  readonly sub = input<string | null>(null);
  /** The person pressed "Zurück". */
  readonly back = output<void>();
}
