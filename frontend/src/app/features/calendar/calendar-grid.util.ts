import { InjectionToken } from '@angular/core';

/*
 * The grid helpers are in the kit (`/views/calendar`, ui-kit 002272); the page adds its clock.
 */
export {
  gridRange,
  monthGrid,
  monthOf,
  shiftDay,
  shiftMonth,
  weekOf,
  weekdayNames,
} from '@stupa-makers/ui-kit/views/calendar';
export type { CalendarDay, MonthRef } from '@stupa-makers/ui-kit/views/calendar';

/** The clock of the Kalender ("today"). A spec replaces it with a fixed time. */
export const CALENDAR_NOW = new InjectionToken<() => Date>('CALENDAR_NOW', {
  providedIn: 'root',
  factory: () => () => new Date(),
});
