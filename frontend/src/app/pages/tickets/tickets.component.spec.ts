import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Observable, Subject, of, throwError } from 'rxjs';
import type { PersonRef } from '@core/api/models';
import {
  TicketsApiService,
  type TicketListItem,
  type TicketPage,
  type TicketQuery,
} from '@core/api/tickets.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../testing/meeting-fixtures';
import { PageFrameService } from '../../layout/page-frame.service';
import { RailStatusService } from '../../layout/rail-status.service';
import { TicketsPageService } from './tickets-page.service';
import { TICKET_PAGE, TicketsComponent } from './tickets.component';

@Component({ standalone: true, template: '<p>detail</p>' })
class DetailStub {}

@Component({ standalone: true, template: '' })
class NoneStub {}

const NOW = new Date(2026, 9, 15, 18, 0);
const MARA: PersonRef = { principalId: 'p1', displayName: 'Mara Keller' };

function ticket(over: Partial<TicketListItem> = {}): TicketListItem {
  return {
    id: 't42',
    number: 'T-0042',
    kind: 'bug',
    title: 'Upload bricht bei PDF über 10 MB ab',
    status: 'new',
    reporter: { principalId: 'r1', displayName: 'Lea Hoffmann', email: null, anonymized: false },
    assignee: null,
    createdAt: new Date(2026, 9, 15, 17, 48).toISOString(),
    updatedAt: new Date(2026, 9, 15, 17, 48).toISOString(),
    ...over,
  };
}

const OPEN = [
  ticket(),
  ticket({
    id: 't40',
    number: 'T-0040',
    kind: 'idea',
    title: 'Protokoll-PDF zeigt im Kopf das falsche Datum',
    status: 'in_progress',
    assignee: MARA,
    // An anonymous report: only the e-mail, which the cut sub line never shows.
    reporter: { principalId: null, displayName: null, email: 'kassenwart.fachschaft-technik@student.example.org', anonymized: false },
    createdAt: new Date(2026, 9, 14, 21, 14).toISOString(),
  }),
];
const CLOSED = [
  ticket({ id: 't30', number: 'T-0030', title: 'Alter Fehler', status: 'done' }),
  ticket({ id: 't31', number: 'T-0031', title: 'Abgelehnt', status: 'rejected' }),
];

function pageOf(items: TicketListItem[], total = items.length): TicketPage {
  return { items, total, limit: TICKET_PAGE, offset: 0 };
}

const isClosedQuery = (q: TicketQuery) => q.status?.join() === 'done,rejected';

type Answer = (q: TicketQuery) => Observable<TicketPage>;

/** The default server: the open rows and two closed ones. */
const defaultAnswer: Answer = (q) => {
  if (isClosedQuery(q)) return of(pageOf(q.limit === 1 ? CLOSED.slice(0, 1) : CLOSED, CLOSED.length));
  return of(pageOf(OPEN));
};

interface Opts {
  answer?: Answer;
  assignees?: Observable<PersonRef[]>;
}

async function start(url = '/tickets', opts: Opts = {}) {
  localStorage.setItem('ap.locale', 'de');
  let answer = opts.answer ?? defaultAnswer;
  const api = {
    list: jest.fn((q: TicketQuery) => answer(q)),
    assignees: jest.fn(() => opts.assignees ?? of([MARA, { principalId: null, displayName: 'Weg' }, { principalId: 'p3', displayName: null }])),
  };
  const rail = { refresh: jest.fn() };
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        {
          path: 'tickets',
          component: TicketsComponent,
          children: [
            { path: '', component: NoneStub },
            { path: ':id', component: DetailStub },
          ],
        },
      ]),
      { provide: TicketsApiService, useValue: api },
      { provide: RailStatusService, useValue: rail },
    ],
  });
  const harness = await RouterTestingHarness.create();
  const cmp = await harness.navigateByUrl(url, TicketsComponent);
  // The clock of the row ages; the rows compute again with it.
  cmp.now = () => NOW;
  cmp.items.set([...cmp.items()]);
  harness.detectChanges();
  const router = TestBed.inject(Router);
  const page = harness.routeDebugElement!.injector.get(TicketsPageService);
  const go = async (path: string) => {
    await router.navigateByUrl(path);
    harness.detectChanges();
  };
  const setAnswer = (a: Answer) => (answer = a);
  return { harness, cmp, api, rail, router, page, go, setAnswer };
}

const groupTitles = () =>
  Array.from(document.querySelectorAll('.tk__groupTitle')).map((h) => h.textContent?.replace(/\s+/g, ' ').trim());

describe('TicketsComponent', () => {
  afterEach(() => localStorage.clear());

  it('groups the open tickets and folds the closed ones with their number', async () => {
    const { api, rail } = await start();
    expect(api.list).toHaveBeenCalledWith({
      kind: [],
      assignee: null,
      q: null,
      status: ['new', 'in_progress'],
      limit: TICKET_PAGE,
      offset: 0,
    });
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ status: ['done', 'rejected'], limit: 1 }));
    expect(groupTitles()).toEqual(['Neu 1', 'In Bearbeitung 1', 'Erledigt oder abgelehnt 2']);
    expect(screen.getByRole('searchbox')).toHaveAttribute('placeholder', '4 Tickets durchsuchen');

    const link = screen.getByRole('link', { name: /Upload bricht/ });
    expect(link).toHaveAttribute('href', '/tickets/t42');
    const row = link.closest('app-list-item')!;
    expect(row).toHaveTextContent('T-0042 · Lea Hoffmann · vor 12 Min.');
    expect(row).toHaveTextContent('Fehler');
    expect(row.querySelector('.tk__nobody')).not.toBeNull();
    const other = screen.getByRole('link', { name: /Protokoll-PDF/ }).closest('app-list-item')!;
    expect(other.querySelector('.li__sub')).toHaveTextContent(/^T-0040 · gestern$/);
    expect(other.querySelector('.li__sub .mono')).toHaveTextContent('T-0040');
    expect(other.querySelector('.tk__kind')).toHaveAttribute('data-kind', 'idea');
    expect(other).not.toHaveTextContent('kassenwart');
    expect(other.querySelector('app-avatar')).not.toBeNull();
    expect(rail.refresh).not.toHaveBeenCalled();
  });

  it('shows the closed tickets on request', async () => {
    const { harness, api } = await start();
    await userEvent.click(screen.getByRole('button', { name: /2 abgeschlossene Tickets zeigen/ }));
    harness.detectChanges();
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: ['done', 'rejected'], limit: TICKET_PAGE }));
    expect(screen.getByRole('link', { name: /Alter Fehler/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /abgeschlossene Tickets zeigen/ })).not.toBeInTheDocument();
  });

  it('asks for the closed tickets only once at a time, and stays on a failure', async () => {
    const pending = new Subject<TicketPage>();
    const { harness, cmp, api, setAnswer } = await start();
    setAnswer(() => pending);
    cmp.showClosed();
    cmp.showClosed();
    expect(api.list).toHaveBeenCalledTimes(3);
    pending.error(new Error('down'));
    harness.detectChanges();
    expect(cmp.closedLoading()).toBe(false);
    expect(cmp.closedItems()).toBeNull();
  });

  it('drops a closed list that a filter change overtook', async () => {
    const pending = new Subject<TicketPage>();
    const { cmp, go, setAnswer } = await start();
    setAnswer((q) => (isClosedQuery(q) && q.limit === TICKET_PAGE ? pending : defaultAnswer(q)));
    cmp.showClosed();
    await go('/tickets?kind=bug');
    pending.next(pageOf(CLOSED));
    expect(cmp.closedItems()).toBeNull();
  });

  it('filters by state, kind and assignee through the query params', async () => {
    const { harness, cmp, api, router } = await start();
    cmp.setStatus('done');
    await harness.fixture.whenStable();
    harness.detectChanges();
    expect(router.url).toBe('/tickets?status=done');
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: ['done'] }));
    // No closed group outside the default view.
    expect(cmp.closedTotal()).toBe(0);

    cmp.setKind('bug');
    await harness.fixture.whenStable();
    cmp.setAssignee('me');
    await harness.fixture.whenStable();
    harness.detectChanges();
    expect(router.url).toBe('/tickets?status=done&kind=bug&assignee=me');
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ kind: ['bug'], assignee: 'me' }));
    expect(cmp.kindChipLabel()).toBe('Fehler');
    expect(cmp.assigneeChipLabel()).toBe('Mir');
    expect(cmp.statusChipLabel()).toBe('Status: Erledigt');

    cmp.setStatus('open');
    await harness.fixture.whenStable();
    cmp.setKind('');
    await harness.fixture.whenStable();
    cmp.setAssignee('');
    await harness.fixture.whenStable();
    cmp.setStatus('');
    await harness.fixture.whenStable();
    harness.detectChanges();
    expect(router.url).toBe('/tickets');
    expect(cmp.kindChipLabel()).toBe('Art');
    expect(cmp.assigneeChipLabel()).toBe('Zugewiesen');
    expect(cmp.statusChipLabel()).toBe('Status: Offen');
  });

  it('lists the people with tickets, and names an unknown one by the chip', async () => {
    const { cmp, go } = await start('/tickets?assignee=p1');
    expect(cmp.assigneeOptions().map((o) => o.label)).toEqual(['Alle', 'Mir', 'Niemandem', 'Mara Keller', 'p3']);
    expect(cmp.assigneeChipLabel()).toBe('Mara Keller');
    await go('/tickets?assignee=gone');
    expect(cmp.assigneeChipLabel()).toBe('Zugewiesen');
  });

  it('works without the list of people', async () => {
    const { cmp } = await start('/tickets', { assignees: throwError(() => new Error('x')) });
    expect(cmp.assigneeOptions()).toHaveLength(3);
  });

  it('reads every state, and falls back to the default for bad params', async () => {
    const { cmp, go } = await start('/tickets?status=all&q=%20pdf%20');
    expect(cmp.statusFilter()).toBe('all');
    expect(cmp.q()).toBe('pdf');
    expect(cmp.statusOptions().map((o) => o.label)).toEqual([
      'Offen',
      'Neu',
      'In Bearbeitung',
      'Erledigt',
      'Abgelehnt',
      'Alle',
    ]);
    await go('/tickets?status=bogus&kind=bogus');
    expect(cmp.statusFilter()).toBe('open');
    expect(cmp.kindFilter()).toBe('');
  });

  it('groups all four states in the view "Alle"', async () => {
    await start('/tickets?status=all', { answer: () => of(pageOf([...OPEN, ...CLOSED])) });
    expect(groupTitles()).toEqual(['Neu 1', 'In Bearbeitung 1', 'Erledigt 1', 'Abgelehnt 1']);
  });

  it('resets every filter and the search', async () => {
    const { harness, cmp, router } = await start('/tickets?q=pdf&status=done');
    expect(cmp.activeFilterCount()).toBe(2);
    await userEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
    await harness.fixture.whenStable();
    harness.detectChanges();
    expect(router.url).toBe('/tickets');
    expect(cmp.search.text()).toBe('');
    expect(screen.queryByRole('button', { name: 'Filter zurücksetzen' })).not.toBeInTheDocument();
  });

  it('searches while the user types', async () => {
    const { harness, router } = await start();
    await userEvent.type(screen.getByRole('searchbox'), 'pdf{Enter}');
    await harness.fixture.whenStable();
    expect(router.url).toBe('/tickets?q=pdf');
    await userEvent.clear(screen.getByRole('searchbox'));
    await userEvent.type(screen.getByRole('searchbox'), '{Enter}');
    await harness.fixture.whenStable();
    expect(router.url).toBe('/tickets');
  });

  it('says that there are no tickets, or that none matches', async () => {
    const { go, setAnswer } = await start('/tickets', { answer: () => of(pageOf([])) });
    expect(screen.getByText('Keine Tickets')).toBeInTheDocument();
    setAnswer(() => of(pageOf([])));
    await go('/tickets?kind=idea');
    expect(screen.getByText('Kein Ticket passt zu den Filtern.')).toBeInTheDocument();
  });

  it('names a failed read, and counts no closed tickets after their failure', async () => {
    const { cmp } = await start('/tickets', { answer: () => throwError(() => new Error('down')) });
    expect(screen.getByRole('alert')).toHaveTextContent('Die Tickets konnten nicht geladen werden.');
    expect(cmp.closedTotal()).toBe(0);
    expect(cmp.hasRows()).toBe(false);
  });

  it('loads the next page, once at a time', async () => {
    const pending = new Subject<TicketPage>();
    const { harness, cmp, api, setAnswer } = await start('/tickets', {
      answer: (q) => (isClosedQuery(q) ? of(pageOf([])) : of(pageOf(OPEN.slice(0, 1), 2))),
    });
    expect(cmp.hasMore()).toBe(true);
    setAnswer(() => pending);
    await userEvent.click(screen.getByRole('button', { name: 'Weitere laden' }));
    cmp.loadMore();
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 1 }));
    pending.next(pageOf(OPEN.slice(1), 2));
    pending.complete();
    harness.detectChanges();
    expect(cmp.items()).toHaveLength(2);
    expect(screen.queryByRole('button', { name: 'Weitere laden' })).not.toBeInTheDocument();
  });

  it('keeps the rows when the next page fails or a filter overtook it', async () => {
    const { cmp, go, setAnswer } = await start('/tickets', {
      answer: (q) => (isClosedQuery(q) ? of(pageOf([])) : of(pageOf(OPEN.slice(0, 1), 2))),
    });
    setAnswer(() => throwError(() => new Error('x')));
    cmp.loadMore();
    expect(cmp.loadingMore()).toBe(false);
    expect(cmp.items()).toHaveLength(1);

    const pending = new Subject<TicketPage>();
    setAnswer(() => pending);
    cmp.loadMore();
    setAnswer((q) => (isClosedQuery(q) ? of(pageOf([])) : of(pageOf(OPEN.slice(0, 1), 2))));
    await go('/tickets?kind=bug');
    pending.next(pageOf(OPEN.slice(1), 2));
    expect(cmp.items()).toHaveLength(1);
  });

  it('drops answers that a newer filter overtook', async () => {
    const slow = new Subject<TicketPage>();
    const slowClosed = new Subject<TicketPage>();
    const { cmp, go, setAnswer } = await start();
    setAnswer((q) => (isClosedQuery(q) ? slowClosed : slow));
    await go('/tickets?kind=bug');
    setAnswer(defaultAnswer);
    await go('/tickets?kind=idea');
    slow.next(pageOf([]));
    slow.error(new Error('late'));
    slowClosed.next(pageOf([], 99));
    expect(cmp.items()).toHaveLength(2);
    expect(cmp.error()).toBe(false);
    expect(cmp.closedTotal()).toBe(2);
  });

  it('drops a late failure of the closed count', async () => {
    const slowClosed = new Subject<TicketPage>();
    const { cmp, go, setAnswer } = await start();
    setAnswer((q) => (isClosedQuery(q) ? slowClosed : defaultAnswer(q)));
    await go('/tickets?kind=bug');
    setAnswer(defaultAnswer);
    await go('/tickets?kind=idea');
    slowClosed.error(new Error('late'));
    expect(cmp.closedTotal()).toBe(2);
  });

  it('loads again when the detail changed a ticket, and keeps the shown closed tickets', async () => {
    const { harness, cmp, api, rail, page, setAnswer } = await start();
    cmp.showClosed();
    harness.detectChanges();
    api.list.mockClear();
    page.notify('t42');
    harness.detectChanges();
    expect(rail.refresh).toHaveBeenCalled();
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ status: ['done', 'rejected'], limit: TICKET_PAGE }));
    expect(cmp.closedItems()).toHaveLength(2);

    // A failed reload keeps the rows.
    setAnswer(() => throwError(() => new Error('x')));
    page.notify('t42');
    harness.detectChanges();
    expect(cmp.items()).toHaveLength(2);
    expect(cmp.error()).toBe(false);
  });

  it('marks the open ticket and goes back to the list with the filters', async () => {
    const { harness, cmp, router, go } = await start('/tickets/t40?kind=idea');
    expect(cmp.selectedId()).toBe('t40');
    cmp.closeDetail();
    await harness.fixture.whenStable();
    expect(router.url).toBe('/tickets?kind=idea');
    expect(cmp.selectedId()).toBeNull();
    await go('/tickets/t42');
    expect(cmp.selectedId()).toBe('t42');
  });

  it('shows the list beside the detail on a wide screen', async () => {
    const restore = matchMediaQueries(MEDIA.wide);
    try {
      const { harness, page } = await start('/tickets/t40');
      await harness.fixture.whenStable();
      harness.detectChanges();
      expect(page.split()).toBe(true);
      expect(TestBed.inject(PageFrameService).fill()).toBe(true);
      const row = screen.getByRole('link', { name: /Protokoll-PDF/ }).closest('app-list-item')!;
      expect(row.querySelector('.tk__chev')).toBeNull();
      // Leaving the page frees the frame.
      harness.fixture.destroy();
      expect(TestBed.inject(PageFrameService).fill()).toBe(false);
    } finally {
      restore();
    }
  });
});
