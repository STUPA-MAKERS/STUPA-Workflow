import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { PushDeviceService, type PushSupport } from '@core/pwa/push-device.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError, type Observable } from 'rxjs';
import {
  ActivityApiService,
  type ActivityEntry,
  type ActivityPage,
  type ActivityQuery,
} from '@core/api/activity.service';
import type { TranslationKey } from '@core/i18n/translations';
import { RailStatusService } from '../../layout/rail-status.service';
import { retryLoadError } from '../../../testing/load-error';
import { ActivityComponent, KIND_ICON, dayLabel, splitUrl } from './activity.component';

const NOW = new Date();
const at = (daysAgo: number, hour = 10): string =>
  new Date(NOW.getFullYear(), NOW.getMonth(), NOW.getDate() - daysAgo, hour, 5).toISOString();

function entry(over: Partial<ActivityEntry> = {}): ActivityEntry {
  return {
    id: 'e1',
    at: at(0),
    itemKind: 'todo',
    itemId: 'c1',
    itemTitle: 'Flyer drucken',
    url: '/tasks/todo/c1',
    change: 'comment',
    detail: 'Danke',
    status: null,
    actor: { kind: 'person', name: 'Bob Berg' },
    own: false,
    isNew: false,
    ...over,
  };
}

function page(entries: readonly ActivityEntry[], nextCursor: string | null = null): ActivityPage {
  return { entries, nextCursor, seenAt: null, readAt: '2026-11-17T10:00:00Z' };
}

/** The push state of the test device. */
interface PushMock {
  support: PushSupport;
  endpoint: string | null;
  enable: jest.Mock;
}

function pushDevice(o: Partial<PushMock> = {}) {
  return {
    support: jest.fn(() => o.support ?? 'unsupported'),
    endpoint: jest.fn(() => Promise.resolve(o.endpoint ?? null)),
    enable: o.enable ?? jest.fn(() => Promise.resolve({})),
  };
}

async function setup(answers: Array<() => Observable<ActivityPage>>, push: Partial<PushMock> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const queries: ActivityQuery[] = [];
  const api = {
    list: jest.fn((q: ActivityQuery) => {
      queries.push(q);
      const next = answers.shift();
      return next ? next() : of(page([]));
    }),
    markSeen: jest.fn(() => of(undefined)),
  };
  const rail = { activitySeen: jest.fn() };
  const device = pushDevice(push);
  const r = await render(ActivityComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: ActivityApiService, useValue: api },
      { provide: RailStatusService, useValue: rail },
      { provide: PushDeviceService, useValue: device },
    ],
  });
  return { ...r, api, rail, queries, device, cmp: r.fixture.componentInstance };
}

describe('ActivityComponent', () => {
  afterEach(() => localStorage.clear());

  /** § F/collaboration/notifications/002550 and F/collaboration/activity/001302. */
  it('shows the bell as the one action of the head, no "Antrag stellen", the live cards above the list', async () => {
    const { container } = await setup([() => of(page([entry()]))]);
    const bell = screen.getByRole('button', { name: 'Benachrichtigungen' });
    expect(bell.closest('app-page-header')).not.toBeNull();
    expect(screen.queryByRole('link', { name: /Antrag stellen/ })).toBeNull();
    expect(container.querySelector('app-fab')).toBeNull();
    const live = container.querySelector('app-live-cards');
    expect(live?.closest('.act__scroll')).not.toBeNull();
  });

  it('switches on push first when the device can take push and has none, then opens the settings', async () => {
    const { device, fixture } = await setup([() => of(page([]))], { support: 'ready' });
    const nav = jest
      .spyOn(fixture.debugElement.injector.get(Router), 'navigateByUrl')
      .mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Benachrichtigungen' }));
    await fixture.whenStable();
    expect(device.enable).toHaveBeenCalledTimes(1);
    expect(nav).toHaveBeenCalledWith('/account/notifications');
  });

  it('opens the settings although the browser refuses the permission', async () => {
    const enable = jest.fn(async () => {
      await Promise.resolve();
      throw new Error('denied');
    });
    const { fixture } = await setup([() => of(page([]))], { support: 'ready', enable });
    const nav = jest
      .spyOn(fixture.debugElement.injector.get(Router), 'navigateByUrl')
      .mockResolvedValue(true);
    await fixture.componentInstance.openNotifications();
    expect(enable).toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith('/account/notifications');
  });

  it.each([
    ['a device with push already', { support: 'ready', endpoint: 'https://fcm.googleapis.com/x' }],
    ['a device without push', { support: 'unsupported' }],
    ['blocked notifications', { support: 'blocked' }],
  ] as const)('opens the settings at once for %s', async (_name, push) => {
    const { device, fixture } = await setup([() => of(page([]))], push);
    const nav = jest
      .spyOn(fixture.debugElement.injector.get(Router), 'navigateByUrl')
      .mockResolvedValue(true);
    await fixture.componentInstance.openNotifications();
    expect(device.enable).not.toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith('/account/notifications');
  });

  it('asks for no permission while the feature push is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['push']));
    const { device, fixture } = await setup([() => of(page([]))], { support: 'ready' });
    localStorage.removeItem('ap.features.off');
    const nav = jest
      .spyOn(fixture.debugElement.injector.get(Router), 'navigateByUrl')
      .mockResolvedValue(true);
    await fixture.componentInstance.openNotifications();
    expect(device.enable).not.toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith('/account/notifications');
  });

  it('groups the rows by day and links each row to its item', async () => {
    const { api, rail } = await setup([
      () =>
        of(
          page([
            entry({ isNew: true }),
            entry({
              id: 'e2',
              at: at(1),
              itemKind: 'application',
              itemTitle: null,
              change: 'application.edited',
              actor: { kind: 'system' },
            }),
            entry({
              id: 'e3',
              at: at(9),
              itemKind: 'ticket',
              change: 'ticket.status',
              status: 'new',
              actor: { kind: 'person', name: null },
            }),
            entry({
              id: 'e4',
              at: at(9),
              itemTitle: 'Ersti-Gruppe anlegen',
              url: '/todos?card=c9',
              change: 'todo.archived',
            }),
          ]),
        ),
    ]);
    expect(screen.getByText('Heute')).toBeInTheDocument();
    expect(screen.getByText('Gestern')).toBeInTheDocument();
    expect(screen.getByText('Bob Berg · Kommentar: Danke')).toBeInTheDocument();
    expect(screen.getByText('Ohne Titel')).toBeInTheDocument();
    expect(screen.getByText('System · Angaben geändert')).toBeInTheDocument();
    expect(screen.getByText('Ohne Namen · Status: Neu')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Flyer drucken/ })[0]).toHaveAttribute(
      'href',
      '/tasks/todo/c1',
    );
    expect(screen.getAllByRole('link', { name: /Ersti-Gruppe anlegen/ })[0]).toHaveAttribute(
      'href',
      '/todos?card=c9',
    );
    expect(screen.getAllByText(/Neu:/).length).toBe(1);
    expect(rail.activitySeen).toHaveBeenCalledTimes(1);
    expect(api.markSeen).toHaveBeenCalledWith('2026-11-17T10:00:00Z');
  });

  it('names the actor by kind and the own actions as "Du"', async () => {
    const { cmp } = await setup([]);
    expect(cmp.actor(entry({ own: true }))).toBe('Du');
    expect(cmp.actor(entry({ actor: { kind: 'applicant' } }))).toBe('Antragsteller:in');
    expect(cmp.actor(entry({ actor: { kind: 'committee' } }))).toBe('Gremium');
    expect(
      cmp.change(entry({ itemKind: 'meeting', change: 'meeting.status', status: 'live' })),
    ).toBe('Status: Live');
    expect(cmp.change(entry({ change: 'todo.archived', detail: null }))).toBe('Archiviert');
    expect(cmp.icon(entry({ itemKind: 'meeting' }))).toBe(KIND_ICON.meeting);
  });

  it('says that nothing happened yet, and that a filter matches nothing', async () => {
    const { cmp, fixture, queries } = await setup([() => of(page([])), () => of(page([]))]);
    expect(screen.getByText('Noch keine Aktivität')).toBeInTheDocument();
    cmp.setKinds(['ticket']);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(screen.getByText('Keine Aktivität für diese Auswahl')).toBeInTheDocument();
    expect(queries.at(-1)?.kinds).toEqual(['ticket']);
  });

  /** Spec 001273: the choice of "Von" stays in this browser. */
  it('shows the own actions on request and keeps the choice', async () => {
    const { cmp, fixture, queries, api } = await setup([
      () => of(page([])),
      () => of(page([])),
      () => of(page([])),
    ]);
    expect(queries[0].own).toBe(false);
    cmp.setWho('own');
    fixture.detectChanges();
    await fixture.whenStable();
    expect(queries.at(-1)?.own).toBe(true);
    expect(localStorage.getItem(ActivityComponent.OWN_KEY)).toBe('1');
    cmp.setWho('');
    fixture.detectChanges();
    await fixture.whenStable();
    expect(localStorage.getItem(ActivityComponent.OWN_KEY)).toBeNull();
    expect(api.markSeen).toHaveBeenCalledTimes(1);
  });

  it('reads the stored choice at the start', async () => {
    localStorage.setItem(ActivityComponent.OWN_KEY, '1');
    const { queries } = await setup([]);
    expect(queries[0].own).toBe(true);
  });

  it('loads the next step at the end of the list and keeps the rows on a failed step', async () => {
    const more = new Subject<ActivityPage>();
    const { cmp, fixture, queries } = await setup([
      () => of(page([entry()], 'c1')),
      () => more,
      () => throwError(() => new Error('down')),
    ]);
    await userEvent.click(screen.getByRole('button', { name: /Mehr laden/ }));
    expect(queries.at(-1)?.cursor).toBe('c1');
    cmp.loadMore();
    expect(queries.length).toBe(2);
    more.next(page([entry({ id: 'e2', itemTitle: 'Saal buchen' })], 'c2'));
    fixture.detectChanges();
    expect(screen.getByText('Saal buchen')).toBeInTheDocument();
    cmp.loadMore();
    fixture.detectChanges();
    expect(cmp.loadingMore()).toBe(false);
    expect(cmp.entries().length).toBe(2);
    expect(cmp.cursor()).toBe('c2');
  });

  it('does not load more without a cursor', async () => {
    const { cmp, queries } = await setup([() => of(page([entry()]))]);
    cmp.loadMore();
    expect(queries.length).toBe(1);
    expect(screen.queryByRole('button', { name: /Mehr laden/ })).toBeNull();
  });

  it('shows a load error and loads again on retry', async () => {
    const { fixture } = await setup([
      () => throwError(() => new Error('down')),
      () => of(page([entry()])),
    ]);
    expect(fixture.componentInstance.error()).toBe(true);
    retryLoadError();
    fixture.detectChanges();
    expect(screen.getByText('Flyer drucken')).toBeInTheDocument();
  });

  it('works when the browser blocks the storage', async () => {
    const realGet = Storage.prototype.getItem;
    const realSet = Storage.prototype.setItem;
    const get = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(function (
      this: Storage,
      key: string,
    ) {
      if (key === ActivityComponent.OWN_KEY) throw new Error('blocked');
      return realGet.call(this, key);
    });
    const set = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
      this: Storage,
      key: string,
      value: string,
    ) {
      if (key === ActivityComponent.OWN_KEY) throw new Error('blocked');
      realSet.call(this, key, value);
    });
    try {
      const { cmp } = await setup([]);
      expect(cmp.own()).toBe(false);
      expect(() => cmp.setWho('own')).not.toThrow();
      expect(cmp.own()).toBe(true);
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });
});

describe('splitUrl', () => {
  it('splits the query off the path', () => {
    expect(splitUrl('/todos?card=c9')).toEqual({ path: '/todos', query: { card: 'c9' } });
    expect(splitUrl('/meetings/m1')).toEqual({ path: '/meetings/m1', query: null });
  });
});

describe('dayLabel', () => {
  const t = (key: TranslationKey): string => key;
  const now = new Date(2026, 10, 18, 12, 0);

  it('labels today, yesterday and older days', () => {
    const label = (d: Date): string => dayLabel(d.toISOString(), 'de', t, now);
    expect(label(new Date(2026, 10, 18, 9))).toBe('activity.today');
    expect(label(new Date(2026, 10, 17, 9))).toBe('activity.yesterday');
    expect(label(new Date(2026, 10, 16, 9))).toBe('Mo, 16.11.2026');
  });
});
