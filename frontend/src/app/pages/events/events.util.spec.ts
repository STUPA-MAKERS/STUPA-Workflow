import { eventDetail } from '../../../testing/event-fixtures';
import { eventBody, eventFormValue, eventQuery, eventWhen, followUpValue, isSegment, shortTime } from './events.util';

describe('events.util', () => {
  it('reads the filter of the screen', () => {
    expect(eventQuery({ search: '  fest ', filters: { team: 't-1', series: '', segment: 'past' } } as never)).toEqual({
      team: 't-1',
      series: undefined,
      q: 'fest',
    });
    expect(isSegment('void')).toBe(true);
    expect(isSegment('open')).toBe(false);
  });

  it('writes the days and the times of an Event', () => {
    const e = eventDetail();
    expect(eventWhen(e, 'de-DE')).toMatch(/^20\..*21\.11\.2026, 19:00–02:00$/);
    expect(eventWhen({ ...e, startTime: null, endTime: null }, 'de-DE')).not.toContain(',');
    expect(eventWhen({ ...e, endTime: null }, 'de-DE')).toMatch(/, 19:00$/);
    expect(eventWhen({ ...e, startTime: null }, 'de-DE')).toMatch(/, –02:00$/);
    expect(eventWhen({ ...e, startsOn: null }, 'de-DE')).toBeNull();
    expect(shortTime(null)).toBeNull();
  });

  it('fills the form of an Event and builds the body', () => {
    const value = eventFormValue(eventDetail());
    expect(value).toMatchObject({ teamId: 't-1', startTime: '19:00', endTime: '02:00', participants: 300 });
    expect(eventBody({ ...value, participants: '12.7', status: '' }, 's-1')).toEqual({
      teamId: 't-1',
      title: 'Erstiparty',
      descriptionMd: 'Party im **Hof**',
      startsOn: '2026-11-20',
      startTime: '19:00:00',
      endsOn: '2026-11-21',
      endTime: '02:00:00',
      place: 'Hof',
      participants: 12,
      seriesId: 's-1',
      shopUrl: 'https://shop.example.org/erstiparty',
    });
    const empty = eventBody(eventFormValue(null), null);
    expect(empty).toMatchObject({ title: '', startsOn: null, startTime: null, participants: null, shopUrl: null });
    expect(eventBody({ ...eventFormValue(null), participants: 'x', status: 'settled', startTime: '18:30:00' }, null)).toMatchObject({
      participants: null,
      status: 'settled',
      startTime: '18:30:00',
    });
  });

  /** §F/collaboration/events/003030: the plan is copied, the dates and the status are not. */
  it('copies the plan of an Event for the next edition', () => {
    const value = followUpValue(eventDetail());
    expect(value).toMatchObject({
      teamId: 't-1',
      title: 'Erstiparty',
      descriptionMd: 'Party im **Hof**',
      place: 'Hof',
      shopUrl: 'https://shop.example.org/erstiparty',
      seriesId: 's-1',
      startsOn: '',
      endsOn: '',
      startTime: '',
      endTime: '',
      status: '',
      participants: null,
    });
    expect(followUpValue(eventDetail({ descriptionMd: null, place: null, shopUrl: null, seriesId: null }))).toMatchObject({
      descriptionMd: '',
      place: '',
      shopUrl: '',
      seriesId: '',
    });
  });
});
