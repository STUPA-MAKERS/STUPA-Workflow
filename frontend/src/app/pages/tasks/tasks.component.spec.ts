import { provideRouter, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { ApplicationListItem } from '@core/api/models';
import { TasksComponent } from './tasks.component';

function task(id: string, kind: string, title = 'Mein Antrag'): ApplicationListItem {
  return {
    id,
    typeId: 't1',
    title,
    state: { id: 's1', key: 's', label: 'Abstimmung', color: '#9b59b6', editAllowed: false, kind },
    gremiumId: null,
    budgetPotId: null,
    amount: '120.00',
    currency: 'EUR',
    createdAt: '2026-06-01T10:00:00Z',
    updatedAt: '2026-06-01T10:00:00Z',
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
    : jest.fn(() => of([{ id: 't1', name: 'Finanzantrag' }]));
  const api = { listTasks, applicationTypes };
  const view = await render(TasksComponent, {
    providers: [provideRouter([]), { provide: ApiClient, useValue: api }],
  });
  return { ...view, listTasks, applicationTypes };
}

describe('TasksComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists vote tasks awaiting the user with type and waiting age', async () => {
    await setup([task('v1', 'vote')]);
    expect(screen.getByText('Mein Antrag')).toBeInTheDocument();
    expect(screen.getByText('Abstimmung')).toBeInTheDocument();
    // Typ-Spalte (über die geladenen Typen aufgelöst).
    expect(await screen.findByText('Finanzantrag')).toBeInTheDocument();
    // „Wartet seit"-Spalte zeigt eine relative Angabe (vor … Tagen).
    expect(screen.getByText(/Tag(en)?/)).toBeInTheDocument();
  });

  it('shows no inline decision buttons (acting happens in the detail view)', async () => {
    await setup([task('v1', 'vote')]);
    expect(screen.queryByRole('button', { name: 'Annehmen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ablehnen' })).not.toBeInTheDocument();
  });

  it('clears loading and shows empty state when the tasks request fails', async () => {
    const { fixture } = await setup([], { tasksError: true });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.tasks()).toEqual([]);
    expect(c.loading()).toBe(false);
  });

  it('tolerates a failing application-types load (empty types)', async () => {
    const { fixture } = await setup([task('v1', 'vote')], { typesError: true });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // Unknown type id falls back to the em-dash placeholder.
    expect(c.typeName('t1')).toBe('—');
  });

  it('falls back to the untitled label when a task has no title', async () => {
    const { fixture } = await setup([task('v1', 'vote', '')]);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const item = c.tasks()[0];
    expect(c.titleOf(item)).toBe('Ohne Titel');
  });

  it('waitingSince handles missing, same-day and prior-day dates', async () => {
    const { fixture } = await setup([task('v1', 'vote')]);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.waitingSince(null)).toBe('—');
    // today → days <= 0 branch → "heute"/"today"
    const today = new Date().toISOString();
    expect(c.waitingSince(today)).toMatch(/heute|today/i);
    // a week ago → relative "vor N Tagen"
    const past = new Date(Date.now() - 7 * 86_400_000).toISOString();
    expect(c.waitingSince(past)).toMatch(/Tag/);
  });

  it('uses the English relative format when the locale is en', async () => {
    const view = await render(TasksComponent, {
      providers: [
        provideRouter([]),
        { provide: ApiClient, useValue: { listTasks: jest.fn(() => of([])), applicationTypes: jest.fn(() => of([])) } },
      ],
    });
    const i18n = view.fixture.debugElement.injector.get(I18nService);
    i18n.setLocale('en');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    const past = new Date(Date.now() - 3 * 86_400_000).toISOString();
    expect(c.waitingSince(past)).toMatch(/day/i);
  });

  it('navigates to the application detail when a row is opened', async () => {
    const view = await render(TasksComponent, {
      providers: [
        provideRouter([]),
        { provide: ApiClient, useValue: { listTasks: jest.fn(() => of([])), applicationTypes: jest.fn(() => of([])) } },
      ],
    });
    const router = view.fixture.debugElement.injector.get(Router);
    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.open('app-9');
    expect(navigate).toHaveBeenCalledWith(['/applications', 'app-9']);
  });
});
