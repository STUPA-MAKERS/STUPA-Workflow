import { provideRouter, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { ApplicationListItem } from '@core/api/models';
import { TasksComponent } from './tasks.component';

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
    createdAt: '2026-06-01T10:00:00Z',
    updatedAt: '2026-06-01T10:00:00Z',
    archivedAt: null,
    ...extra,
  };
}

async function setup(
  items: ApplicationListItem[],
  opts: { tasksError?: boolean; typesError?: boolean } = {},
) {
  const listTasks = opts.tasksError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of(items));
  const applicationTypes = opts.typesError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of([{ id: 't1', name: 'Förderantrag' }]));
  const view = await render(TasksComponent, {
    providers: [provideRouter([]), { provide: ApiClient, useValue: { listTasks, applicationTypes } }],
  });
  return { ...view, listTasks, applicationTypes };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const cmp = (fixture: { componentInstance: unknown }): any => fixture.componentInstance;

describe('TasksComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    jest.spyOn(Date, 'now').mockReturnValue(NOW);
  });
  afterEach(() => jest.restoreAllMocks());

  it('shows the columns Titel, Typ, Status, Betrag and Wartet seit', async () => {
    await setup([task('a1')]);
    for (const name of ['Titel', 'Typ', 'Status', 'Betrag', 'Wartet seit']) {
      expect(screen.getByRole('columnheader', { name })).toBeInTheDocument();
    }
  });

  it('fills a row: title, type, status as text, amount and waiting time', async () => {
    const since = new Date(Date.now() - 4 * DAY - 3_600_000).toISOString();
    await setup([task('a1', { stateSince: since })]);
    expect(screen.getByText('Mein Antrag')).toHaveAttribute('title', 'Mein Antrag');
    expect(screen.getByText('Förderantrag')).toBeInTheDocument();
    // The status is coloured text, not a badge: a yellow flow colour reads as "warn".
    const state = screen.getByText('In Prüfung');
    expect(state.closest('app-status-text')).toHaveClass('st--warn');
    expect(document.querySelector('app-badge')).toBeNull();
    expect(screen.getByText('1.250,00 €')).toHaveClass('mono');
    const waiting = screen.getByText('seit 4 Tagen');
    expect(waiting.getAttribute('title')).toMatch(/^Status seit /);
  });

  it('counts the open tasks in the header', async () => {
    await setup([task('a1'), task('a2')]);
    expect(screen.getByText('2 offen')).toBeInTheDocument();
  });

  it('counts "Wartet seit" from stateSince, else from updatedAt', async () => {
    const { fixture } = await setup([]);
    const c = cmp(fixture);
    const stateSince = new Date(Date.now() - 2 * DAY).toISOString();
    const updatedAt = new Date(Date.now() - 9 * DAY).toISOString();
    expect(c.waitingSince(c.since(task('x', { stateSince, updatedAt })))).toBe('seit 2 Tagen');
    expect(c.waitingSince(c.since(task('x', { stateSince: null, updatedAt })))).toBe('seit 9 Tagen');
    expect(c.waitingSince(c.since(task('x', { stateSince: undefined, updatedAt })))).toBe('seit 9 Tagen');
  });

  it('says "seit heute", "seit 1 Tag" and a dash for a missing or invalid time', async () => {
    const { fixture } = await setup([]);
    const c = cmp(fixture);
    expect(c.waitingSince(new Date().toISOString())).toBe('seit heute');
    // A clock a little ahead of the server is still today, not a negative age.
    expect(c.waitingSince(new Date(Date.now() + 60_000).toISOString())).toBe('seit heute');
    expect(c.waitingSince(new Date(Date.now() - DAY - 60_000).toISOString())).toBe('seit 1 Tag');
    expect(c.waitingSince(null)).toBe('—');
    expect(c.waitingSince('kein Datum')).toBe('—');
    expect(c.sinceTitle(null)).toBeNull();
    expect(c.sinceTitle('kein Datum')).toBeNull();
  });

  it('counts local calendar days, not blocks of 24 hours', async () => {
    const { fixture } = await setup([]);
    const c = cmp(fixture);
    // Now is 4 Oct, 09:00. Yesterday late in the evening is one day, not "today".
    expect(c.waitingSince(new Date(2026, 9, 3, 23, 0).toISOString())).toBe('seit 1 Tag');
    // Two days ago in the evening is two days, not one.
    expect(c.waitingSince(new Date(2026, 9, 2, 20, 0).toISOString())).toBe('seit 2 Tagen');
    // Earlier the same day is today.
    expect(c.waitingSince(new Date(2026, 9, 4, 0, 5).toISOString())).toBe('seit heute');
  });

  it('counts a day across a DST change as one day', async () => {
    const { fixture } = await setup([]);
    const c = cmp(fixture);
    // In a zone with DST, 25 or 23 hours lie between these local midnights.
    jest.spyOn(Date, 'now').mockReturnValue(new Date(2026, 9, 26, 0, 30).getTime());
    expect(c.waitingSince(new Date(2026, 9, 25, 0, 30).toISOString())).toBe('seit 1 Tag');
    jest.spyOn(Date, 'now').mockReturnValue(new Date(2026, 2, 30, 0, 30).getTime());
    expect(c.waitingSince(new Date(2026, 2, 28, 23, 30).toISOString())).toBe('seit 2 Tagen');
  });

  it('uses the English wording in English', async () => {
    const { fixture } = await setup([]);
    fixture.debugElement.injector.get(I18nService).setLocale('en');
    const c = cmp(fixture);
    expect(c.waitingSince(new Date(Date.now() - 3 * DAY).toISOString())).toBe('for 3 days');
    expect(c.waitingSince(new Date(Date.now() - DAY - 60_000).toISOString())).toBe('for 1 day');
    // The header reads "Waiting", so each value reads after it: "today", "for 3 days".
    expect(c.waitingSince(new Date().toISOString())).toBe('today');
    expect(c.columns().find((col: { key: string }) => col.key === 'waiting').label).toBe('Waiting');
  });

  it('formats a missing, odd or foreign-currency amount', async () => {
    const { fixture } = await setup([]);
    const c = cmp(fixture);
    expect(c.money(task('x', { amount: null }))).toBe('—');
    expect(c.money(task('x', { amount: '' }))).toBe('—');
    expect(c.money(task('x', { amount: 'abc' }))).toBe('abc');
    // Without a currency the amount is in euro. Intl puts a no-break space before the sign.
    expect(c.money(task('x', { amount: '10', currency: null }))).toBe('10,00\u00a0€');
  });

  it('shows an error and no count, not an empty list, when the request fails', async () => {
    const { fixture } = await setup([], { tasksError: true });
    const c = cmp(fixture);
    expect(c.tasks()).toEqual([]);
    expect(c.loading()).toBe(false);
    expect(c.error()).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('Aufgaben konnten nicht geladen werden.');
    expect(screen.queryByText('Keine offenen Aufgaben.')).not.toBeInTheDocument();
    expect(screen.queryByText('0 offen')).not.toBeInTheDocument();
  });

  it('shows the empty state and the count 0 when there are no tasks', async () => {
    await setup([]);
    expect(screen.getByText('Keine offenen Aufgaben.')).toBeInTheDocument();
    expect(screen.getByText('0 offen')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('tolerates a failing type load and an untitled task without a state', async () => {
    await setup([task('a1', { title: '', state: null })], { typesError: true });
    expect(screen.getByText('Ohne Titel')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('opens the application when a row is clicked', async () => {
    const { fixture } = await setup([task('app-9')]);
    const router = fixture.debugElement.injector.get(Router);
    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    screen.getByText('Mein Antrag').click();
    expect(navigate).toHaveBeenCalledWith(['/applications', 'app-9']);
  });
});
