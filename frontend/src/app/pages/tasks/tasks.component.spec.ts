import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of, throwError } from 'rxjs';
import { screen, within } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { ApplicationListItem } from '@core/api/models';
import { ApplicationsPageService } from '../applications/applications-page.service';
import { TasksComponent } from './tasks.component';
import { TasksNoneComponent } from './tasks-none.component';

/** The detail of the outlet. The detail has its own spec; here only the route matters. */
@Component({ standalone: true, template: '<p>detail</p>' })
class DetailStub {}

const DAY = 86_400_000;
/** A fixed local "now" (4 Oct 2026, 09:00), so that no case depends on the time of the run. */
const NOW = new Date(2026, 9, 4, 9, 0).getTime();

function task(id: string, extra: Partial<ApplicationListItem> = {}): ApplicationListItem {
  return {
    id,
    typeId: 't1',
    title: 'Mein Antrag',
    state: { id: 's1', key: 's', label: 'In Prüfung', color: '#e8a33d', editAllowed: false, kind: 'vote' },
    gremiumId: null,
    amount: '1250.00',
    currency: 'EUR',
    createdAt: '2026-09-01T10:00:00Z',
    updatedAt: '2026-09-01T10:00:00Z',
    archivedAt: null,
    ...extra,
  };
}

const THREE = [
  task('a1', { title: 'Erster' }),
  task('a2', { title: 'Zweiter' }),
  task('a3', { title: 'Dritter', createdAt: '2026-08-10T10:00:00Z' }),
];

interface Opts {
  tasksError?: boolean;
  typesError?: boolean;
}

/**
 * Start the page at `url`. `answers` holds the answers of the task requests in order;
 * the last one repeats.
 */
async function start(url: string, answers: ApplicationListItem[][], opts: Opts = {}) {
  let call = 0;
  const listTasks = jest.fn(() => {
    if (opts.tasksError) return throwError(() => new Error('boom'));
    const answer = answers[Math.min(call, answers.length - 1)];
    call++;
    return of(answer);
  });
  const applicationTypes = opts.typesError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of([{ id: 't1', name: 'Förderantrag' }]));
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        {
          path: 'tasks',
          component: TasksComponent,
          children: [
            { path: '', component: TasksNoneComponent },
            { path: ':id', component: DetailStub },
          ],
        },
      ]),
      { provide: ApiClient, useValue: { listTasks, applicationTypes } },
    ],
  });
  const harness = await RouterTestingHarness.create();
  const cmp = await harness.navigateByUrl(url, TasksComponent);
  harness.detectChanges();
  const router = TestBed.inject(Router);
  const pageService = harness.routeDebugElement!.injector.get(ApplicationsPageService);
  const settle = async () => {
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return { harness, cmp: cmp as any, router, pageService, listTasks, applicationTypes, settle };
}

describe('TasksComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    jest.spyOn(Date, 'now').mockReturnValue(NOW);
  });
  afterEach(() => jest.restoreAllMocks());

  it('fills a row: title, status as text, type, amount and waiting time', async () => {
    const since = new Date(Date.now() - 4 * DAY - 3_600_000).toISOString();
    await start('/tasks', [[task('a1', { stateSince: since })]]);
    const link = screen.getByRole('link', { name: 'Mein Antrag' });
    expect(link).toHaveAttribute('href', '/tasks/a1');
    expect(screen.getByText('Förderantrag')).toBeInTheDocument();
    // The status is coloured text, not a badge: a yellow flow colour reads as "warn".
    expect(screen.getByText('In Prüfung').closest('app-status-text')).toHaveClass('st--warn');
    expect(screen.getByText('1.250,00 €')).toHaveClass('mono');
    const waiting = screen.getByText('seit 4 Tagen');
    expect(waiting.getAttribute('title')).toMatch(/^Status seit /);
  });

  it('groups the tasks by month of submission, in server order', async () => {
    await start('/tasks', [THREE]);
    const groups = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent?.trim());
    expect(groups).toEqual(['September 2026', 'August 2026']);
    const lists = screen.getAllByRole('list');
    expect(within(lists[0]).getAllByRole('link').map((a) => a.textContent?.trim())).toEqual([
      'Erster',
      'Zweiter',
    ]);
  });

  it('shows no count next to the title (the navigation badge counts the tasks)', async () => {
    await start('/tasks', [[task('a1'), task('a2')]]);
    expect(screen.queryByText('2 offen')).not.toBeInTheDocument();
    expect(document.querySelector('.ph__meta')).toBeNull();
  });

  it('sets the list path of the shared detail to /tasks', async () => {
    const { pageService } = await start('/tasks', [THREE]);
    expect(pageService.listPath()).toEqual(['/tasks']);
  });

  it('opens a deep link /tasks/:id in the detail pane and marks the row', async () => {
    const { cmp } = await start('/tasks/a2', [THREE]);
    expect(cmp.selectedId()).toBe('a2');
    expect(screen.getByText('detail')).toBeInTheDocument();
    // One pane at a time in the test: the list is hidden while the detail is open.
    const link = (name: string) => screen.getByRole('link', { name, hidden: true });
    expect(link('Zweiter')).toHaveAttribute('aria-current', 'true');
    expect(link('Erster')).not.toHaveAttribute('aria-current');
  });

  it('a click on a row opens it under /tasks/:id', async () => {
    const { router, settle, cmp } = await start('/tasks', [THREE]);
    screen.getByRole('link', { name: 'Dritter' }).click();
    await settle();
    expect(router.url).toBe('/tasks/a3');
    expect(cmp.selectedId()).toBe('a3');
  });

  it('opens the next task when a transition takes the open task out of the list', async () => {
    const { router, pageService, settle, listTasks } = await start('/tasks/a2', [
      THREE,
      [THREE[0], THREE[2]],
    ]);
    pageService.notify({ id: 'a2', kind: 'updated', source: 'detail' });
    await settle();
    expect(listTasks).toHaveBeenCalledTimes(2);
    expect(router.url).toBe('/tasks/a3');
    expect(screen.queryByRole('link', { name: 'Zweiter', hidden: true })).not.toBeInTheDocument();
  });

  it('opens the task before it when the last task leaves the list', async () => {
    const { router, pageService, settle } = await start('/tasks/a3', [THREE, THREE.slice(0, 2)]);
    pageService.notify({ id: 'a3', kind: 'updated', source: 'detail' });
    await settle();
    expect(router.url).toBe('/tasks/a2');
  });

  it('shows the empty state when the last task leaves the list', async () => {
    const { router, pageService, settle } = await start('/tasks/a1', [[THREE[0]], []]);
    pageService.notify({ id: 'a1', kind: 'updated', source: 'detail' });
    await settle();
    expect(router.url).toBe('/tasks');
    expect(screen.getAllByText('Keine offenen Aufgaben.').length).toBeGreaterThan(0);
  });

  it('keeps the open task when it stays in the list after a change', async () => {
    const { router, pageService, settle } = await start('/tasks/a2', [THREE, THREE]);
    pageService.notify({ id: 'a2', kind: 'updated', source: 'detail' });
    await settle();
    expect(router.url).toBe('/tasks/a2');
  });

  it('keeps an open application that was never a task (deep link)', async () => {
    const { router, pageService, settle } = await start('/tasks/zz', [THREE, THREE]);
    pageService.notify({ id: 'zz', kind: 'updated', source: 'detail' });
    await settle();
    expect(router.url).toBe('/tasks/zz');
  });

  it('removes a deleted task from the list without a request', async () => {
    const { pageService, settle, listTasks } = await start('/tasks/a1', [THREE]);
    pageService.notify({ id: 'a1', kind: 'deleted', source: 'detail' });
    await settle();
    expect(listTasks).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('link', { name: 'Erster', hidden: true })).not.toBeInTheDocument();
    // Only the rows of the list pane count, not a link of the detail or the frame.
    const list = document.querySelector<HTMLElement>('.tasks__scroll')!;
    expect(
      within(list).getAllByRole('link', { hidden: true }).map((a) => a.textContent?.trim()),
    ).toEqual(['Zweiter', 'Dritter']);
  });

  it('ignores the notices of the list pane', async () => {
    const { pageService, settle, listTasks } = await start('/tasks', [THREE]);
    pageService.notify({ id: 'a1', kind: 'updated', source: 'list' });
    await settle();
    expect(listTasks).toHaveBeenCalledTimes(1);
  });

  it('"Zur Liste" goes back to /tasks', async () => {
    const { cmp, router, settle } = await start('/tasks/a1', [THREE]);
    cmp.closeDetail();
    await settle();
    expect(router.url).toBe('/tasks');
  });

  it('shows the empty state when there are no tasks', async () => {
    await start('/tasks', [[]]);
    // The list pane (one pane at a time in the test) and the none pane both say it.
    expect(screen.getAllByText('Keine offenen Aufgaben.').length).toBeGreaterThan(0);
    expect(document.querySelector('app-empty-state')).not.toBeNull();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('the none pane asks to open a task while tasks exist', async () => {
    await start('/tasks', [THREE]);
    expect(screen.getByText('Keine Aufgabe geöffnet')).toBeInTheDocument();
  });

  it('shows an error, not an empty list, when the request fails', async () => {
    const { cmp } = await start('/tasks', [[]], { tasksError: true });
    expect(cmp.tasks()).toEqual([]);
    expect(cmp.loading()).toBe(false);
    expect(cmp.error()).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('Aufgaben konnten nicht geladen werden.');
    expect(screen.queryByText('Keine offenen Aufgaben.')).not.toBeInTheDocument();
  });

  it('tolerates a failing type load and an untitled task without a state', async () => {
    await start('/tasks', [[task('a1', { title: '', state: null, amount: null })]], {
      typesError: true,
    });
    expect(screen.getByRole('link', { name: 'Ohne Titel' })).toBeInTheDocument();
    expect(screen.queryByText('·')).not.toBeInTheDocument();
  });

  it('counts "Wartet seit" from stateSince, else from updatedAt', async () => {
    const { cmp: c } = await start('/tasks', [[]]);
    const stateSince = new Date(Date.now() - 2 * DAY).toISOString();
    const updatedAt = new Date(Date.now() - 9 * DAY).toISOString();
    expect(c.waitingSince(c.since(task('x', { stateSince, updatedAt })))).toBe('seit 2 Tagen');
    expect(c.waitingSince(c.since(task('x', { stateSince: null, updatedAt })))).toBe(
      'seit 9 Tagen',
    );
    expect(c.waitingSince(c.since(task('x', { stateSince: undefined, updatedAt })))).toBe(
      'seit 9 Tagen',
    );
  });

  it('says "seit heute", "seit 1 Tag" and a dash for a missing or invalid time', async () => {
    const { cmp: c } = await start('/tasks', [[]]);
    expect(c.waitingSince(new Date().toISOString())).toBe('seit heute');
    // A clock a little ahead of the server is still today, not a negative age.
    expect(c.waitingSince(new Date(Date.now() + 60_000).toISOString())).toBe('seit heute');
    expect(c.waitingSince(new Date(Date.now() - DAY - 60_000).toISOString())).toBe(
      'seit 1 Tag',
    );
    expect(c.waitingSince(null)).toBe('—');
    expect(c.waitingSince('kein Datum')).toBe('—');
    expect(c.sinceTitle(null)).toBeNull();
    expect(c.sinceTitle('kein Datum')).toBeNull();
  });

  it('counts local calendar days, not blocks of 24 hours', async () => {
    const { cmp: c } = await start('/tasks', [[]]);
    // Now is 4 Oct, 09:00. Yesterday late in the evening is one day, not "today".
    expect(c.waitingSince(new Date(2026, 9, 3, 23, 0).toISOString())).toBe('seit 1 Tag');
    // Two days ago in the evening is two days, not one.
    expect(c.waitingSince(new Date(2026, 9, 2, 20, 0).toISOString())).toBe('seit 2 Tagen');
    // Earlier the same day is today.
    expect(c.waitingSince(new Date(2026, 9, 4, 0, 5).toISOString())).toBe('seit heute');
  });

  it('counts a day across a DST change as one day', async () => {
    const { cmp: c } = await start('/tasks', [[]]);
    // In a zone with DST, 25 or 23 hours lie between these local midnights.
    jest.spyOn(Date, 'now').mockReturnValue(new Date(2026, 9, 26, 0, 30).getTime());
    expect(c.waitingSince(new Date(2026, 9, 25, 0, 30).toISOString())).toBe('seit 1 Tag');
    jest.spyOn(Date, 'now').mockReturnValue(new Date(2026, 2, 30, 0, 30).getTime());
    expect(c.waitingSince(new Date(2026, 2, 28, 23, 30).toISOString())).toBe('seit 2 Tagen');
  });

  it('uses the English wording in English', async () => {
    const { cmp: c } = await start('/tasks', [[]]);
    TestBed.inject(I18nService).setLocale('en');
    expect(c.waitingSince(new Date(Date.now() - 3 * DAY).toISOString())).toBe('for 3 days');
    expect(c.waitingSince(new Date(Date.now() - DAY - 60_000).toISOString())).toBe(
      'for 1 day',
    );
    expect(c.waitingSince(new Date().toISOString())).toBe('since today');
  });

  it('formats a missing, odd or foreign-currency amount', async () => {
    const { cmp: c } = await start('/tasks', [[]]);
    expect(c.money(task('x', { amount: null }))).toBeNull();
    expect(c.money(task('x', { amount: '' }))).toBeNull();
    expect(c.money(task('x', { amount: 'abc' }))).toBe('abc');
    // Without a currency the amount is in euro. Intl puts a no-break space before the sign.
    expect(c.money(task('x', { amount: '10', currency: null }))).toBe('10,00 €');
  });
});
