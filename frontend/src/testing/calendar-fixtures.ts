import type { Appointment, CalendarEntry } from '@core/api/calendar.service';

/** An entry of the Kalender: an all-day Termin on 2026-11-11 unless `over` says otherwise. */
export function calendarEntry(id: string, over: Partial<CalendarEntry> = {}): CalendarEntry {
  return {
    kind: 'appointment',
    id,
    title: `Eintrag ${id}`,
    startsOn: '2026-11-11',
    endsOn: '2026-11-11',
    startTime: null,
    endTime: null,
    place: null,
    source: null,
    gremiumIds: [],
    mine: false,
    myAnswer: null,
    ...over,
  };
}

/** A Termin on 2026-11-11 from 14:00 to 15:30 that the caller created. */
export function appointment(over: Partial<Appointment> = {}): Appointment {
  return {
    id: 'a-1',
    title: 'Jour fixe',
    startsOn: '2026-11-11',
    endsOn: '2026-11-11',
    startTime: '14:00:00',
    endTime: '15:30:00',
    place: 'AStA-Büro',
    description: 'Offene Buchungen',
    forAll: false,
    creator: { id: 'p-1', name: 'Dana Meier' },
    gremien: [{ id: 'g-1', name: 'Haushaltsausschuss' }],
    persons: [{ id: 'p-2', name: 'Jonas Weber' }],
    answers: [{ principalId: 'p-2', name: 'Jonas Weber', answer: 'accept' }],
    myAnswer: null,
    invited: true,
    canEdit: true,
    ...over,
  };
}
