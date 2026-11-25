import type { EventDetail, EventItem } from '@core/api/events.service';

/** One Event of the page "Veranstaltungen" with its detail; `over` changes fields. */
export function eventDetail(over: Partial<EventDetail> = {}): EventDetail {
  return {
    id: 'e-1',
    number: 'V-7K3QX9MD',
    teamId: 't-1',
    teamName: 'Kultur',
    status: 'planned',
    phase: 'open',
    title: 'Erstiparty',
    descriptionMd: 'Party im **Hof**',
    startsOn: '2026-11-20',
    startTime: '19:00:00',
    endsOn: '2026-11-21',
    endTime: '02:00:00',
    place: 'Hof',
    participants: 300,
    seriesId: 's-1',
    seriesName: 'Erstiparty',
    shopUrl: 'https://shop.example.org/erstiparty',
    totals: { requested: '500.00', approved: '400.00', expenses: '250.00', income: '562.00', balance: '312.00' },
    version: 1,
    createdAt: '2026-11-01T10:00:00Z',
    updatedAt: '2026-11-01T10:00:00Z',
    decisions: [],
    editions: [],
    hiddenEditions: 0,
    ...over,
  };
}

/** One row of the list of the Events. */
export function eventItem(over: Partial<EventItem> = {}): EventItem {
  const { decisions: _d, editions: _e, hiddenEditions: _h, ...item } = eventDetail(over);
  return item;
}
