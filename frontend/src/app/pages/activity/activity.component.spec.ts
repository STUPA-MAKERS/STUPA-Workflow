import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
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
import { ActivityComponent, KIND_ICON, groupByDay } from './activity.component';

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

async function setup(answers: Array<() => Observable<ActivityPage>>) {
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
  const r = await render(ActivityComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: ActivityApiService, useValue: api },
      { provide: RailStatusService, useValue: rail },
    ],
  });
  return { ...r, api, rail, queries, cmp: r.fixture.componentInstance };
}

describe('ActivityComponent', () => {
  afterEach(() => localStorage.clear());

  /** § F/collaboration/activity/001301 and 001302: the start page parts above the list. */
  it('shows "Antrag stellen" in the header and the live cards above the list', async () => {
    const { container } = await setup([() => of(page([entry()]))]);
    const apply = screen.getByRole('link', { name: /Antrag stellen/ });
    expect(apply).toHaveAttribute('href', '/apply');
    expect(apply.closest('app-page-header')).not.toBeNull();
    expect(container.querySelector('app-fab')).toBeNull();
    const live = container.querySelector('app-live-cards');
    expect(live?.closest('.act__scroll')).not.toBeNull();
  });

  it('shows "Antrag stellen" as the floating button on a phone', async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query === '(max-width: 767.98px)',
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    try {
      const { container } = await setup([() => of(page([entry()]))]);
      expect(container.querySelector('app-page-header a[href="/apply"]')).toBeNull();
      expect(container.querySelector('app-fab')).not.toBeNull();
    } finally {
      window.matchMedia = original;
    }
  });

  it('groups the rows by day and links each row to its item', async () => {
    const { api, rail } = await setup([
      () =>
        of(
          page([
            entry({ isNew: true }),
            entry({ id: 'e2', at: at(1), itemKind: 'application', itemTitle: null, change: 'application.edited', actor: { kind: 'system' } }),
            entry({ id: 'e3', at: at(9), itemKind: 'ticket', change: 'ticket.status', status: 'new', actor: { kind: 'person', name: null } }),
          ]),
        ),
    ]);
    expect(screen.getByText('Heute')).toBeInTheDocument();
    expect(screen.getByText('Gestern')).toBeInTheDocument();
    expect(screen.getByText('Bob Berg · Kommentar: Danke')).toBeInTheDocument();
    expect(screen.getByText('Ohne Titel')).toBeInTheDocument();
    expect(screen.getByText('System · Angaben geändert')).toBeInTheDocument();
    expect(screen.getByText('Ohne Namen · Status: Neu')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Flyer drucken/ })[0]).toHaveAttribute('href', '/tasks/todo/c1');
    expect(screen.getAllByText(/Neu:/).length).toBe(1);
    expect(rail.activitySeen).toHaveBeenCalledTimes(1);
    expect(api.markSeen).toHaveBeenCalledWith('2026-11-17T10:00:00Z');
  });

  it('names the actor by kind and the own actions as "Du"', async () => {
    const { cmp } = await setup([]);
    expect(cmp.actor(entry({ own: true }))).toBe('Du');
    expect(cmp.actor(entry({ actor: { kind: 'applicant' } }))).toBe('Antragsteller:in');
    expect(cmp.actor(entry({ actor: { kind: 'committee' } }))).toBe('Gremium');
    expect(cmp.change(entry({ itemKind: 'meeting', change: 'meeting.status', status: 'live' }))).toBe('Status: Live');
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
    const { cmp, fixture, queries, api } = await setup([() => of(page([])), () => of(page([])), () => of(page([]))]);
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
    const { fixture } = await setup([() => throwError(() => new Error('down')), () => of(page([entry()]))]);
    expect(fixture.componentInstance.error()).toBe(true);
    retryLoadError();
    fixture.detectChanges();
    expect(screen.getByText('Flyer drucken')).toBeInTheDocument();
  });

  it('works when the browser blocks the storage', async () => {
    const realGet = Storage.prototype.getItem;
    const realSet = Storage.prototype.setItem;
    const get = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key: string) {
      if (key === ActivityComponent.OWN_KEY) throw new Error('blocked');
      return realGet.call(this, key);
    });
    const set = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
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

describe('groupByDay', () => {
  const t = (key: TranslationKey): string => key;
  const now = new Date(2026, 10, 18, 12, 0);

  it('labels today, yesterday and older days and keeps the order', () => {
    const rows = [
      entry({ id: 'a', at: new Date(2026, 10, 18, 9).toISOString() }),
      entry({ id: 'b', at: new Date(2026, 10, 18, 8).toISOString() }),
      entry({ id: 'c', at: new Date(2026, 10, 17, 9).toISOString() }),
      entry({ id: 'd', at: new Date(2026, 10, 16, 9).toISOString() }),
    ];
    const days = groupByDay(rows, 'de', t, now);
    expect(days.map((d) => d.label)).toEqual(['activity.today', 'activity.yesterday', 'Mo, 16.11.2026']);
    expect(days[0].entries.map((e) => e.id)).toEqual(['a', 'b']);
  });
});
