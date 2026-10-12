import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import type { Meeting } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import { ButtonComponent, DialogComponent, IconComponent } from '@stupa-makers/ui-kit';
import { shortTime } from '../meetings-display.util';

/**
 * "Sitzung schon eröffnen?": the extra question before an early open.
 *
 * Between the earliest open (`opensAt`) and `confirmUntil` the open of a planned
 * meeting is early. The server refuses it without `confirmEarly` (409
 * `early_open_unconfirmed`), so the page asks first. The admin sets both points on
 * the deadlines page (by default 60 and 10 minutes before the planned start).
 */
@Component({
  selector: 'app-early-open-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DialogComponent, ButtonComponent, IconComponent, NoteComponent],
  templateUrl: './early-open-dialog.component.html',
  styleUrl: './early-open-dialog.component.scss',
})
export class EarlyOpenDialogComponent {
  private readonly i18n = inject(I18nService);

  readonly open = input(false);
  readonly meeting = input.required<Meeting>();
  /** The dialog closes without an open. */
  readonly closed = output<void>();
  /** The lead confirmed the early open. */
  readonly confirmed = output<void>();

  /** "Die Sitzung ist erst für 18:00 Uhr geplant." */
  protected readonly body = computed(() => {
    const time = shortTime(this.meeting().startTime);
    return time
      ? this.i18n.translate('meetings.earlyOpen.body', { time })
      : this.i18n.translate('meetings.earlyOpen.bodyNoTime');
  });
}
