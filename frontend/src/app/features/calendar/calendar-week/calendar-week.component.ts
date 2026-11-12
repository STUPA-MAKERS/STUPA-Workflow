import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import type { CalendarEntry } from '@core/api/calendar.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { longDate, shortTime, weekdayName } from '@shared/date-format';
import { IconComponent, ScrollFadeDirective } from '@stupa-makers/ui-kit';
import type { CalendarDay } from '../calendar-grid.util';
import {
  type Block,
  DAY_HOURS,
  allDayOf,
  dayBlocks,
  entryIcon,
  isSpan,
  openHour,
  spanText,
} from '../calendar.util';

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
 * as columns with an hour axis. A timed entry is a block from its start to its end, and
 * a timed entry over several days has one block on each of its days (§ 000744). An
 * all-day entry and a due card are in the row above the hours.
 *
 * The axis shows the whole day, 00:00 to 24:00, so a block over several days ends at
 * midnight and not at the last hour of a shorter axis (§ 000746). The view opens at
 * 08:00, or at the first entry of the week when that is earlier. A press on the head of
 * a day picks the day, a press on an entry opens it.
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

  private readonly scroll = viewChild.required<ElementRef<HTMLElement>>('scroll');
  readonly hours = Array.from({ length: DAY_HOURS }, (_, i) => i);
  readonly columns = computed<readonly WeekColumn[]>(() =>
    this.days().map((day) => ({
      day,
      weekday: weekdayName(day.iso, this.i18n.formatLocale()),
      label: longDate(day.iso, this.i18n.formatLocale()),
      allDay: allDayOf(this.entries(), day.iso),
      blocks: dayBlocks(this.entries(), day.iso, 0, DAY_HOURS),
    })),
  );

  constructor() {
    afterNextRender(() => {
      const area = this.scroll().nativeElement;
      const first = openHour(
        this.entries(),
        this.days().map((d) => d.iso),
      );
      area.scrollTop = (area.scrollHeight / DAY_HOURS) * first;
    });
  }

  readonly icon = entryIcon;
  readonly time = shortTime;

  /**
   * "14:00 – 15:30 Jour fixe": the whole entry for the tooltip and a screen reader. An
   * entry over several days names its days too.
   */
  blockLabel(e: CalendarEntry): string {
    if (isSpan(e)) return `${spanText(e, this.i18n.formatLocale())} ${e.title}`;
    const end = e.endTime ? ` – ${shortTime(e.endTime)}` : '';
    return `${shortTime(e.startTime)}${end} ${e.title}`;
  }

  /** "08:00": an hour of the axis. */
  hourLabel(hour: number): string {
    return `${String(hour).padStart(2, '0')}:00`;
  }
}
