import { render, screen } from '@testing-library/angular';
import { NEVER, of, throwError } from 'rxjs';
import { TodosApiService, type TodoLink, type TodoLinkView } from '@core/api/todos.service';
import { link } from '../../../../testing/todo-fixtures';
import { TodoLinkViewComponent } from './todo-link-view.component';

const BOOKING = link({
  id: 'l-1',
  kind: 'expense',
  targetId: 'x-1',
  title: 'Getränke',
  url: null,
  granted: true,
  detail: { amount: '300.00', costCentre: 'VS-800' },
});

const VIEW: TodoLinkView = {
  kind: 'expense',
  title: 'Getränke',
  detail: { amount: '300.00' },
  facts: [
    { key: 'amount', label: null, value: '300.00', format: 'money' },
    { key: 'bookingKind', label: null, value: 'income', format: 'text' },
    { key: 'paymentMethod', label: null, value: 'ueberweisung', format: 'text' },
    { key: 'category', label: null, value: 'Getränke', format: 'text' },
    { key: 'paymentDate', label: null, value: '2026-11-03', format: 'date' },
    { key: 'zweck', label: { de: 'Zweck', en: 'Purpose' }, value: 'Party', format: 'text' },
    { key: 'note', label: null, value: 'Beleg **folgt**', format: 'markdown' },
  ],
  rows: [],
};

function view(over: Partial<TodoLinkView>): TodoLinkView {
  return { ...VIEW, facts: [], ...over };
}

async function setup(answer: TodoLinkView | null | 'never' = VIEW, first: TodoLink | null = BOOKING) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    linkView: jest.fn(() => (answer === 'never' ? NEVER : answer ? of(answer) : throwError(() => new Error('404')))),
  };
  const r = await render(TodoLinkViewComponent, {
    inputs: { cardId: 'c-1', link: first, open: true },
    providers: [{ provide: TodosApiService, useValue: api }],
  });
  r.fixture.detectChanges();
  return { ...r, api, cmp: r.fixture.componentInstance };
}

describe('TodoLinkViewComponent', () => {
  it('reads the linked Buchung through the card and shows its facts read only', async () => {
    const { api } = await setup();
    expect(api.linkView).toHaveBeenCalledWith('c-1', 'l-1');
    expect(screen.getByRole('heading', { name: 'Getränke', level: 2 })).toBeInTheDocument();
    const sheet = screen.getByTestId('link-view');
    for (const text of ['Betrag', '300,00', 'Einnahme', 'Überweisung', 'Getränke', '03.11.2026', 'Zweck', 'Party', 'Anmerkungen']) {
      expect(sheet).toHaveTextContent(text);
    }
    expect(sheet.querySelector('strong')).toHaveTextContent('folgt');
    expect(sheet.querySelector('input, textarea, a[href]')).toBeNull();
  });

  it('shows the title of the link while the sheet loads', async () => {
    await setup('never');
    expect(screen.getByRole('heading', { name: 'Getränke', level: 2 })).toBeInTheDocument();
    expect(screen.getByTestId('link-view').querySelector('.skel-in')).not.toBeNull();
  });

  it('reads nothing without a link and drops the read of a link it left', async () => {
    const { api, fixture, cmp } = await setup(VIEW, null);
    expect(api.linkView).not.toHaveBeenCalled();
    expect([cmp.heading(), cmp.sub(), cmp.icon()]).toEqual(['', '', 'circleok']);
    fixture.componentRef.setInput('link', BOOKING);
    fixture.detectChanges();
    fixture.componentRef.setInput('link', { ...BOOKING, id: 'l-2' });
    fixture.detectChanges();
    expect(api.linkView).toHaveBeenLastCalledWith('c-1', 'l-2');
    expect(cmp.heading()).toBe('Getränke');
  });

  it('numbers the agenda of a meeting', async () => {
    const { cmp } = await setup(
      view({ kind: 'meeting', title: 'StuPa 3', rows: [{ title: 'Begrüßung', meta: null, done: true }, { title: 'Erstiparty', meta: null, done: false }] }),
    );
    const sheet = screen.getByTestId('link-view');
    expect(sheet).toHaveTextContent('Tagesordnung');
    expect(sheet).toHaveTextContent('TOP 2');
    expect(cmp.rowMeta(0, 'passed')).toBe('TOP 1');
  });

  it('names the result or the status of each vote of a TOP', async () => {
    const { cmp } = await setup(
      view({ kind: 'agenda_item', title: 'TOP 3', rows: [{ title: 'Getränke?', meta: 'passed', done: true }] }),
    );
    expect(screen.getByTestId('link-view')).toHaveTextContent('Abstimmungen');
    expect(cmp.rowMeta(0, 'passed')).toBe('Angenommen');
    expect(cmp.rowMeta(0, 'open')).not.toBe('open');
    expect(cmp.rowMeta(0, 'odd')).toBe('odd');
    expect(cmp.rowMeta(0, null)).toBe('');
  });

  it('heads the checklist of a card and no list of a Buchung', async () => {
    const { cmp, fixture } = await setup(view({ kind: 'todo', rows: [{ title: 'Plakate', meta: null, done: null }] }));
    expect(screen.getByTestId('link-view')).toHaveTextContent('Checkliste');
    expect(screen.getByTestId('link-view').querySelector('.lv__check')).toBeNull();
    fixture.componentRef.setInput('link', { ...BOOKING, id: 'l-3' });
    fixture.detectChanges();
    expect(cmp.view()?.kind).toBe('todo');
    expect(cmp.rowsHeading(VIEW)).toBe('');
  });

  it('says so when the sheet cannot be read', async () => {
    await setup(null);
    expect(screen.getByTestId('link-view')).toHaveTextContent('Konnte nicht geladen werden.');
  });
});
