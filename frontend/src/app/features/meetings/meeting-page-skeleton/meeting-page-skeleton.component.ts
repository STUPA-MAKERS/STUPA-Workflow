import { ChangeDetectionStrategy, Component } from '@angular/core';
import { MEDIA, mediaQuery } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/**
 * The first load of a meeting: the frame of `app-meeting-page` with bars where its text
 * goes. The head, the agenda beside the sheet on a wide screen, the protocol sheet and the
 * dock sit where the page puts them, so nothing moves when the meeting arrives.
 */
@Component({
  selector: 'app-meeting-page-skeleton',
  standalone: true,
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './meeting-page-skeleton.component.html',
  styleUrl: './meeting-page-skeleton.component.scss',
  host: { 'aria-busy': 'true', class: 'skel-in' },
})
export class MeetingPageSkeletonComponent {
  protected readonly wide = mediaQuery(MEDIA.wide);
  /** Name widths of the agenda rows, in percent. */
  protected readonly rows = [62, 78, 55, 70, 48];
}
