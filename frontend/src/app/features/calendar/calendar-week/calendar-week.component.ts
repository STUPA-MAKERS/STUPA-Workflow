import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import type { CalendarEntry } from '@core/api/calendar.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { longDate, shortTime, weekdayName } from '@shared/date-format';
import { IconComponent, ScrollFadeDirective } from '@stupa-makers/ui-kit';
import type { CalendarDay } from '../calendar-grid.util';
import { type Block, allDayOf, dayBlocks, entryIcon, hourRange } from '../calendar.util';

/** One day column of the week view. */
interface WeekColumn {
  readonly day: CalendarDay;
  readonly weekday: string;
  /** "Mittwoch, 11. November 2026": the name of the day for a screen reader. */
  readonly label: string;
  readonly allDay: readonly CalendarEntry[];
  readonly blocks: readonly Block[];
}

/**
 * The week view of the desktop Kalender (§ 000728): the seven days from Monday to Sunday
 * as columns with an hour axis. A timed entry of one day is a block from its start to
 * its end. An all-day entry, an entry over several days and a due card are in the row
 * above the hours.
 *
 * The axis shows 08:00 to 21:00 and widens for an earlier or a later entry. A press on
 * the head of a day picks the day, a press on an entry opens it.
 */
@Component({
  selector: 'app-calendar-week',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, ScrollFadeDirective, TranslatePipe],
  templateUrl: './calendar-week.component.html',
  styleUrl: './calendar-week.component.scss',
})
export class CalendarWeekComponent {
  private readonly i18n = inject(I18nService);

  /** The seven days of the week. */
  readonly days = input.required<readonly CalendarDay[]>();
  /** The entries that the filters keep. */
  readonly entries = input.required<readonly CalendarEntry[]>();
  readonly selectedDay = input.required<string>();
  /** The name of the grid for a screen reader. */
  readonly label = input.required<string>();

  readonly selectDay = output<string>();
  readonly openEntry = output<CalendarEntry>();

  private readonly range = computed(() => hourRange(this.entries()));
  readonly hours = computed(() =>
    Array.from({ length: this.range().to - this.range().from }, (_, i) => this.range().from + i),
  );
  readonly columns = computed<readonly WeekColumn[]>(() =>
    this.days().map((day) => ({
      day,
      weekday: weekdayName(day.iso, this.i18n.formatLocale()),
      label: longDate(day.iso, this.i18n.formatLocale()),
      allDay: allDayOf(this.entries(), day.iso),
      blocks: dayBlocks(this.entries(), day.iso, this.range().from),
    })),
  );

  readonly icon = entryIcon;
  readonly time = shortTime;

  /** "14:00 – 15:30 Jour fixe": the whole entry for the tooltip and a screen reader. */
  blockLabel(e: CalendarEntry): string {
    const end = e.endTime ? ` – ${shortTime(e.endTime)}` : '';
    return `${shortTime(e.startTime)}${end} ${e.title}`;
  }

  /** "08:00": an hour of the axis. */
  hourLabel(hour: number): string {
    return `${String(hour).padStart(2, '0')}:00`;
  }
}
