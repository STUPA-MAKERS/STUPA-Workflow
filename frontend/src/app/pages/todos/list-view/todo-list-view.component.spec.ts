import { fireEvent, render, screen, within } from '@testing-library/angular';
import type { TodoBoard } from '@core/api/todos.service';
import { cardsOf } from '../../../features/todos/todos.util';
import { TODAY, board, link, tile } from '../../../../testing/todo-fixtures';
import { TodoListViewComponent } from './todo-list-view.component';

function mapOf(b: TodoBoard) {
  return new Map(b.columns.map((c) => [c.id, cardsOf(b, c.id)]));
}

const CARDS = [
  tile({ id: 'k-1', title: 'Ohne Datum', labelIds: ['l-x', 'l-2', 'l-1'], primaryLink: link({ title: 'Lerncafé' }) }),
  tile({ id: 'k-2', title: 'Spät', dueDate: '2026-11-20', assignees: [{ principalId: 'p-1', displayName: 'Selin' }] }),
  tile({ id: 'k-3', title: 'Überfällig', dueDate: '2026-10-10' }),
  tile({ id: 'k-4', title: 'Auch ohne' }),
  tile({ id: 'k-5', title: 'Erledigt eins', columnId: 'c-4', dueDate: '2026-10-01' }),
];

async function setup(b: TodoBoard = board({ cards: CARDS })) {
  const openCard = jest.fn();
  const toggleDone = jest.fn();
  const view = await render(TodoListViewComponent, {
    inputs: { board: b, cards: mapOf(b), labels: new Map(b.labels.map((l) => [l.id, l])), today: TODAY },
    on: { openCard, toggleDone },
  });
  const titles = () =>
    within(screen.getByRole('rowgroup', { name: 'Offen' }))
      .queryAllByRole('button', { name: /^(?!.*erledigen)/ })
      .filter((b) => b.classList.contains('lv__open'))
      .map((b) => b.textContent?.trim());
  return { ...view, openCard, toggleDone, cmp: view.fixture.componentInstance, titles };
}

describe('TodoListViewComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the cards per column with link, label, due date and people', async () => {
    const { openCard, toggleDone } = await setup();
    expect(screen.getByRole('table', { name: 'Studierendenparlament' })).toBeInTheDocument();
    expect(screen.getByText('Antrag · Lerncafé')).toBeInTheDocument();
    expect(screen.getByText('Sitzung')).toBeInTheDocument();
    expect(screen.getByText('Haushalt')).toBeInTheDocument();
    expect(screen.getByText(/10\.10\. · überfällig/).closest('.lv__due')).toHaveClass('lv__due--overdue');
    expect(screen.getAllByRole('img', { name: 'Niemand zuständig' })).toHaveLength(3);
    expect(within(screen.getByRole('rowgroup', { name: 'In Arbeit' })).getByText('Keine Karten')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Spät' }));
    expect(openCard).toHaveBeenCalledWith('k-2');
    fireEvent.click(screen.getByRole('checkbox', { name: '„Spät“ erledigen' }));
    expect(toggleDone).toHaveBeenCalledWith(CARDS[1]);
  });

  it('folds the done group until it is opened', async () => {
    const { fixture } = await setup();
    const head = screen.getByRole('button', { name: /^Erledigt/ });
    expect(head).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'Erledigt eins' })).toBeNull();
    fireEvent.click(head);
    fixture.detectChanges();
    expect(head).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('checkbox', { name: '„Erledigt eins“ wieder öffnen' })).toHaveAttribute('aria-checked', 'true');
    // A done card shows its date without the overdue colour.
    expect(screen.getByText('01.10.').closest('.lv__due')).not.toHaveClass('lv__due--overdue');
    fireEvent.click(head);
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Erledigt eins' })).toBeNull();
  });

  it('sorts by due date up, down and back, cards without a date last', async () => {
    const { cmp, titles, fixture } = await setup();
    const sortHead = screen.getByRole('columnheader', { name: /Fällig/ });
    expect(titles()).toEqual(['Ohne Datum', 'Spät', 'Überfällig', 'Auch ohne']);
    expect(sortHead).toHaveAttribute('aria-sort', 'none');
    fireEvent.click(screen.getByRole('button', { name: /Fällig/ }));
    fixture.detectChanges();
    expect(titles()).toEqual(['Überfällig', 'Spät', 'Ohne Datum', 'Auch ohne']);
    expect(sortHead).toHaveAttribute('aria-sort', 'ascending');
    cmp.nextSort();
    fixture.detectChanges();
    expect(titles()).toEqual(['Spät', 'Überfällig', 'Ohne Datum', 'Auch ohne']);
    expect(sortHead).toHaveAttribute('aria-sort', 'descending');
    cmp.nextSort();
    fixture.detectChanges();
    expect(cmp.sort()).toBe('none');
  });

  it('locks the circles without the write right and copes with a missing column list', async () => {
    const b = board({ cards: CARDS, canWrite: false });
    const { fixture } = await setup(b);
    expect(screen.getByRole('checkbox', { name: '„Spät“ erledigen' })).toBeDisabled();
    fixture.componentRef.setInput('cards', new Map());
    fixture.detectChanges();
    expect(screen.getAllByText('Keine Karten')).toHaveLength(3);
  });
});
