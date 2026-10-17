import { fireEvent, render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TodosApiService, type TodoLinkTarget } from '@core/api/todos.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { asPhone } from '../../../../testing/todo-fixtures';
import { TodoLinkPickerComponent, linkKey } from './todo-link-picker.component';

const HITS: TodoLinkTarget[] = [
  { kind: 'application', targetId: 'a-1', title: 'Haushalt 2027', detail: null },
  { kind: 'meeting', targetId: 'm-1', title: 'Sondersitzung Haushalt', detail: { date: '2026-11-03' } },
  { kind: 'agenda_item', targetId: 't-1', title: 'TOP Haushalt', detail: { position: 2 } },
  { kind: 'todo', targetId: 'k-2', title: 'Haushalt Kapitel 3', detail: { boardName: 'StuPa' } },
];

async function setup(opts: { fail?: boolean; linked?: string[] } = {}) {
  const linkTargets = jest.fn(() => (opts.fail ? throwError(() => new Error('x')) : of(HITS)));
  const picked = jest.fn();
  const view = await render(TodoLinkPickerComponent, {
    inputs: { open: false, excludeCardId: 'k-1', linked: new Set(opts.linked ?? []) },
    on: { picked },
    providers: [{ provide: TodosApiService, useValue: { linkTargets } }],
  });
  const open = async () => {
    view.fixture.componentInstance.open.set(true);
    view.fixture.detectChanges();
    await view.fixture.whenStable();
  };
  const type = (text: string) => {
    fireEvent.input(screen.getByRole('searchbox', { name: 'Suchen' }), { target: { value: text } });
    view.fixture.componentInstance.search.flush();
    view.fixture.detectChanges();
  };
  return { ...view, linkTargets, picked, open, type };
}

describe('TodoLinkPickerComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => jest.restoreAllMocks());

  it('keys a target by kind and id', () => {
    expect(linkKey('ticket', 't-1')).toBe('ticket:t-1');
  });

  it('shows nothing while closed and a panel with the focus in the field when open', async () => {
    const { open, fixture, container } = await setup();
    expect(container.querySelector('.lp')).toBeNull();
    await open();
    const panel = screen.getByRole('dialog', { name: 'Verknüpfen' });
    // The panel floats at the end of <body>, outside the parent that holds the picker.
    expect(container.contains(panel)).toBe(false);
    expect(panel.closest('.lp-layer')?.parentElement).toBe(document.body);
    expect(document.activeElement).toBe(screen.getByRole('searchbox'));
    fixture.componentInstance.open.set(false);
    fixture.detectChanges();
    expect(document.querySelector('.lp-layer')).toBeNull();
  });

  it('opens on the first render when open is true from the start', async () => {
    const linkTargets = jest.fn(() => of(HITS));
    await render(TodoLinkPickerComponent, {
      inputs: { open: true, excludeCardId: 'k-1', linked: new Set<string>() },
      providers: [{ provide: TodosApiService, useValue: { linkTargets } }],
    });
    expect(screen.getByRole('dialog', { name: 'Verknüpfen' }).closest('.lp-layer')?.parentElement).toBe(document.body);
    expect(document.querySelectorAll('.lp-layer')).toHaveLength(1);
  });

  it('closes on the scrim and gives the focus back', async () => {
    const { open, fixture } = await setup();
    const before = document.createElement('button');
    document.body.appendChild(before);
    before.focus();
    await open();
    expect(document.activeElement).toBe(screen.getByRole('searchbox'));
    fireEvent.click(document.querySelector('.lp__scrim')!);
    fixture.detectChanges();
    expect(fixture.componentInstance.open()).toBe(false);
    expect(document.activeElement).toBe(before);
    before.remove();
  });

  it('keeps Tab in the panel and stops it there', async () => {
    const { open } = await setup();
    await open();
    const panel = screen.getByRole('dialog');
    const field = screen.getByRole('searchbox');
    const buttons = [...panel.querySelectorAll<HTMLElement>('button')];
    const last = buttons[buttons.length - 1];
    const outer = jest.fn();
    document.addEventListener('keydown', outer);
    last.focus();
    fireEvent.keyDown(last, { key: 'Tab' });
    expect(document.activeElement).toBe(field);
    fireEvent.keyDown(field, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
    // In the middle, the browser moves the focus.
    buttons[0].focus();
    fireEvent.keyDown(buttons[0], { key: 'Tab' });
    expect(document.activeElement).toBe(buttons[0]);
    expect(outer).not.toHaveBeenCalled();
    document.removeEventListener('keydown', outer);
  });

  it('removes the floating panel when it is destroyed open', async () => {
    const { open, fixture } = await setup();
    await open();
    fixture.destroy();
    expect(document.querySelector('.lp-layer')).toBeNull();
  });

  it('searches, groups the hits and marks a linked target', async () => {
    const { open, type, linkTargets, picked } = await setup({ linked: ['application:a-1'] });
    await open();
    type('Haushalt');
    expect(linkTargets).toHaveBeenLastCalledWith('Haushalt', 'all', 'k-1');
    expect(screen.getByText('Anträge', { selector: '.lp__group' })).toBeInTheDocument();
    expect(screen.getByText('Sitzungen und TOPs')).toBeInTheDocument();
    expect(screen.getByText('To-Dos', { selector: '.lp__group' })).toBeInTheDocument();
    expect(screen.queryByText('Tickets', { selector: '.lp__group' })).toBeNull();
    const app = screen.getByRole('button', { name: /Haushalt 2027/ });
    expect(app).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Sondersitzung Haushalt/ })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('Sitzung · Di, 03.11.2026')).toBeInTheDocument();
    fireEvent.click(app);
    expect(picked).toHaveBeenCalledWith(HITS[0]);
    // An empty field takes the hits away at once.
    fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
    expect(screen.queryByText('Anträge', { selector: '.lp__group' })).toBeNull();
  });

  it('groups votes, gremien, invoices and bookings with their icons', async () => {
    const hits: TodoLinkTarget[] = [
      { kind: 'vote', targetId: 'v-1', title: 'Plakate annehmen?', detail: { voteStatus: 'open' } },
      { kind: 'gremium', targetId: 'g-1', title: 'StuPa', detail: {} },
      { kind: 'invoice', targetId: 'i-1', title: 'RE-7', detail: { number: 'RE-7', counterparty: 'Druckhaus' } },
      { kind: 'expense', targetId: 'e-1', title: 'Plakate', detail: { costCentre: 'VS-800' } },
    ];
    const { open, type, linkTargets, picked, fixture } = await setup();
    linkTargets.mockReturnValue(of(hits));
    await open();
    type('Pla');
    const groups = [...document.querySelectorAll('.lp__group')].map((g) => g.textContent?.trim());
    expect(groups).toEqual(['Abstimmungen', 'Gremien', 'Rechnungen', 'Buchungen']);
    expect(screen.getByText('Abstimmung · Offen')).toBeInTheDocument();
    expect(screen.getByText('Rechnung · Druckhaus')).toBeInTheDocument();
    expect(screen.getByText('Buchung · VS-800')).toBeInTheDocument();
    // The icons of the navigation: Abstimmungen, Gremien, Rechnungen, Buchungen.
    expect(hits.map((h) => fixture.componentInstance.icon(h))).toEqual(['vote', 'landmark', 'receipt', 'swap']);
    fireEvent.click(screen.getByRole('button', { name: /StuPa/ }));
    expect(picked).toHaveBeenCalledWith(hits[1]);
    for (const [label, kind] of [
      ['Abstimmungen', 'vote'],
      ['Gremien', 'gremium'],
      ['Rechnungen', 'invoice'],
      ['Buchungen', 'expense'],
    ] as const) {
      fireEvent.click(screen.getByRole('button', { name: label }));
      expect(linkTargets).toHaveBeenLastCalledWith('Pla', kind, 'k-1');
    }
  });

  it('narrows the kind and searches again; the same kind does nothing', async () => {
    const { open, type, linkTargets } = await setup();
    await open();
    type('Haushalt');
    const calls = linkTargets.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Alle' }));
    expect(linkTargets).toHaveBeenCalledTimes(calls);
    fireEvent.click(screen.getByRole('button', { name: 'TOPs' }));
    expect(screen.getByRole('button', { name: 'TOPs' })).toHaveAttribute('aria-pressed', 'true');
    expect(linkTargets).toHaveBeenLastCalledWith('Haushalt', 'agenda_item', 'k-1');
  });

  it('says when nothing matches', async () => {
    const empty = await setup();
    empty.linkTargets.mockReturnValue(of([]));
    await empty.open();
    empty.type('zz');
    expect(screen.getByText('Keine Treffer.')).toBeInTheDocument();
  });

  it('says when the search fails', async () => {
    const failing = await setup({ fail: true });
    await failing.open();
    failing.type('zz');
    expect(screen.getByText('Die Suche ist fehlgeschlagen.')).toBeInTheDocument();
  });

  it('closes with the × and with Escape', async () => {
    const { open, fixture } = await setup();
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(fixture.componentInstance.open()).toBe(false);
    await open();
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'a' });
    expect(fixture.componentInstance.open()).toBe(true);
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(fixture.componentInstance.open()).toBe(false);
  });

  it('uses the bottom sheet on the phone', async () => {
    asPhone(MEDIA.phone);
    const { open, container } = await setup();
    await open();
    expect(container.querySelector('.lp--sheet')).not.toBeNull();
    expect(container.querySelector('.lp__x')).toBeNull();
  });
});
