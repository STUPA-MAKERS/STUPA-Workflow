import type {
  AnswerKey,
  AppointmentInput,
  CalendarEntry,
  EntryKind,
} from '@core/api/calendar.service';
import type { TranslationKey } from '@core/i18n/translations';
import { shortTime } from '@shared/date-format';
import { filterKind } from '@stupa-makers/ui-kit/views/calendar';
import type { CalendarView, Spanned } from '@stupa-makers/ui-kit/views/calendar';

/*
 * The calendar helpers of the views are in the kit (`/views/calendar`, ui-kit 002272); this file
 * adds the parts of the page: the stored view, the routes, the Termin form and the text keys of
 * the app catalogue.
 */
export {
  CELL_ROOM,
  FILTER_KINDS,
  HOUR_REM,
  LIST_CHUNK,
  MIN_BLOCK,
  OPEN_HOUR,
  OVERLAP_HEAD,
  OVERLAP_INDENT,
  SHORT_BLOCK,
  DAY_HOURS,
  allDayOf,
  answerKind,
  dayBlocks,
  dayList,
  daysBetween,
  entryIcon,
  entryTime,
  filterKind,
  hasEnded,
  hoursOf,
  isSpan,
  isTimed,
  laneCount,
  mergeEntries,
  monthRows,
  onDay,
  openHour,
  singleDay,
  spanText,
  visibleEntries,
  weekBars,
} from '@stupa-makers/ui-kit/views/calendar';
export type {
  Bar,
  Block,
  CalendarView,
  DayRange,
  FilterKind,
  MonthCell,
  MonthRow,
  Spanned,
} from '@stupa-makers/ui-kit/views/calendar';

/** The key in `localStorage` that keeps the chosen view per browser. */
export const VIEW_STORAGE_KEY = 'ap.calendar.view';

/** The view that this browser chose last, else the month. A blocked storage gives the month. */
export function readStoredView(): CalendarView {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) === 'week' ? 'week' : 'month';
  } catch {
    return 'month';
  }
}

/** Keep the chosen view for the next visit. A blocked storage only forgets it. */
export function storeView(view: CalendarView): void {
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // Nothing to do: the view is a convenience, not data.
  }
}

/** The text key of the kind of an entry. */
export function kindKey(kind: EntryKind): TranslationKey {
  return `calendar.kind.${filterKind(kind)}`;
}

/** The route that an entry opens, or null for a Termin and an external entry (a dialog). */
export function entryLink(
  e: CalendarEntry,
): {
  readonly commands: readonly string[];
  readonly queryParams?: Readonly<Record<string, string>>;
} | null {
  switch (e.kind) {
    case 'meeting':
      return { commands: ['/meetings', e.id] };
    case 'card':
    case 'event':
      return { commands: ['/todos'], queryParams: { card: e.id } };
    case 'appointment':
    case 'external':
      return null;
  }
}

/** The form of the Termin dialog. The times are `HH:MM`, and empty for an all-day Termin. */
export interface AppointmentForm {
  readonly title: string;
  readonly allDay: boolean;
  readonly startsOn: string;
  readonly endsOn: string;
  readonly startTime: string;
  readonly endTime: string;
  readonly place: string;
  readonly description: string;
  readonly forAll: boolean;
  readonly public: boolean;
}

/** A new Termin on `day`: all-day, one day. */
export function emptyForm(day: string): AppointmentForm {
  return {
    title: '',
    allDay: true,
    startsOn: day,
    endsOn: day,
    startTime: '09:00',
    endTime: '10:00',
    place: '',
    description: '',
    forAll: false,
    public: false,
  };
}

/** The reason why a form cannot be saved, or null. */
export type FormError = 'title' | 'days' | 'times';

export function formError(form: AppointmentForm): FormError | null {
  if (!form.title.trim()) return 'title';
  if (!form.startsOn || !form.endsOn || form.endsOn < form.startsOn) return 'days';
  if (form.allDay) return null;
  if (!form.startTime || !form.endTime) return 'times';
  return form.endsOn === form.startsOn && form.endTime <= form.startTime ? 'times' : null;
}

/** The request body of a form with its invitations. */
export function toInput(
  form: AppointmentForm,
  teamIds: readonly string[],
  principalIds: readonly string[],
): AppointmentInput {
  return {
    title: form.title.trim(),
    startsOn: form.startsOn,
    endsOn: form.endsOn,
    startTime: form.allDay ? null : `${shortTime(form.startTime)}:00`,
    endTime: form.allDay ? null : `${shortTime(form.endTime)}:00`,
    place: form.place.trim() || null,
    description: form.description.trim() || null,
    forAll: form.forAll,
    public: form.public,
    teamIds,
    principalIds,
  };
}

/** The text key of an answer. */
export function answerKey(answer: AnswerKey): TranslationKey {
  return `calendar.answer.${answer}`;
}

/** The entry of the grid that stands for a Termin, so a save shows without a second read. */
export function entryOf(
  a: Spanned & { readonly id: string; readonly title: string; readonly place: string | null },
  teams: readonly { readonly id: string; readonly name: string; readonly gremiumId?: string | null }[],
  myAnswer: AnswerKey | null,
): CalendarEntry {
  return {
    kind: 'appointment',
    id: a.id,
    title: a.title,
    startsOn: a.startsOn,
    endsOn: a.endsOn,
    startTime: a.startTime,
    endTime: a.endTime,
    place: a.place,
    source: teams[0]?.name ?? null,
    gremiumIds: teams.flatMap((t) => (t.gremiumId ? [t.gremiumId] : [])),
    mine: true,
    myAnswer,
  };
}
