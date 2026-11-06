import { render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TodosApiService, type TodoLinkView } from '@core/api/todos.service';
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
    { key: 'paymentDate', label: null, value: '2026-11-03', format: 'date' },
    { key: 'zweck', label: { de: 'Zweck', en: 'Purpose' }, value: 'Party', format: 'text' },
    { key: 'note', label: null, value: 'Beleg **folgt**', format: 'markdown' },
  ],
  rows: [],
};

async function setup(view: TodoLinkView | null = VIEW) {
  localStorage.setItem('ap.locale', 'de');
  const api = { linkView: jest.fn(() => (view ? of(view) : throwError(() => new Error('404')))) };
  const r = await render(TodoLinkViewComponent, {
    inputs: { cardId: 'c-1', link: BOOKING, open: true },
    providers: [{ provide: TodosApiService, useValue: api }],
  });
  r.fixture.detectChanges();
  return { ...r, api };
}

describe('TodoLinkViewComponent', () => {
  it('reads the linked Buchung through the card and shows its facts read only', async () => {
    const { api } = await setup();
    expect(api.linkView).toHaveBeenCalledWith('c-1', 'l-1');
    expect(screen.getByRole('heading', { name: 'Getränke' })).toBeInTheDocument();
    const sheet = screen.getByTestId('link-view');
    expect(sheet).toHaveTextContent('Betrag');
    expect(sheet).toHaveTextContent('300,00');
    expect(sheet).toHaveTextContent('Einnahme');
    expect(sheet).toHaveTextContent('03.11.2026');
    expect(sheet).toHaveTextContent('Zweck');
    expect(sheet).toHaveTextContent('Party');
    expect(sheet.querySelector('strong')).toHaveTextContent('folgt');
    expect(sheet.querySelector('input, textarea, a[href]')).toBeNull();
  });

  it('numbers the agenda of a meeting and translates the result of a vote', async () => {
    const { fixture } = await setup({
      kind: 'meeting',
      title: 'StuPa 3',
      detail: {},
      facts: [],
      rows: [
        { title: 'Begrüßung', meta: null, done: true },
        { title: 'Erstiparty', meta: null, done: false },
      ],
    });
    const sheet = screen.getByTestId('link-view');
    expect(sheet).toHaveTextContent('Tagesordnung');
    expect(sheet).toHaveTextContent('TOP 2');
    expect(fixture.componentInstance.rowMeta(0, 'passed')).toBe('TOP 1');
  });

  it('says so when the sheet cannot be read', async () => {
    await setup(null);
    expect(screen.getByTestId('link-view')).toHaveTextContent('Konnte nicht geladen werden.');
  });
});
