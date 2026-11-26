import type { EventDetail, EventInput, EventQuery, EventSegment } from '@core/api/events.service';
import { EVENT_SEGMENTS } from '@core/api/events.service';
import type { TranslationKey } from '@core/i18n/translations';
import type { ListQuery } from '@stupa-makers/ui-kit';
import type { FormValue } from '@stupa-makers/ui-kit/screens';
import { eventDays } from '../../features/todos/todos.util';

/** The label of each segment of the page (spec 003028). */
export const SEGMENT_LABEL: Readonly<Record<EventSegment, TranslationKey>> = {
  upcoming: 'events.segment.upcoming',
  past: 'events.segment.past',
  done: 'events.segment.done',
  void: 'events.segment.void',
};

/** The value of the choice "Neue Reihe …" in the field Reihe. */
export const NEW_SERIES = 'new';

export const isSegment = (value: unknown): value is EventSegment =>
  EVENT_SEGMENTS.includes(value as EventSegment);

const text = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim() !== '' ? value.trim() : undefined;

const orNull = (value: unknown): string | null => text(value) ?? null;

/** `19:00:00` → `19:00`. */
export const shortTime = (value: string | null): string | null => (value ? value.slice(0, 5) : null);

/** The filter of the API from the query of the screen. */
export function eventQuery(query: ListQuery): EventQuery {
  const f = query.filters;
  return { team: text(f['team']), series: text(f['series']), q: text(query.search) };
}

/** "20.11.2026 19:00–21.11.2026 02:00": the days and, when set, the times of an Event. */
export function eventWhen(
  e: Pick<EventDetail, 'startsOn' | 'endsOn' | 'startTime' | 'endTime'>,
  locale: string,
): string | null {
  const days = eventDays(e.startsOn, e.endsOn, locale);
  if (!days) return null;
  const start = shortTime(e.startTime);
  const end = shortTime(e.endTime);
  const times = start && end ? `${start}–${end}` : (start ?? (end ? `–${end}` : null));
  return times ? `${days}, ${times}` : days;
}

/** The value of the form for an Event, or the empty form for a new one. */
export function eventFormValue(e: EventDetail | null): FormValue {
  return {
    teamId: e?.teamId ?? '',
    title: e?.title ?? '',
    status: e?.status ?? '',
    descriptionMd: e?.descriptionMd ?? '',
    startsOn: e?.startsOn ?? '',
    startTime: shortTime(e?.startTime ?? null) ?? '',
    endsOn: e?.endsOn ?? '',
    endTime: shortTime(e?.endTime ?? null) ?? '',
    place: e?.place ?? '',
    participants: e?.participants ?? null,
    seriesId: e?.seriesId ?? '',
    seriesName: '',
    shopUrl: e?.shopUrl ?? '',
  };
}

/**
 * The form of `Folgeveranstaltung anlegen` (spec 003030): the name, the description, the
 * place, the shop, the team and the series of the Event, and no dates, status or links.
 */
export function followUpValue(e: EventDetail): FormValue {
  return {
    ...eventFormValue(null),
    teamId: e.teamId,
    title: e.title,
    descriptionMd: e.descriptionMd ?? '',
    place: e.place ?? '',
    shopUrl: e.shopUrl ?? '',
    seriesId: e.seriesId ?? '',
  };
}

const time = (value: unknown): string | null => {
  const t = text(value);
  return t ? (t.length === 5 ? `${t}:00` : t) : null;
};

const count = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : null;
};

/** The body of a create or a change; `seriesId` is the id of the series to save. */
export function eventBody(value: FormValue, seriesId: string | null): EventInput {
  return {
    teamId: text(value['teamId']),
    title: text(value['title']) ?? '',
    ...(text(value['status']) ? { status: text(value['status']) } : {}),
    descriptionMd: orNull(value['descriptionMd']),
    startsOn: orNull(value['startsOn']),
    startTime: time(value['startTime']),
    endsOn: orNull(value['endsOn']),
    endTime: time(value['endTime']),
    place: orNull(value['place']),
    participants: count(value['participants']),
    seriesId,
    shopUrl: orNull(value['shopUrl']),
  };
}
