import { ChangeDetectionStrategy, Component, booleanAttribute, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import type { CalendarSubscribeComponent } from '../calendar-subscribe/calendar-subscribe.component';
import type { MeetingsView } from '../meetings-overview.util';
import { MeetingsViewSwitchComponent } from '../meetings-view-switch/meetings-view-switch.component';

/**
 * The end of the header of the meeting overview: the switch between the list and the
 * calendar, then the calendar button that opens the subscription. Both views show them in
 * this order, so they keep their place when the view changes. The host has no box, so the
 * controls sit in the actions of the page header.
 *
 * The page keeps the `app-calendar-subscribe` popover, because its phone menu opens it too.
 *
 * ```html
 * <app-meetings-view-actions view="list" [abo]="abo" (viewChange)="viewChange.emit($event)" />
 * <app-calendar-subscribe #abo />
 * ```
 */
@Component({
  selector: 'app-meetings-view-actions',
  standalone: true,
  imports: [ButtonComponent, IconComponent, MeetingsViewSwitchComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './meetings-view-actions.component.html',
  styleUrl: './meetings-view-actions.component.scss',
})
export class MeetingsViewActionsComponent {
  /** The view that shows now. */
  readonly view = input.required<MeetingsView>();
  /** Show the switch between the list and the calendar. */
  readonly showSwitch = input(true, { transform: booleanAttribute });
  /** The subscription popover that the calendar button opens. */
  readonly abo = input.required<CalendarSubscribeComponent>();
  /** The person picked the other view. */
  readonly viewChange = output<MeetingsView>();
}
