import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { GremienApiService } from '@core/api/gremien.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import {
  GREMIEN_TEST_NOW,
  gremienApiMock,
  gremiumMeeting,
} from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { GREMIEN_NOW } from '../gremien.store';
import { GremiumMeetingsComponent } from './gremium-meetings.component';

const MEETINGS = [
  gremiumMeeting({ id: 'm-p1', title: '34. Sitzung', date: '2026-10-20', status: 'planned', protocolStatus: null }),
  gremiumMeeting({ id: 'm-p2', title: '35. Sitzung', date: '2026-11-03', status: 'planned', protocolStatus: null }),
  gremiumMeeting({ id: 'm-p3', title: 'Klausur', date: null, startTime: null, status: 'planned', protocolStatus: null }),
  gremiumMeeting({ id: 'm-1', title: '33. Sitzung', date: '2026-10-06', protocolStatus: 'final' }),
  gremiumMeeting({ id: 'm-2', title: '32. Sitzung', date: '2026-09-29', protocolStatus: 'draft' }),
  gremiumMeeting({ id: 'm-3', title: '31. Sitzung', date: '2026-09-15', protocolStatus: 'rendering' }),
  gremiumMeeting({ id: 'm-4', title: '20. Sitzung', date: '2025-11-10', protocolStatus: null }),
  gremiumMeeting({ id: 'm-5', title: 'Alte Sitzung', date: null, protocolStatus: null }),
];

async function setup(opts: { api?: ReturnType<typeof gremienApiMock>; phone?: boolean } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.phone ? [MEDIA.phone] : []));
  const api = opts.api ?? gremienApiMock({ meetings: jest.fn(() => of(MEETINGS)) });
  const count = jest.fn();
  const view = await render(GremiumMeetingsComponent, {
    inputs: { gremiumId: 'g-1' },
    on: { count },
    providers: [
      provideRouter([]),
      { provide: GremienApiService, useValue: api },
      { provide: GREMIEN_NOW, useValue: GREMIEN_TEST_NOW },
    ],
  });
  return { ...view, api, count, restore, cmp: view.fixture.componentInstance };
}

describe('GremiumMeetingsComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  it('groups the coming meetings first, then the closed ones by month', async () => {
    const view = await setup();
    restore = view.restore;
    expect(view.api.meetings).toHaveBeenCalledWith('g-1');
    expect(view.count).toHaveBeenCalledWith(MEETINGS.length);
    const heads = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent?.replace(/\s+/g, ' ').trim());
    expect(heads).toEqual(['Kommend 3', 'Oktober 2026', 'September 2026', 'November 2025', 'Ohne Datum']);
    const titles = view.cmp.groups()[0].rows.map((r) => r.meeting.id);
    expect(titles).toEqual(['m-p1', 'm-p2', 'm-p3']);
    const closed = view.cmp.groups()[1].rows[0];
    expect(closed.attendance).toBe('24/31');
    expect(closed.attendanceLabel).toBe('24 von 31 anwesend');
    expect(closed.sub).toContain('18:00–20:30');
    expect(closed.status.key).toBe('gremien.meetings.protocolFinal');
    expect(view.cmp.groups()[2].rows.map((r) => r.status.key)).toEqual([
      'gremien.meetings.protocolDraft',
      'gremien.meetings.protocolRendering',
    ]);
    expect(view.cmp.groups()[3].rows[0].status.key).toBe('gremien.meetings.protocolMissing');
    expect(view.cmp.groups()[0].rows[0].status.key).toBe('meetings.status.planned');
    expect(screen.getByRole('link', { name: /In „Sitzungen“ öffnen/ }).getAttribute('href')).toBe('/meetings');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('filters by the range and by the protocol', async () => {
    const view = await setup();
    restore = view.restore;
    const ids = () => view.cmp.groups().flatMap((g) => g.rows.map((r) => r.meeting.id));

    view.cmp.setRange('upcoming');
    expect(ids()).toEqual(['m-p1', 'm-p2', 'm-p3']);
    expect(view.cmp.rangeText()).toBe('Zeitraum: Kommend');

    view.cmp.setRange('past6');
    expect(ids()).toEqual(['m-1', 'm-2', 'm-3']);
    view.cmp.setRange('past12');
    expect(ids()).toEqual(['m-1', 'm-2', 'm-3', 'm-4']);
    view.cmp.setRange('');

    view.cmp.setProtocol('final');
    expect(ids()).toEqual(['m-1']);
    expect(view.cmp.protocolText()).toBe('Protokoll: Protokoll final');
    view.cmp.setProtocol('draft');
    expect(ids()).toEqual(['m-2', 'm-3']);
    view.cmp.setProtocol('none');
    expect(ids()).toEqual(['m-p1', 'm-p2', 'm-p3', 'm-4', 'm-5']);

    view.cmp.setRange('upcoming');
    view.cmp.setProtocol('final');
    view.fixture.detectChanges();
    expect(view.cmp.filterActive()).toBe(true);
    expect(screen.getByText('Keine Sitzung passt zu den Filtern.')).toBeTruthy();
  });

  it('orders by date and time, puts a meeting without a date last and survives an odd chip value', async () => {
    const rows = [
      gremiumMeeting({ id: 'c-x', date: null, protocolStatus: null }),
      gremiumMeeting({ id: 'c-1', date: '2026-10-06', endTime: null }),
      gremiumMeeting({ id: 'c-y', date: null, protocolStatus: null }),
      gremiumMeeting({ id: 'p-n', date: null, startTime: null, status: 'planned' }),
      gremiumMeeting({ id: 'p-b', date: '2026-10-20', startTime: null, status: 'live' }),
      gremiumMeeting({ id: 'p-a', date: '2026-10-20', startTime: '17:00:00', status: 'planned' }),
      gremiumMeeting({ id: 'p-m', date: null, startTime: null, status: 'planned' }),
    ];
    const view = await setup({ api: gremienApiMock({ meetings: jest.fn(() => of(rows)) }) });
    restore = view.restore;
    expect(view.cmp.groups()[0].rows.map((r) => r.meeting.id)).toEqual(['p-b', 'p-a', 'p-n', 'p-m']);
    expect(view.cmp.groups()[0].rows[0].status.key).toBe('meetings.status.live');
    const closed = view.cmp.groups()[1].rows[0];
    expect(closed.meeting.id).toBe('c-1');
    expect(closed.sub).toContain('18:00');
    expect(closed.sub).not.toContain('–');
    expect(view.cmp.groups()[2].rows.map((r) => r.meeting.id)).toEqual(['c-x', 'c-y']);
    view.cmp.setRange('odd');
    expect(view.cmp.rangeText()).toBe('Zeitraum: ');
  });

  it('shows the empty state without meetings', async () => {
    const view = await setup({ api: gremienApiMock({ meetings: jest.fn(() => of([])) }) });
    restore = view.restore;
    expect(screen.getByText('Noch keine Sitzungen')).toBeTruthy();
  });

  it('reports a failed read and reads again', async () => {
    const meetings = jest.fn((): ReturnType<GremienApiService['meetings']> => throwError(() => new Error('x')));
    const view = await setup({ api: gremienApiMock({ meetings }) });
    restore = view.restore;
    expect(screen.getByRole('alert')).toHaveTextContent('Die Sitzungen konnten nicht geladen werden.');
    meetings.mockReturnValue(of(MEETINGS));
    screen.getByRole('button', { name: 'Erneut versuchen' }).click();
    view.fixture.detectChanges();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(meetings).toHaveBeenCalledTimes(2);
  });

  it('shows only the date and the count on a phone', async () => {
    const view = await setup({ phone: true });
    restore = view.restore;
    const closed = view.cmp.groups()[1].rows[0];
    expect(closed.sub).not.toContain('18:00');
    expect(screen.queryByRole('link', { name: /In „Sitzungen“ öffnen/ })).toBeNull();
    expect(screen.queryByText('anwesend')).toBeNull();
    expect(view.cmp.groups()[0].rows[2].sub).toBe('');
  });
});
