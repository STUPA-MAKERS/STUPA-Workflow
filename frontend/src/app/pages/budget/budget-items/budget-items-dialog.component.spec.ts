import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import type { BudgetApplication, Expense } from '../budget-tree.api';
import { BudgetItemsDialogComponent } from './budget-items-dialog.component';
import { itemApp, itemBooking } from './budget-items.fixtures';
import { loadErrorToast, retryLoadError } from '../../../../testing/load-error';

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- the spec reads protected state
type Inst = any;

interface Opts {
  apps?: BudgetApplication[];
  withBookings?: boolean;
  open?: boolean;
  fyId?: string;
}

async function setup(opts: Opts = {}) {
  localStorage.setItem('ap.locale', 'de');
  const view = await render(BudgetItemsDialogComponent, {
    inputs: {
      open: opts.open ?? true,
      title: 'Anträge und Buchungen',
      ksId: 'b-800',
      fyId: opts.fyId ?? 'fy-1',
      apps: opts.apps ?? [],
      withBookings: opts.withBookings ?? true,
    },
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
  });
  const http = TestBed.inject(HttpTestingController);
  return { ...view, http, c: view.fixture.componentInstance as Inst };
}

const page = (items: Expense[], total: number, offset = 0) => ({ items, total, limit: 50, offset });

function nextPage(http: HttpTestingController): TestRequest {
  return http.expectOne((r) => r.url.endsWith('/expenses'));
}

describe('BudgetItemsDialogComponent', () => {
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('loads the bookings page by page and merges them with the applications by date', async () => {
    const view = await setup({
      apps: [
        itemApp({ applicationId: 'a-new', title: 'Neu', createdAt: '2026-06-01T00:00:00Z' }),
        itemApp({ applicationId: 'a-old', title: 'Alt', createdAt: '2026-01-01T00:00:00Z' }),
      ],
    });
    const first = nextPage(view.http);
    expect(first.request.params.get('budget')).toBe('b-800');
    expect(first.request.params.get('fiscalYear')).toBe('fy-1');
    expect(first.request.params.get('offset')).toBe('0');
    expect(first.request.params.get('limit')).toBe('50');
    expect(view.container.querySelector('app-skeleton')).toBeTruthy();
    first.flush(page([itemBooking({ id: 'e-1', description: 'Druck', createdAt: '2026-04-01T00:00:00Z' })], 2));
    view.fixture.detectChanges();
    const titles = () => [...view.container.querySelectorAll('.li__title')].map((t) => t.textContent?.trim());
    expect(titles()).toEqual(['Neu', 'Druck']);
    expect(view.c.hasMore()).toBe(true);
    expect(screen.getByRole('button', { name: 'Mehr laden' })).toBeTruthy();

    view.c.loadMore();
    view.c.loadMore();
    const second = nextPage(view.http);
    expect(second.request.params.get('offset')).toBe('1');
    second.flush(page([itemBooking({ id: 'e-2', description: 'Papier', createdAt: '2025-12-01T00:00:00Z' })], 2, 1));
    view.fixture.detectChanges();
    expect(titles()).toEqual(['Neu', 'Druck', 'Alt', 'Papier']);
    expect(view.c.hasMore()).toBe(false);
    view.c.loadMore();
    view.http.expectNone((r) => r.url.endsWith('/expenses'));
  });

  it('filters by type and by the search, with the search on the server for the bookings', async () => {
    jest.useFakeTimers();
    try {
      const view = await setup({
        fyId: '',
        apps: [
          itemApp({ applicationId: 'a-1', title: 'Getränke', createdAt: '2026-06-01T00:00:00Z' }),
          itemApp({ applicationId: 'a-2', title: null, createdAt: '2026-05-01T00:00:00Z' }),
        ],
      });
      const first = nextPage(view.http);
      expect(first.request.params.has('fiscalYear')).toBe(false);
      first.flush(page([itemBooking({ id: 'e-1', createdAt: '2026-04-01T00:00:00Z' })], 1));

      view.c.setType('application');
      view.fixture.detectChanges();
      view.http.expectNone((r) => r.url.endsWith('/expenses'));
      expect(view.c.items()).toHaveLength(2);
      expect(view.c.typeText()).toBe('Typ: Anträge');

      view.c.setType('booking');
      view.fixture.detectChanges();
      nextPage(view.http).flush(page([itemBooking({ id: 'e-1', createdAt: '2026-04-01T00:00:00Z' })], 1));
      expect(view.c.items().map((i: { type: string }) => i.type)).toEqual(['booking']);

      view.c.setType('');
      expect(view.c.typeText()).toBeNull();
      view.fixture.detectChanges();
      view.http.expectNone((r) => r.url.endsWith('/expenses'));

      view.c.onQuery('getr');
      expect(view.c.query()).toBe('getr');
      jest.advanceTimersByTime(250);
      view.fixture.detectChanges();
      const search = nextPage(view.http);
      expect(search.request.params.get('q')).toBe('getr');
      expect(search.request.params.get('limit')).toBe('200');
      search.flush(page([], 0));
      expect(view.c.items().map((i: { app: { applicationId: string } }) => i.app.applicationId)).toEqual(['a-1']);
    } finally {
      jest.useRealTimers();
    }
  });

  it('shows the empty state, and an error with a retry', async () => {
    const view = await setup();
    nextPage(view.http).flush('x', { status: 500, statusText: 'err' });
    view.fixture.detectChanges();
    expect(loadErrorToast()).toBe('Die Anträge und Buchungen konnten nicht geladen werden.');
    retryLoadError();
    nextPage(view.http).flush(page([], 0));
    view.fixture.detectChanges();
    expect(screen.getByText('Keine Anträge oder Buchungen auf dieser Kostenstelle.')).toBeTruthy();
  });

  it('keeps the loaded rows when a later page fails', async () => {
    const view = await setup();
    nextPage(view.http).flush(page([itemBooking({ id: 'e-1' })], 3));
    view.c.loadMore();
    nextPage(view.http).flush('x', { status: 500, statusText: 'err' });
    view.fixture.detectChanges();
    expect(view.container.querySelectorAll('app-list-item')).toHaveLength(1);
    expect(loadErrorToast()).not.toBeNull();
    expect(view.c.hasMore()).toBe(false);
    view.c.retry();
    expect(nextPage(view.http).request.params.get('offset')).toBe('1');
  });

  it('loads no bookings while closed', async () => {
    const closed = await setup({ open: false });
    closed.http.expectNone((r) => r.url.endsWith('/expenses'));
  });

  it('lists only the applications for a reader without a budget role', async () => {
    const view = await setup({ withBookings: false, apps: [itemApp({ applicationId: 'a-1' })] });
    view.http.expectNone((r) => r.url.endsWith('/expenses'));
    expect(view.container.querySelector('app-filter-select')).toBeNull();
    expect(view.container.querySelectorAll('app-list-item')).toHaveLength(1);
    view.c.close();
    expect(view.c.open()).toBe(false);
  });
});
