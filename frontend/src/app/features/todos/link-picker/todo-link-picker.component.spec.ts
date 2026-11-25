import { provideTestStatuses } from '@core/api/statuses.service';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TodosApiService, type TodoLinkTarget } from '@core/api/todos.service';
import { PaperlessService } from '@core/api/paperless.service';
import { AuthService } from '@core/auth/auth.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { asPhone } from '../../../../testing/todo-fixtures';
import { TodoLinkPickerComponent, linkKey } from './todo-link-picker.component';

const HITS: TodoLinkTarget[] = [
  { kind: 'application', targetId: 'a-1', title: 'Haushalt 2027', detail: {} },
  { kind: 'meeting', targetId: 'm-1', title: 'Sondersitzung Haushalt', detail: { date: '2026-11-03' } },
  { kind: 'agenda_item', targetId: 't-1', title: 'TOP Haushalt', detail: { position: 2 } },
  { kind: 'todo', targetId: 'k-2', title: 'Haushalt Kapitel 3', detail: { boardName: 'StuPa' } },
];

const found = (hits: TodoLinkTarget[], paperlessDown = false) => ({ hits, paperlessDown });

async function setup(opts: { fail?: boolean; linked?: string[]; budgetWrite?: boolean; paperless?: boolean } = {}) {
  const linkSearch = jest.fn(() => (opts.fail ? throwError(() => new Error('x')) : of(found(HITS))));
  const picked = jest.fn();
  const view = await render(TodoLinkPickerComponent, {
    inputs: { open: false, exclude: { kind: 'todo', id: 'k-1' }, linked: new Set(opts.linked ?? []) },
    on: { picked },
    providers: [
      provideTestStatuses(),
      { provide: TodosApiService, useValue: { linkSearch } },
      { provide: PaperlessService, useValue: { linksOn: () => of(opts.paperless ?? false) } },
      ...(opts.budgetWrite === undefined
        ? []
        : [{ provide: AuthService, useValue: { can: () => opts.budgetWrite } }]),
    ],
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
  return { ...view, linkSearch, picked, open, type };
}

describe('TodoLinkPickerComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => jest.restoreAllMocks());

  it('keys a target by kind and id', () => {
    expect(linkKey('ticket', 't-1')).toBe('ticket:t-1');
  });

  /** The panel floats at the end of <body>, outside the parent that holds the picker. */
  it('shows nothing while closed and a panel with the focus in the field when open', async () => {
    const { open, fixture, container } = await setup();
    expect(container.querySelector('.lp')).toBeNull();
    await open();
    const panel = screen.getByRole('dialog', { name: 'Verknüpfen' });
    expect(container.contains(panel)).toBe(false);
    expect(panel.closest('.lp-layer')?.parentElement).toBe(document.body);
    expect(document.activeElement).toBe(screen.getByRole('searchbox'));
    fixture.componentInstance.open.set(false);
    fixture.detectChanges();
    expect(document.querySelector('.lp-layer')).toBeNull();
  });

  it('opens on the first render when open is true from the start', async () => {
    const linkSearch = jest.fn(() => of(found(HITS)));
    await render(TodoLinkPickerComponent, {
      inputs: { open: true, exclude: { kind: 'todo', id: 'k-1' }, linked: new Set<string>() },
      providers: [provideTestStatuses(), { provide: TodosApiService, useValue: { linkSearch } }],
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

  /** In the middle, the browser moves the focus. */
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

  /** An empty field takes the hits away at once. */
  it('searches, groups the hits and marks a linked target', async () => {
    const { open, type, linkSearch, picked } = await setup({ linked: ['application:a-1'] });
    await open();
    type('Haushalt');
    expect(linkSearch).toHaveBeenLastCalledWith('Haushalt', 'all', { kind: 'todo', id: 'k-1' });
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
    fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
    expect(screen.queryByText('Anträge', { selector: '.lp__group' })).toBeNull();
  });

  /** The icons are those of the navigation: Abstimmungen, Gremien, Rechnungen, Buchungen. */
  it('groups votes, gremien, invoices and bookings with their icons', async () => {
    const hits: TodoLinkTarget[] = [
      { kind: 'vote', targetId: 'v-1', title: 'Plakate annehmen?', detail: { voteStatus: 'open' } },
      { kind: 'appointment', targetId: 'a-1', title: 'Vollversammlung', detail: { date: '2026-11-18', place: 'Aula' } },
      { kind: 'gremium', targetId: 'g-1', title: 'StuPa', detail: {} },
      { kind: 'invoice', targetId: 'i-1', title: 'RE-7', detail: { number: 'RE-7', counterparty: 'Druckhaus' } },
      { kind: 'expense', targetId: 'e-1', title: 'Plakate', detail: { costCentre: 'VS-800' } },
      { kind: 'order', targetId: 'o-1', title: 'Beamer', detail: { orderStatus: 'ordered' } },
    ];
    const { open, type, linkSearch, picked, fixture } = await setup();
    linkSearch.mockReturnValue(of(found(hits)));
    await open();
    type('Pla');
    const groups = [...document.querySelectorAll('.lp__group')].map((g) => g.textContent?.trim());
    expect(groups).toEqual(['Abstimmungen', 'Termine', 'Gremien', 'Rechnungen', 'Buchungen', 'Bestellungen']);
    expect(screen.getByText('Bestellung · Bestellt')).toBeInTheDocument();
    expect(screen.getByText('Termin · Mi, 18.11.2026 · Aula')).toBeInTheDocument();
    expect(screen.getByText('Abstimmung · Offen')).toBeInTheDocument();
    expect(screen.getByText('Rechnung · Druckhaus')).toBeInTheDocument();
    expect(screen.getByText('Buchung · VS-800')).toBeInTheDocument();
    expect(hits.map((h) => fixture.componentInstance.icon(h))).toEqual(['vote', 'cal', 'landmark', 'receipt', 'swap', 'package']);
    fireEvent.click(screen.getByRole('button', { name: /StuPa/ }));
    expect(picked).toHaveBeenCalledWith(hits[2]);
    for (const [label, kind] of [
      ['Abstimmungen', 'vote'],
      ['Termine', 'appointment'],
      ['Gremien', 'gremium'],
      ['Rechnungen', 'invoice'],
      ['Buchungen', 'expense'],
      ['Bestellungen', 'order'],
    ] as const) {
      fireEvent.click(screen.getByRole('button', { name: label }));
      expect(linkSearch).toHaveBeenLastCalledWith('Pla', kind, { kind: 'todo', id: 'k-1' });
    }
  });

  it('narrows the kind and searches again; the same kind does nothing', async () => {
    const { open, type, linkSearch } = await setup();
    await open();
    type('Haushalt');
    const calls = linkSearch.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Alle' }));
    expect(linkSearch).toHaveBeenCalledTimes(calls);
    fireEvent.click(screen.getByRole('button', { name: 'TOPs' }));
    expect(screen.getByRole('button', { name: 'TOPs' })).toHaveAttribute('aria-pressed', 'true');
    expect(linkSearch).toHaveBeenLastCalledWith('Haushalt', 'agenda_item', { kind: 'todo', id: 'k-1' });
  });

  it('shows the shared empty state when nothing matches', async () => {
    const empty = await setup();
    empty.linkSearch.mockReturnValue(of(found([])));
    await empty.open();
    empty.type('zz');
    expect(screen.getByText('Keine Treffer.').closest('app-empty-state')).not.toBeNull();
  });

  it('says when the search fails', async () => {
    const failing = await setup({ fail: true });
    await failing.open();
    failing.type('zz');
    expect(screen.getByText('Die Suche ist fehlgeschlagen.')).toBeInTheDocument();
  });

  it('does not offer the kind Paperless while the links to Paperless are off (002767)', async () => {
    const { open } = await setup();
    await open();
    expect(screen.getByRole('button', { name: 'To-Dos' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Paperless' })).toBeNull();
  });

  it('lists the newest documents of the kind Paperless and links a hit (002766)', async () => {
    const doc: TodoLinkTarget = {
      kind: 'paperless',
      targetId: 'p-41',
      title: 'Angebot Beamer',
      detail: { documentType: 'Angebot', date: '2026-10-30' },
    };
    const { open, type, linkSearch, picked } = await setup({ paperless: true });
    linkSearch.mockReturnValue(of(found([doc])));
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Paperless' }));
    expect(linkSearch).toHaveBeenLastCalledWith('', 'paperless', { kind: 'todo', id: 'k-1' });
    fireEvent.click(await screen.findByRole('button', { name: /Angebot Beamer/ }));
    expect(picked).toHaveBeenCalledWith(doc);
    type('Beamer');
    expect(linkSearch).toHaveBeenLastCalledWith('Beamer', 'paperless', { kind: 'todo', id: 'k-1' });
  });

  it('keeps the hits of the other kinds and names the outage of Paperless (002766)', async () => {
    const { open, type, linkSearch } = await setup({ paperless: true });
    linkSearch.mockReturnValue(of(found(HITS, true)));
    await open();
    type('Haushalt');
    expect(screen.getByRole('button', { name: /Haushalt 2027/ })).toBeInTheDocument();
    expect(screen.getByText('Paperless ist nicht erreichbar')).toBeInTheDocument();
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

  /**
   * A second closing in the fade starts no second fade. An opening in the fade stops it. A fade
   * that ends after an opening in it leaves the panel.
   */
  it('drops the layer at once under reduced motion, without asking for animations', async () => {
    document.documentElement.setAttribute('data-display-motion', 'reduce');
    try {
      const { open, fixture } = await setup();
      await open();
      const anims = jest.fn(() => [{ finished: new Promise<void>(() => undefined) } as unknown as Animation]);
      Object.defineProperty(screen.getByRole('dialog'), 'getAnimations', { value: anims, configurable: true });
      fixture.componentInstance.open.set(false);
      fixture.detectChanges();
      expect(anims).not.toHaveBeenCalled();
      expect(document.querySelector('.lp-layer')).toBeNull();
    } finally {
      document.documentElement.removeAttribute('data-display-motion');
    }
  });

  it('closes without moving the focus when the element it came from is gone', async () => {
    const { open, fixture } = await setup();
    const before = document.createElement('button');
    document.body.appendChild(before);
    before.focus();
    await open();
    before.remove();
    fixture.componentInstance.open.set(false);
    fixture.detectChanges();
    expect(document.activeElement).not.toBe(before);
    expect(document.querySelector('.lp-layer')).toBeNull();
  });

  it('fades the panel out before the layer goes, and keeps it on an opening in the fade', async () => {
    let finish: () => void = () => undefined;
    const fading = () => [{ finished: new Promise<void>((r) => (finish = r)) } as unknown as Animation];
    const { open, fixture } = await setup();
    await open();
    const panel = screen.getByRole('dialog');
    const anims = jest.fn(fading);
    Object.defineProperty(panel, 'getAnimations', { value: anims, configurable: true });
    const close = () => {
      fixture.componentInstance.open.set(false);
      fixture.detectChanges();
    };
    close();
    expect(panel).toHaveClass('motion-fade-out');
    expect(document.querySelector('.lp-layer')).not.toBeNull();
    (fixture.componentInstance as unknown as { detach(): void }).detach();
    expect(anims).toHaveBeenCalledTimes(1);
    fixture.componentInstance.open.set(true);
    fixture.detectChanges();
    expect(panel).not.toHaveClass('motion-fade-out');
    close();
    finish();
    await fixture.whenStable();
    await Promise.resolve();
    expect(document.querySelector('.lp-layer')).toBeNull();
    await open();
    const again = screen.getByRole('dialog');
    Object.defineProperty(again, 'getAnimations', { value: jest.fn(fading), configurable: true });
    close();
    fixture.componentInstance.open.set(true);
    fixture.detectChanges();
    finish();
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.getByRole('dialog')).toBe(again);
  });

    it('names the close key ⎋ on Apple devices, as the global search does', async () => {
    jest.spyOn(navigator, 'platform', 'get').mockReturnValue('MacIntel');
    const { open } = await setup();
    await open();
    expect(screen.getByRole('button', { name: 'Schließen' })).toHaveTextContent('⎋');
  });

  it('floats like the global search on the phone too, with a × as the close button (spec 001977)', async () => {
    asPhone(MEDIA.phone);
    const { open, fixture, container } = await setup();
    await open();
    const panel = screen.getByRole('dialog', { name: 'Verknüpfen' });
    expect(container.querySelector('app-side-sheet')).toBeNull();
    expect(panel.closest('.lp-layer')?.parentElement).toBe(document.body);
    expect(panel.querySelector('.lp__esc')).toBeNull();
    fireEvent.click(within(panel).getByRole('button', { name: 'Schließen' }));
    expect(fixture.componentInstance.open()).toBe(false);
  });

  /** Spec 000758: the picker offers no kind of a feature that is off. */
  it('offers no chip for the kinds of a feature that is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['tickets', 'budget']));
    const { open } = await setup();
    localStorage.removeItem('ap.features.off');
    await open();
    const chips = screen.getAllByRole('button', { pressed: false }).map((b) => b.textContent?.trim());
    expect(chips).toContain('Sitzungen');
    expect(chips).not.toContain('Tickets');
    expect(chips).not.toContain('Kostenstellen');
    expect(chips).not.toContain('Buchungen');
  });

  it.each([
    [true, true],
    [false, false],
  ])('§F/collaboration/links/001410: a budget write right %s shows cost centres: %s', async (budgetWrite, shown) => {
    const { open } = await setup({ budgetWrite });
    await open();
    const chips = screen.getAllByRole('button', { pressed: false }).map((b) => b.textContent?.trim());
    expect(chips.includes('Kostenstellen')).toBe(shown);
  });
});
