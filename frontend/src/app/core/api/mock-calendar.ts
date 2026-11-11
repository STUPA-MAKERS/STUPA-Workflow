/**
 * Demo data of the Kalender for the mock API (dev builds only): meetings, due cards, an
 * Event, Termine and external entries around today, the search, the person search, the
 * Termine with their answers, and the external calendars of the admin page. The interceptor loads this module on first use, so it stays out of the
 * initial bundle.
 */
import { signal } from '@angular/core';
import { isoDay } from '@shared/date-format';
import type {
  AnswerKey,
  Appointment,
  AppointmentInput,
  CalendarEntry,
  CalendarGremium,
  CalendarPerson,
  ExternalCalendar,
  ExternalCalendarInput,
  ExternalEntry,
  PublicAppointment,
  PublicMeeting,
} from './calendar.service';

/** The answer of a mock route: the status and the body. */
export interface MockCalendarReply {
  readonly status: number;
  readonly body: unknown;
}

const STUPA: CalendarGremium = { id: 'g0000000-0000-0000-0000-000000000001', name: 'Studierendenparlament' };
const HHA: CalendarGremium = { id: 'g0000000-0000-0000-0000-000000000002', name: 'Haushaltsausschuss' };
const GREMIEN: readonly CalendarGremium[] = [STUPA, HHA];

const ME: CalendarPerson = { id: 'p0000000-0000-0000-0000-000000000001', name: 'Dana Meier' };
const PEOPLE: readonly CalendarPerson[] = [
  ME,
  { id: 'p0000000-0000-0000-0000-000000000002', name: 'Jonas Weber' },
  { id: 'p0000000-0000-0000-0000-000000000003', name: 'Lea Schmid' },
  { id: 'p0000000-0000-0000-0000-000000000004', name: 'Tim Koch' },
];

/** The day `offset` days from today. */
function day(offset: number): string {
  const now = new Date();
  return isoDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset));
}

function appointment(
  n: number,
  title: string,
  from: number,
  to: number,
  times: readonly [string, string] | null,
  more: Partial<Appointment> = {},
): Appointment {
  return {
    id: `a0000000-0000-0000-0000-00000000000${n}`,
    title,
    startsOn: day(from),
    endsOn: day(to),
    startTime: times ? `${times[0]}:00` : null,
    endTime: times ? `${times[1]}:00` : null,
    place: null,
    description: null,
    forAll: false,
    public: false,
    creator: ME,
    gremien: [],
    persons: [],
    answers: [],
    myAnswer: null,
    invited: false,
    canEdit: true,
    ...more,
  };
}

function initialAppointments(): readonly Appointment[] {
  return [
    appointment(1, 'Jour fixe Finanzreferat', 0, 0, ['14:00', '15:30'], {
      place: 'AStA-Büro',
      description: 'Abstimmung der offenen Buchungen und der Anträge für die nächste Sitzung.',
      creator: PEOPLE[1],
      gremien: [HHA],
      answers: [
        { principalId: PEOPLE[1].id, name: PEOPLE[1].name, answer: 'accept' },
        { principalId: PEOPLE[2].id, name: PEOPLE[2].name, answer: 'tentative' },
      ],
      invited: true,
      canEdit: false,
    }),
    appointment(2, 'Klausurtagung', 6, 8, null, { place: 'Jugendherberge Tübingen', gremien: [STUPA], invited: true }),
    appointment(3, 'Sprechstunde', -1, -1, ['09:30', '11:00'], { place: 'AStA-Büro' }),
    appointment(4, 'Gespräch mit dem Rektorat', -6, -6, ['10:00', '11:00'], {
      place: 'Gebäude 3, Raum 101',
      forAll: true,
      creator: PEOPLE[3],
      canEdit: false,
    }),
    appointment(5, 'Kurzer Abgleich', 0, 0, ['14:30', '14:45'], { persons: [PEOPLE[2]] }),
    appointment(6, 'Vollversammlung', 7, 7, ['14:00', '16:00'], {
      place: 'Aula',
      description: 'Offen für alle Studierenden. Bericht des AStA und Aussprache.',
      forAll: true,
      public: true,
      creator: PEOPLE[3],
      canEdit: false,
    }),
  ];
}

/** The Termine of the demo, and the number of the created ones for their ids. */
const appointments = signal(initialAppointments());
const created = signal(0);

function entryOf(a: Appointment): CalendarEntry {
  return {
    kind: 'appointment',
    id: a.id,
    title: a.title,
    startsOn: a.startsOn,
    endsOn: a.endsOn,
    startTime: a.startTime,
    endTime: a.endTime,
    place: a.place,
    source: a.gremien[0]?.name ?? null,
    gremiumIds: a.gremien.map((g) => g.id),
    mine: a.invited || a.creator?.id === ME.id,
    myAnswer: a.myAnswer,
  };
}

function other(
  kind: CalendarEntry['kind'],
  n: number,
  title: string,
  from: number,
  to: number,
  times: readonly [string, string | null] | null,
  source: string,
  more: Partial<CalendarEntry> = {},
): CalendarEntry {
  return {
    kind,
    id: `e0000000-0000-0000-0000-00000000000${n}`,
    title,
    startsOn: day(from),
    endsOn: day(to),
    startTime: times ? `${times[0]}:00` : null,
    endTime: times?.[1] ? `${times[1]}:00` : null,
    place: null,
    source,
    gremiumIds: [],
    mine: false,
    myAnswer: null,
    ...more,
  };
}

function fixed(): readonly CalendarEntry[] {
  return [
    other('meeting', 1, '35. Sitzung des Studierendenparlaments', 1, 1, ['18:00', '20:00'], STUPA.name, {
      gremiumIds: [STUPA.id],
    }),
    other('meeting', 2, '12. Sitzung des Haushaltsausschusses', 13, 13, ['17:30', null], HHA.name, {
      gremiumIds: [HHA.id],
    }),
    other('card', 3, 'Angebot Technik einholen', 0, 0, null, 'AStA-Board', { mine: true }),
    other('card', 4, 'Plakate drucken', 2, 2, null, 'Ersti-Wochenende'),
    other('card', 5, 'Abrechnung Ersti-Woche', 9, 9, null, 'AStA-Board', { gremiumIds: [STUPA.id] }),
    other('event', 6, 'Ersti-Wochenende', 16, 18, null, 'Ersti-Wochenende', { place: 'Schwäbische Alb' }),
    other('event', 7, 'Infoabend Wahlen', 2, 2, ['19:00', '20:30'], 'AStA-Board', { place: 'Aula' }),
  ];
}

/** The time `minutes` before now as an ISO instant. */
function ago(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function initialCalendars(): readonly ExternalCalendar[] {
  return [
    {
      id: 'c0000000-0000-0000-0000-000000000001',
      name: 'Hochschulkalender',
      url: 'https://www.reutlingen-university.de/termine/semester.ics',
      gremiumId: null,
      gremiumName: null,
      intervalMinutes: 1440,
      lastAttemptAt: ago(55),
      lastSuccessAt: ago(55),
      lastError: null,
      entryCount: 42,
    },
    {
      id: 'c0000000-0000-0000-0000-000000000002',
      name: 'Senatstermine',
      url: 'https://cloud.example.org/remote.php/dav/public-calendars/k3Qz/?export',
      gremiumId: STUPA.id,
      gremiumName: STUPA.name,
      intervalMinutes: 60,
      lastAttemptAt: ago(12),
      lastSuccessAt: ago(12),
      lastError: null,
      entryCount: 9,
    },
    {
      id: 'c0000000-0000-0000-0000-000000000003',
      name: 'Raumbelegung AStA-Büro',
      url: 'https://raum.example.org/asta/belegung.ics',
      gremiumId: HHA.id,
      gremiumName: HHA.name,
      intervalMinutes: 15,
      lastAttemptAt: ago(4),
      lastSuccessAt: ago(60 * 53),
      lastError: 'timeout',
      entryCount: 17,
    },
  ];
}

const calendars = signal(initialCalendars());

/** The external entries of the demo: the dialog reads the description from here. */
function externalEntries(): readonly ExternalEntry[] {
  const entry = (
    n: number,
    title: string,
    from: number,
    to: number,
    times: readonly [string, string] | null,
    calendar: string,
    place: string | null,
    description: string | null,
  ): ExternalEntry => ({
    id: `x0000000-0000-0000-0000-00000000000${n}`,
    title,
    startsOn: day(from),
    endsOn: day(to),
    startTime: times ? `${times[0]}:00` : null,
    endTime: times ? `${times[1]}:00` : null,
    place,
    description,
    calendar,
  });
  return [
    entry(1, 'Senatssitzung', 5, 5, ['14:00', '17:00'], 'Senatstermine', 'Gebäude 3, Raum 113', 'Öffentlicher Teil ab 14:00 Uhr.\n\nTagesordnung im Intranet.'),
    entry(2, 'Vorlesungsfreie Zeit', 20, 24, null, 'Hochschulkalender', null, null),
    entry(3, 'Rückmeldefrist', -3, -3, null, 'Hochschulkalender', null, 'Frist für die Rückmeldung zum Sommersemester.'),
  ];
}

function externalEntryOf(e: ExternalEntry): CalendarEntry {
  return {
    kind: 'external',
    id: e.id,
    title: e.title,
    startsOn: e.startsOn,
    endsOn: e.endsOn,
    startTime: e.startTime,
    endTime: e.endTime,
    place: e.place,
    source: e.calendar,
    gremiumIds: e.calendar === 'Senatstermine' ? [STUPA.id] : [],
    mine: false,
    myAnswer: null,
  };
}

function calendarFrom(id: string, body: ExternalCalendarInput, before: ExternalCalendar | null): ExternalCalendar {
  return {
    id,
    name: body.name.trim(),
    url: body.url,
    gremiumId: body.gremiumId,
    gremiumName: GREMIEN.find((g) => g.id === body.gremiumId)?.name ?? null,
    intervalMinutes: body.intervalMinutes,
    lastAttemptAt: before?.lastAttemptAt ?? null,
    lastSuccessAt: before?.lastSuccessAt ?? null,
    lastError: before?.lastError ?? null,
    entryCount: before?.entryCount ?? 0,
  };
}

/** Answer a route of the admin page `Kalender`, or null for an unknown path. */
function mockExternalCalendars(method: string, tail: string, body: unknown): MockCalendarReply | null {
  if (tail === '') {
    if (method === 'GET') return { status: 200, body: calendars() };
    if (method !== 'POST') return null;
    created.update((n) => n + 1);
    const fresh = calendarFrom(
      `c0000000-0000-0000-0000-0000000001${String(created()).padStart(2, '0')}`,
      body as ExternalCalendarInput,
      null,
    );
    calendars.update((list) => [...list, fresh]);
    return { status: 201, body: fresh };
  }
  const match = /^\/([^/]+)(\/fetch)?$/.exec(tail);
  const current = match ? calendars().find((c) => c.id === match[1]) : undefined;
  if (!match || !current) return null;
  if (match[2]) {
    if (method !== 'POST') return null;
    const next = { ...current, lastAttemptAt: ago(0), lastSuccessAt: ago(0), lastError: null };
    calendars.update((list) => list.map((c) => (c.id === next.id ? next : c)));
    return { status: 200, body: next };
  }
  switch (method) {
    case 'PUT': {
      const next = calendarFrom(current.id, body as ExternalCalendarInput, current);
      calendars.update((list) => list.map((c) => (c.id === next.id ? next : c)));
      return { status: 200, body: next };
    }
    case 'DELETE':
      calendars.update((list) => list.filter((c) => c.id !== current.id));
      return { status: 204, body: null };
    default:
      return null;
  }
}

function all(): readonly CalendarEntry[] {
  return [...fixed(), ...appointments().map(entryOf), ...externalEntries().map(externalEntryOf)].sort(
    (a, b) => a.startsOn.localeCompare(b.startsOn) || (a.startTime ?? '').localeCompare(b.startTime ?? ''),
  );
}

function fromInput(id: string, body: AppointmentInput, before: Appointment | null): Appointment {
  const moved =
    !!before &&
    (before.startsOn !== body.startsOn ||
      before.endsOn !== body.endsOn ||
      before.startTime !== body.startTime ||
      before.endTime !== body.endTime);
  return {
    id,
    title: body.title,
    startsOn: body.startsOn,
    endsOn: body.endsOn,
    startTime: body.startTime,
    endTime: body.endTime,
    place: body.place,
    description: body.description,
    forAll: body.forAll,
    public: body.public,
    creator: before?.creator ?? ME,
    gremien: GREMIEN.filter((g) => body.gremiumIds.includes(g.id)),
    persons: PEOPLE.filter((p) => body.principalIds.includes(p.id)),
    answers: moved ? [] : (before?.answers ?? []),
    myAnswer: moved ? null : (before?.myAnswer ?? null),
    invited: before?.invited ?? false,
    canEdit: true,
  };
}

/** The Termin with the answer of the demo person. */
function answered(a: Appointment, answer: AnswerKey): Appointment {
  return {
    ...a,
    myAnswer: answer,
    answers: [
      ...a.answers.filter((row) => row.principalId !== ME.id),
      { principalId: ME.id, name: ME.name, answer },
    ],
  };
}

/** The entries of the public calendar: the meetings and the public Termine, without a Gremium for a Termin. */
function publicEntries(): readonly CalendarEntry[] {
  return [
    ...fixed().filter((e) => e.kind === 'meeting'),
    ...appointments()
      .filter((a) => a.public)
      .map((a) => ({ ...entryOf(a), source: null, gremiumIds: [], mine: false, myAnswer: null })),
  ];
}

/** Answer a route of the public calendar (`/public/calendar/…`), or null for an unknown path. */
function mockPublicCalendar(tail: string, params: { get(name: string): string | null }): MockCalendarReply | null {
  if (tail === 'committees') return { status: 200, body: [STUPA, HHA] };
  if (tail === 'entries') {
    const from = params.get('from') ?? '';
    const to = params.get('to') ?? '';
    return { status: 200, body: { items: publicEntries().filter((e) => e.startsOn <= to && e.endsOn >= from) } };
  }
  if (tail === 'search') {
    const q = (params.get('q') ?? '').trim().toLowerCase();
    const items = q.length < 2 ? [] : publicEntries().filter((e) => e.title.toLowerCase().includes(q));
    return { status: 200, body: { items } };
  }
  const id = tail.split('/')[1] ?? '';
  if (tail.startsWith('appointments/')) {
    const a = appointments().find((row) => row.public && row.id === id);
    const body: PublicAppointment | null = a
      ? {
          id: a.id,
          title: a.title,
          startsOn: a.startsOn,
          endsOn: a.endsOn,
          startTime: a.startTime,
          endTime: a.endTime,
          place: a.place,
          description: a.description,
        }
      : null;
    return body ? { status: 200, body } : null;
  }
  const meeting = tail.startsWith('meetings/') ? fixed().find((e) => e.kind === 'meeting' && e.id === id) : undefined;
  const body: PublicMeeting | null = meeting
    ? {
        id: meeting.id,
        title: meeting.title,
        day: meeting.startsOn,
        startTime: meeting.startTime,
        endTime: meeting.endTime,
        gremium: meeting.source ?? '',
        tops: ['Begrüßung und Feststellung der Beschlussfähigkeit', 'Bericht des AStA', 'Haushaltsplan 2027', 'Verschiedenes'],
        protocolId: null,
      }
    : null;
  return body ? { status: 200, body } : null;
}

/** Answer a Kalender route, or null for a path that this module does not know. */
export function mockCalendar(
  method: string,
  path: string,
  params: { get(name: string): string | null },
  body: unknown,
): MockCalendarReply | null {
  const open = path.split('/public/calendar/')[1];
  if (open !== undefined) return method === 'GET' ? mockPublicCalendar(open, params) : null;
  const admin = path.split('/admin/calendars')[1];
  if (admin !== undefined) return mockExternalCalendars(method, admin, body);
  const tail = path.split('/calendar/')[1] ?? '';
  if (method === 'GET' && tail.startsWith('external/')) {
    const found = externalEntries().find((e) => e.id === tail.slice('external/'.length));
    return found ? { status: 200, body: found } : null;
  }
  if (method === 'GET' && tail === 'entries') {
    const from = params.get('from') ?? '';
    const to = params.get('to') ?? '';
    const mine = params.get('mine') === 'true';
    const items = all().filter((e) => e.startsOn <= to && e.endsOn >= from && (!mine || e.kind === 'meeting' || e.kind === 'external' || e.mine));
    return { status: 200, body: { items } };
  }
  if (method === 'GET' && tail === 'search') {
    const q = (params.get('q') ?? '').trim().toLowerCase();
    return { status: 200, body: { items: q.length < 2 ? [] : all().filter((e) => e.title.toLowerCase().includes(q)) } };
  }
  if (method === 'GET' && tail === 'people') {
    const q = (params.get('q') ?? '').trim().toLowerCase();
    return { status: 200, body: q.length < 2 ? [] : PEOPLE.filter((p) => p.name.toLowerCase().includes(q)) };
  }
  if (method === 'POST' && tail === 'appointments') {
    created.update((n) => n + 1);
    const id = `a0000000-0000-0000-0000-0000000001${String(created()).padStart(2, '0')}`;
    const fresh = fromInput(id, body as AppointmentInput, null);
    appointments.update((list) => [...list, fresh]);
    return { status: 201, body: fresh };
  }
  const match = /^appointments\/([^/]+)(\/answer)?$/.exec(tail);
  const current = match ? appointments().find((a) => a.id === match[1]) : undefined;
  if (!match || !current) return null;
  if (match[2]) {
    if (method !== 'PUT') return null;
    const next = answered(current, (body as { answer: AnswerKey }).answer);
    appointments.update((list) => list.map((a) => (a.id === next.id ? next : a)));
    return { status: 200, body: next };
  }
  switch (method) {
    case 'GET':
      return { status: 200, body: current };
    case 'PUT': {
      const next = fromInput(current.id, body as AppointmentInput, current);
      appointments.update((list) => list.map((a) => (a.id === next.id ? next : a)));
      return { status: 200, body: next };
    }
    case 'DELETE':
      appointments.update((list) => list.filter((a) => a.id !== current.id));
      return { status: 204, body: null };
    default:
      return null;
  }
}

/** Put the demo data back, for a test. */
export function resetMockCalendar(): void {
  appointments.set(initialAppointments());
  calendars.set(initialCalendars());
  created.set(0);
}
