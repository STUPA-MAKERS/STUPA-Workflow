import { render, screen } from '@testing-library/angular';
import type { TodoCardTile } from '@core/api/todos.service';
import { TODAY, board, link, tile } from '../../../../testing/todo-fixtures';
import { TodoCardTileComponent } from './todo-card-tile.component';

const LABELS = new Map([
  ...board().labels.map((l) => [l.id, l] as const),
  ['l-3', { id: 'l-3', name: 'Dritte', color: 'red' as const }],
]);

async function setup(card: TodoCardTile, extra: { done?: boolean; lifted?: boolean; column?: string | null } = {}) {
  const open = jest.fn();
  const view = await render(TodoCardTileComponent, {
    inputs: { card, labels: LABELS, today: TODAY, ...extra },
    on: { open },
  });
  return { ...view, open };
}

describe('TodoCardTileComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows at most two labels, the title, the link, the due date and the counts', async () => {
    const { open, fixture } = await setup(
      tile({
        labelIds: ['l-1', 'l-x', 'l-2', 'l-3'],
        dueDate: '2026-10-14',
        checklist: { done: 1, total: 3 },
        commentCount: 2,
        primaryLink: link({ kind: 'meeting', title: 'Sondersitzung', detail: { date: '2026-11-03' } }),
      }),
    );
    expect(screen.getByText('Haushalt')).toBeInTheDocument();
    expect(screen.getByText('Sitzung')).toBeInTheDocument();
    expect(screen.queryByText('Dritte')).toBeNull();
    expect(screen.getByText('Sitzung · Sondersitzung · Di, 03.11.')).toBeInTheDocument();
    expect(screen.getByText(/14\.10\. · überfällig/).closest('.tt__fact')).toHaveClass('tdu--overdue');
    expect(screen.getByRole('img', { name: 'Checkliste 1 von 3' })).toHaveTextContent('1/3');
    expect(screen.getByRole('img', { name: '2 Kommentare' })).toHaveTextContent('2');
    expect(screen.getByRole('img', { name: 'Niemand zuständig' })).toBeInTheDocument();
    const title = screen.getByRole('button', { name: 'Protokoll gegenlesen' });
    expect(title).toHaveAttribute('data-card-id', 'k-1');
    title.click();
    expect(open).toHaveBeenCalled();
    expect(fixture.nativeElement).not.toHaveClass('tt--lifted');
  });

  it('shows the column tag only when a list asks for it', async () => {
    const view = await setup(tile(), { column: 'In Arbeit' });
    expect(screen.getByText('In Arbeit', { selector: '.tt__col' })).toHaveAttribute('title', 'In Arbeit');
    view.fixture.componentRef.setInput('column', null);
    view.fixture.detectChanges();
    expect(view.container.querySelector('.tt__col')).toBeNull();
  });

  it('marks a date of tomorrow as soon and a later date plainly', async () => {
    const view = await setup(tile({ dueDate: '2026-10-17' }));
    expect(screen.getByText(/17\.10\. · morgen/).closest('.tt__fact')).toHaveClass('tdu--soon');
    view.fixture.componentRef.setInput('card', tile({ dueDate: '2026-10-30' }));
    view.fixture.detectChanges();
    const fact = screen.getByText('30.10.').closest('.tt__fact');
    expect(fact).not.toHaveClass('tdu--soon');
    expect(fact).not.toHaveClass('tdu--overdue');
  });

  it('shows the people of the card and no counts without them', async () => {
    const { container } = await setup(
      tile({ assignees: [{ principalId: 'p-1', displayName: 'Selin' }, { principalId: null, displayName: null }] }),
    );
    expect(container.querySelector('app-avatar-stack')).not.toBeNull();
    expect(screen.queryByRole('img', { name: 'Niemand zuständig' })).toBeNull();
    expect(container.querySelector('.tt__labels')).toBeNull();
    expect(container.querySelector('.tt__link')).toBeNull();
    expect(container.querySelectorAll('.tt__fact')).toHaveLength(0);
  });

  it('shows a done card with its done date and no due date', async () => {
    const { container, fixture } = await setup(
      tile({ dueDate: '2026-10-01', completedAt: '2026-10-10T10:00:00Z' }),
      { done: true, lifted: true },
    );
    expect(container.querySelector('.tt__doneIcon')).not.toBeNull();
    expect(screen.getByText('10.10.')).toBeInTheDocument();
    expect(screen.queryByText(/01\.10\./)).toBeNull();
    expect(fixture.nativeElement).toHaveClass('tt--lifted');
  });

  it('shows no done date without a valid completion time', async () => {
    const view = await setup(tile({ completedAt: null }), { done: true });
    expect(view.container.querySelectorAll('.tt__fact')).toHaveLength(0);
    view.fixture.componentRef.setInput('card', tile({ completedAt: 'bad' }));
    view.fixture.detectChanges();
    expect(view.container.querySelectorAll('.tt__fact')).toHaveLength(0);
  });
});
