import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { TodosApiService, type LinksOut, type TodoLinkedCard } from '@core/api/todos.service';
import { TestBed } from '@angular/core/testing';
import { ToastService } from '@stupa-makers/ui-kit';
import { linkRow, linksOf } from '../../../../testing/todo-fixtures';
import { TodoLinkPickerComponent } from '../link-picker/todo-link-picker.component';
import { TodoLinkedListComponent } from './todo-linked-list.component';
import { TodoLinkedRefresh } from './todo-linked-refresh';
import { By } from '@angular/platform-browser';
import { kindSpies } from '../../../../testing/toast';

function card(over: Partial<TodoLinkedCard> = {}): TodoLinkedCard {
  return {
    id: 'k-1',
    boardId: 'b-1',
    boardName: 'Studierendenparlament',
    title: 'Raum buchen',
    columnName: 'In Arbeit',
    isDone: false,
    dueDate: '2026-10-17',
    assignees: [{ principalId: 'p-1', displayName: 'Mara Keller' }, { principalId: null, displayName: null }],
    event: null,
    balance: null,
    ...over,
  };
}

const ids = (cmp: TodoLinkedListComponent) => cmp.links().map((l) => l.targetId);

async function setup(answer: () => Observable<LinksOut>, extra: Record<string, unknown> = {}) {
  const api = { links: jest.fn(answer), boards: jest.fn(() => of([])) };
  const view = await render(TodoLinkedListComponent, {
    inputs: { kind: 'application', targetId: 'a-1', headingId: 'ad-todos', ...extra },
    providers: [provideRouter([]), { provide: TodosApiService, useValue: api }],
  });
  return { ...view, api, cmp: view.fixture.componentInstance };
}

describe('TodoLinkedListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the linked cards with board, column, due date and people, each a link to its card', async () => {
    const { api, cmp } = await setup(() =>
      of(linksOf([card(), card({ id: 'k-2', title: 'Erledigt', isDone: true, dueDate: null, assignees: [] })])),
    );
    expect(api.links).toHaveBeenCalledWith('application', 'a-1');
    expect(screen.getByRole('heading', { name: 'Verknüpft' })).toHaveAttribute('id', 'ad-todos');
    expect(screen.getByRole('link', { name: 'Raum buchen' })).toHaveAttribute('href', '/todos?card=k-1');
    expect(screen.getByText('Studierendenparlament · In Arbeit · fällig 17.10.')).toBeInTheDocument();
    expect(screen.getByText('Studierendenparlament · In Arbeit')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Erledigt' }).closest('li')).toHaveClass('tl__row--done');
    expect(cmp.names(card())).toEqual(['Mara Keller', 'Gelöschte Person']);
    expect(cmp.ids(card())).toEqual(['p-1', null]);
    expect(document.querySelectorAll('app-avatar-stack')).toHaveLength(1);
  });

  /** §F/finance/orders/002869: rows of the page with and without a link, and a button of the page. */
  it('shows a row of the page without a link, one with query parameters, and the button of the page', async () => {
    await setup(() => of(linksOf([])), {
      rows: [
        { icon: 'package', title: 'Beamer', sub: 'Bestellung · Geplant', link: null },
        { icon: 'receipt', title: 'RE-7', sub: 'Rechnung', link: ['/invoices'], queryParams: { id: 'i-1' } },
      ],
      extra: { label: 'Bestellung anlegen', icon: 'package', link: ['/orders', 'new'], queryParams: { application: 'a-1' } },
    });
    expect(screen.getByText('Beamer')).not.toHaveAttribute('href');
    expect(screen.getByRole('link', { name: 'RE-7' })).toHaveAttribute('href', '/invoices?id=i-1');
    const extra = screen.getByTestId('tl-extra');
    expect(extra).toHaveAttribute('href', '/orders/new?application=a-1');
    expect(extra).toHaveAttribute('aria-label', 'Bestellung anlegen');
  });

  /** §F/collaboration/links/001407: the section shows the links of every kind. */
  it('lists the links of the other kinds with their page or "kein Zugriff"', async () => {
    await setup(() =>
      of(
        linksOf(
          [card()],
          [
            linkRow({ id: 'l-2', kind: 'invoice', title: 'RE-2026-17', url: '/invoices?id=i-1' }),
            linkRow({ id: 'l-3', kind: 'expense', targetId: 'e-1', accessible: false, title: null, url: null }),
          ],
        ),
      ),
    );
    expect(screen.getByRole('link', { name: 'RE-2026-17' })).toHaveAttribute('href', '/invoices?id=i-1');
    expect(screen.getByText('Buchung (kein Zugriff)')).toHaveClass('tl__muted');
    expect(document.querySelectorAll('[data-testid="tl-link-row"]')).toHaveLength(2);
  });

  it('opens a Paperless document in a new tab and hides it without the right (002764, 002765)', async () => {
    const href = 'https://paperless.example.org/documents/41/details';
    await setup(() =>
      of(
        linksOf(
          [],
          [
            linkRow({ id: 'l-5', kind: 'paperless', title: 'Angebot Beamer', url: href, detail: { documentType: 'Angebot' } }),
            linkRow({ id: 'l-6', kind: 'paperless', targetId: 'p-2', accessible: false, title: null, url: null }),
          ],
        ),
      ),
    );
    const link = screen.getByRole('link', { name: 'Angebot Beamer' });
    expect(link).toHaveAttribute('href', href);
    expect(link).toHaveAttribute('target', '_blank');
    expect(screen.getByText('Paperless-Dokument · Angebot')).toBeInTheDocument();
    expect(screen.getByText('Paperless-Dokument (kein Zugriff)')).toHaveClass('tl__muted');
  });

  it('leaves out the heading on request and keeps the name of the section', async () => {
    await setup(() => of(linksOf([card()])), { showTitle: false });
    const heading = screen.getByRole('heading', { name: 'Verknüpft' });
    expect(heading.closest('.section__head')).toHaveClass('section__head--hidden');
    expect(screen.getByRole('group', { name: 'Verknüpft' })).toBeInTheDocument();
  });

  it('shows the cards of the page without a read of its own', async () => {
    const { api, fixture } = await setup(() => of(linksOf([card({ id: 'k-8', title: 'Vom Server' })])), {
      items: [card()],
      avatarSize: 'xs',
    });
    expect(api.links).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: 'Raum buchen' })).toBeInTheDocument();
    expect(document.querySelector('app-avatar')).toHaveClass('av--xs');
    expect(document.querySelector('[data-testid="tl-unlink"]')).toBeNull();
    TestBed.inject(TodoLinkedRefresh).touch([{ kind: 'application', targetId: 'a-1' }]);
    fixture.componentRef.setInput('items', [card({ id: 'k-2', title: 'Zweite' })]);
    fixture.detectChanges();
    expect(api.links).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: 'Zweite' })).toBeInTheDocument();
  });

  it('shows a linked Event with its dates, board, place and balance (spec 000489)', async () => {
    const event = { startsOn: '2026-11-20', endsOn: '2026-11-21', startTime: null, endTime: null, place: 'Mensa', participants: null, seriesId: null, seriesName: null };
    await setup(() => of(linksOf([card({ id: 'ev', title: 'Erstiparty', event, balance: '-725.40' }), card()])));
    const rows = [...document.querySelectorAll('.tl__row')];
    expect(rows[0]).toHaveClass('tl__row--event');
    expect(rows[0]).toHaveTextContent('Erstiparty');
    expect(screen.getByText('Veranstaltung · 20.11.–21.11.2026 · Studierendenparlament')).toBeInTheDocument();
    expect(rows[0].querySelector('.tl__neg')?.textContent).toContain('−725,40');
    expect(rows[0]).toHaveTextContent('Mensa');
  });

  it('shows nothing without links', async () => {
    const { container } = await setup(() => of(linksOf()));
    expect(container.querySelector('section')).toBeNull();
  });

  it('shows nothing when the read fails', async () => {
    const { container } = await setup(() => throwError(() => new Error('x')));
    expect(container.querySelector('section')).toBeNull();
  });

  it('reads again for another target and drops a late answer', async () => {
    const late = new Subject<LinksOut>();
    let first = true;
    const { api, fixture, cmp } = await setup(() => {
      if (first) {
        first = false;
        return late;
      }
      return of(linksOf([card({ id: 'k-9', title: 'Neu' })]));
    });
    fixture.componentRef.setInput('kind', 'agenda_item');
    fixture.componentRef.setInput('targetId', 'ai-1');
    fixture.detectChanges();
    expect(api.links).toHaveBeenLastCalledWith('agenda_item', 'ai-1');
    late.next(linksOf([card()]));
    expect(ids(cmp)).toEqual(['k-9']);
  });

  it('reads again, keeping the list, when a link of its target changes elsewhere', async () => {
    let answer = linksOf([card()]);
    const { api, fixture, cmp } = await setup(() => of(answer));
    const refresh = TestBed.inject(TodoLinkedRefresh);
    expect(api.links).toHaveBeenCalledTimes(1);
    refresh.touch([{ kind: 'agenda_item', targetId: 'a-1' }]);
    fixture.detectChanges();
    expect(api.links).toHaveBeenCalledTimes(1);
    refresh.touch([]);
    fixture.detectChanges();
    expect(api.links).toHaveBeenCalledTimes(1);
    const late = new Subject<LinksOut>();
    api.links.mockReturnValueOnce(late);
    refresh.touch([{ kind: 'application', targetId: 'a-1' }]);
    fixture.detectChanges();
    expect(api.links).toHaveBeenCalledTimes(2);
    expect(ids(cmp)).toEqual(['k-1']);
    answer = linksOf([card(), card({ id: 'k-2', title: 'Neu' })]);
    late.next(answer);
    fixture.detectChanges();
    expect(screen.getByRole('link', { name: 'Neu' })).toBeInTheDocument();
  });

  it('does not read twice for a change made before it was shown', async () => {
    const { api, fixture } = await setup(() => of(linksOf([card()])));
    TestBed.inject(TodoLinkedRefresh).touch([{ kind: 'application', targetId: 'a-1' }]);
    fixture.detectChanges();
    const before = api.links.mock.calls.length;
    const second = TestBed.createComponent(TodoLinkedListComponent);
    second.componentRef.setInput('kind', 'application');
    second.componentRef.setInput('targetId', 'a-1');
    second.detectChanges();
    second.detectChanges();
    expect(api.links).toHaveBeenCalledTimes(before + 1);
    expect(ids(second.componentInstance)).toEqual(['k-1']);
  });
});

describe('TodoLinkedListComponent actions (specs 000547, 001404, 001408)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  async function withActions(writes: boolean, out: LinksOut = linksOf(), more: Record<string, unknown> = {}) {
    const api = {
      links: jest.fn(() => of(out)),
      link: jest.fn(() => of(linksOf([], [linkRow()], true))),
      unlink: jest.fn(() => of(undefined)),
      linkTargets: jest.fn(() => of([])),
      boards: jest.fn(() => of([{ id: 'b-1', name: 'StuPa', kind: 'team', gremiumId: 'g-1', canWrite: writes }])),
      ...more,
    };
    const view = await render(TodoLinkedListComponent, {
      inputs: { kind: 'application', targetId: 'a-1', headingId: 'ad-todos', actions: true, gremiumId: 'g-1', linkLabel: 'Lerncafé' },
      providers: [provideRouter([]), { provide: TodosApiService, useValue: api }],
    });
    return { ...view, api, cmp: view.fixture.componentInstance };
  }

  it('shows "Verknüpfen" and "To-Do anlegen" also without a link', async () => {
    const { cmp } = await withActions(true);
    expect(screen.getByRole('heading', { name: 'Verknüpft' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Verknüpfen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'To-Do anlegen' })).toBeInTheDocument();
    expect(cmp.showActions()).toBe(true);
  });

  it('shows "Verknüpfen" without "To-Do anlegen" to a person who changes the element only', async () => {
    await withActions(false, linksOf([], [], true));
    expect(screen.getByRole('button', { name: 'Verknüpfen' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'To-Do anlegen' })).toBeNull();
  });

  it('opens the create dialog of an Antrag with the link and the board of its Gremium', async () => {
    const { cmp, fixture } = await withActions(true);
    screen.getByRole('button', { name: 'To-Do anlegen' }).click();
    fixture.detectChanges();
    expect(cmp.newOpen()).toBe(true);
    expect(cmp.newLinks()).toEqual([{ kind: 'application', targetId: 'a-1', label: 'Antrag · Lerncafé' }]);
    expect(cmp.gremiumId()).toBe('g-1');
    expect(document.querySelector('app-todo-new-dialog')).not.toBeNull();
  });

  it('opens the one picker without the element, and links the pick', async () => {
    const { cmp, fixture, api } = await withActions(true, linksOf([card()]));
    screen.getByRole('button', { name: 'Verknüpfen' }).click();
    fixture.detectChanges();
    const picker = fixture.debugElement.query(By.directive(TodoLinkPickerComponent)).componentInstance as TodoLinkPickerComponent;
    expect(cmp.linkOpen()).toBe(true);
    expect(picker.exclude()).toEqual({ kind: 'application', id: 'a-1' });
    expect([...picker.linked()]).toEqual(['todo:k-1']);
    const touch = jest.spyOn(TestBed.inject(TodoLinkedRefresh), 'touch');
    picker.picked.emit({ kind: 'invoice', targetId: 'i-1', title: 'RE-2026-17', detail: {} });
    fixture.detectChanges();
    expect(api.link).toHaveBeenCalledWith({ kind: 'application', id: 'a-1' }, { kind: 'invoice', id: 'i-1' });
    expect(touch).toHaveBeenCalledWith([{ kind: 'invoice', targetId: 'i-1' }]);
    expect(screen.getByRole('link', { name: 'RE-2026-17' })).toBeInTheDocument();
  });

  it('takes a link off with the × of a removable row, and a pick of a linked hit', async () => {
    const out = linksOf([], [linkRow({ id: 'l-2', removable: true }), linkRow({ id: 'l-3', targetId: 'i-3', title: 'RE-3' })]);
    const { cmp, fixture, api } = await withActions(true, out);
    const x = screen.getAllByRole('button', { name: /RE-2026-17/ });
    expect(x).toHaveLength(1);
    x[0].click();
    fixture.detectChanges();
    expect(api.unlink).toHaveBeenCalledWith('l-2');
    expect(screen.queryByRole('link', { name: 'RE-2026-17' })).toBeNull();
    cmp.pick({ kind: 'invoice', targetId: 'i-3', title: 'RE-3', detail: {} });
    expect(api.unlink).toHaveBeenLastCalledWith('l-3');
  });

  it('tells a refused link or removal in a toast', async () => {
    const fail = () => throwError(() => new Error('403'));
    const { cmp } = await withActions(true, linksOf([], [linkRow({ removable: true })]), { link: jest.fn(fail), unlink: jest.fn(fail) });
    const toast = TestBed.inject(ToastService);
    const error = jest.spyOn(kindSpies(toast), 'error');
    cmp.pick({ kind: 'ticket', targetId: 't-1', title: 'T-0001', detail: {} });
    expect(error).toHaveBeenLastCalledWith('Die Verknüpfung ist fehlgeschlagen.');
    cmp.remove(cmp.links()[0]);
    expect(error).toHaveBeenLastCalledWith('Die Verknüpfung konnte nicht entfernt werden.');
  });

  /** Spec 000582: the section with actions and no row shows the empty state. */
  it('shows the empty state below the actions when nothing is linked', async () => {
    await withActions(true);
    expect(screen.getByRole('heading', { name: 'Verknüpft' })).toBeInTheDocument();
    expect(screen.getByText('Nichts verknüpft')).toBeInTheDocument();
  });

  /** Spec 000758: without Boards the section keeps its links and has no "To-Do anlegen". */
  it('keeps the links and shows no "To-Do anlegen" while Boards is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['todos']));
    const { api, cmp } = await withActions(true, linksOf([], [linkRow()]));
    localStorage.removeItem('ap.features.off');
    expect(api.links).toHaveBeenCalled();
    expect(api.boards).not.toHaveBeenCalled();
    expect(cmp.showNew()).toBe(false);
    expect(screen.getByRole('link', { name: 'RE-2026-17' })).toBeInTheDocument();
  });

  it('hides the actions from a person who writes no board and changes nothing', async () => {
    await withActions(false);
    expect(screen.queryByRole('button', { name: 'To-Do anlegen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Verknüpfen' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Verknüpft' })).toBeNull();
  });

  it('reads no boards without actions, and shows the empty state it is given', async () => {
    const api = { links: jest.fn(() => of(linksOf())), boards: jest.fn(() => of([])) };
    await render(TodoLinkedListComponent, {
      inputs: { kind: 'meeting', targetId: 'm-1', emptyHeading: 'Nichts mit dieser Sitzung verknüpft' },
      providers: [provideRouter([]), { provide: TodosApiService, useValue: api }],
    });
    expect(api.boards).not.toHaveBeenCalled();
    expect(screen.getByText('Nichts mit dieser Sitzung verknüpft')).toBeInTheDocument();
  });

  it('reads the list again after a new card', async () => {
    const { cmp, api } = await withActions(true);
    expect(api.links).toHaveBeenCalledTimes(1);
    cmp.created();
    TestBed.tick();
    expect(api.links).toHaveBeenCalledTimes(2);
  });
});
