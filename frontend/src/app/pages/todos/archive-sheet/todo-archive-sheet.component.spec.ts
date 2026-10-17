import { fireEvent, render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import type { Page } from '@core/api/models';
import { TodosApiService, type TodoCardTile } from '@core/api/todos.service';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { asPhone, detail, tile } from '../../../../testing/todo-fixtures';
import { ARCHIVE_PAGE, TodoArchiveSheetComponent } from './todo-archive-sheet.component';

const page = (items: TodoCardTile[], total = items.length): Page<TodoCardTile> => ({
  items,
  total,
  limit: ARCHIVE_PAGE,
  offset: 0,
});

const A = tile({ id: 'a-1', title: 'Bus anfragen', completedAt: '2026-10-10T10:00:00Z' });
const B = tile({ id: 'a-2', title: 'Plakat', completedAt: null });
const C = tile({ id: 'a-3', title: 'Flyer', completedAt: 'bad' });

async function setup(first: Page<TodoCardTile> = page([A, B], 3)) {
  const api = {
    archive: jest.fn(() => of(first)),
    restoreCard: jest.fn(() => of(detail({ id: 'a-1' }))),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const on = { openCard: jest.fn(), restored: jest.fn() };
  const view = await render(TodoArchiveSheetComponent, {
    inputs: { open: false, boardId: 'b-1' },
    on,
    providers: [
      { provide: TodosApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  const cmp = view.fixture.componentInstance;
  cmp.open.set(true);
  view.fixture.detectChanges();
  return { ...view, api, toast, cmp, ...on, detect: () => view.fixture.detectChanges() };
}

describe('TodoArchiveSheetComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => jest.restoreAllMocks());

  it('lists the archived cards with their done date and pages on', async () => {
    const { api, cmp, detect } = await setup();
    expect(api.archive).toHaveBeenCalledWith('b-1', '', 0, ARCHIVE_PAGE);
    expect(screen.getByText('erledigt am 10.10.')).toBeInTheDocument();
    expect(cmp.doneOn(B)).toBe('');
    expect(cmp.doneOn(C)).toBe('');
    api.archive.mockReturnValueOnce(of(page([C], 3)));
    fireEvent.click(screen.getByRole('button', { name: 'Mehr laden' }));
    detect();
    expect(api.archive).toHaveBeenLastCalledWith('b-1', '', 2, ARCHIVE_PAGE);
    expect(cmp.items().map((c) => c.id)).toEqual(['a-1', 'a-2', 'a-3']);
    expect(screen.queryByRole('button', { name: 'Mehr laden' })).toBeNull();
  });

  it('searches the archive and resets on an empty field', async () => {
    const { api, cmp, detect } = await setup();
    api.archive.mockReturnValueOnce(of(page([A])));
    cmp.search.set('Bus');
    cmp.search.flush();
    detect();
    expect(api.archive).toHaveBeenLastCalledWith('b-1', 'Bus', 0, ARCHIVE_PAGE);
    expect(cmp.items()).toEqual([A]);
    cmp.search.clear();
    expect(api.archive).toHaveBeenLastCalledWith('b-1', '', 0, ARCHIVE_PAGE);
    expect(cmp.items()).toHaveLength(2);
  });

  it('says when it is empty and when it fails', async () => {
    const { api, cmp, detect } = await setup(page([]));
    expect(screen.getByText('Keine archivierten Karten.')).toBeInTheDocument();
    api.archive.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.search.set('zz');
    cmp.search.flush();
    detect();
    expect(screen.getByRole('alert')).toHaveTextContent('Das Archiv konnte nicht geladen werden.');
    expect(cmp.loading()).toBe(false);
    api.archive.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.more();
    expect(cmp.failed()).toBe(true);
  });

  it('opens a card and restores one', async () => {
    const { api, cmp, openCard, restored, toast, detect } = await setup();
    const restoreButton = screen.getByRole('button', { name: '„Bus anfragen“ wiederherstellen' });
    // A tonal button with the undo icon before its label.
    expect(restoreButton).toHaveClass('btn--tonal');
    expect(restoreButton.querySelector('app-icon')).toHaveAttribute('name', 'undo');
    expect(restoreButton).toHaveTextContent('Wiederherstellen');
    fireEvent.click(restoreButton);
    expect(api.restoreCard).toHaveBeenCalledWith('a-1');
    expect(restored).toHaveBeenCalledWith(detail({ id: 'a-1' }));
    expect(cmp.total()).toBe(2);
    detect();
    expect(screen.queryByText('Bus anfragen')).toBeNull();
    api.restoreCard.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.restore(B);
    expect(toast.error).toHaveBeenCalledWith('Die Änderung konnte nicht gespeichert werden.');
    cmp.total.set(0);
    api.restoreCard.mockReturnValueOnce(of(detail({ id: 'a-2' })));
    cmp.restore(B);
    expect(cmp.total()).toBe(0);
    fireEvent.click(screen.getByRole('button', { name: /^Plakat/ }));
    expect(openCard).toHaveBeenCalledWith('a-2');
    expect(cmp.open()).toBe(false);
  });

  it('opens from the bottom on the phone', async () => {
    asPhone(MEDIA.phone);
    const { container } = await setup();
    expect(container.ownerDocument.querySelector('.ss--bottom')).not.toBeNull();
  });
});
