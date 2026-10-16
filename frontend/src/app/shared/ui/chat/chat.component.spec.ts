import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { ChatComponent } from './chat.component';
import type { ChatEvent, ChatMessage, ChatVisibility } from './chat.models';

/** A time today, so the day separator reads "Heute". */
function today(h: number, m = 0): string {
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toISOString();
}

function daysAgo(n: number, h = 10): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  d.setHours(h, 0, 0, 0);
  return d.toISOString();
}

function msg(id: string, at: string, extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id,
    author: { principalId: 'p-1', displayName: 'Jonas Albrecht' },
    body: `Text ${id}`,
    at,
    own: false,
    ...extra,
  };
}

/** Let `matchMedia` report a phone with a touch pointer (or a desktop, or a narrow window with a mouse). */
function mockPhone(phone: boolean, coarse = phone): void {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('coarse') ? coarse : phone && query.includes('max-width'),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

interface SetupOpts {
  messages?: ChatMessage[];
  events?: ChatEvent[];
  canPost?: boolean;
  visibilityOptions?: ChatVisibility[];
  draftKey?: string;
  phone?: boolean;
  /** A phone width with a mouse or a keyboard (a narrow or zoomed desktop window). */
  fine?: boolean;
}

async function setup(opts: SetupOpts = {}) {
  mockPhone(!!opts.phone || !!opts.fine, !!opts.phone);
  const send = jest.fn();
  const edit = jest.fn();
  const del = jest.fn();
  const retry = jest.fn();
  const view = await render(ChatComponent, {
    inputs: {
      messages: opts.messages ?? [],
      events: opts.events ?? [],
      canPost: opts.canPost ?? true,
      visibilityOptions: opts.visibilityOptions ?? [],
      draftKey: opts.draftKey ?? 't1',
    },
    on: { send, edit, delete: del, retry },
  });
  const set = (name: string, value: unknown) => {
    view.fixture.componentRef.setInput(name, value);
    view.fixture.detectChanges();
  };
  const log = () => screen.getByRole('log');
  const input = () => screen.getByRole('textbox', { name: 'Nachricht schreiben …' }) as HTMLTextAreaElement;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  return { view, send, edit, del, retry, set, log, input, cmp, user: userEvent.setup() };
}

describe('ChatComponent', () => {
  const realMatchMedia = window.matchMedia;
  afterEach(() => {
    window.matchMedia = realMatchMedia;
    localStorage.clear();
    jest.restoreAllMocks();
  });

  it('is a polite log that shows an empty thread', async () => {
    const { log } = await setup();
    expect(log()).toHaveAttribute('aria-live', 'polite');
    expect(log()).toHaveAccessibleName('Verlauf');
    expect(within(log()).getByText('Noch keine Nachrichten.')).toBeInTheDocument();
  });

  it('has no a11y violations', async () => {
    const { view } = await setup({
      visibilityOptions: ['public', 'internal'],
      messages: [
        msg('a', today(9), { visibility: 'internal' }),
        msg('b', today(10), { own: true, visibility: 'public', body: 'https://example.de' }),
        msg('c', today(11), { own: true, state: 'failed' }),
      ],
    });
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('groups messages, puts own ones right and the time under the last', async () => {
    const { view } = await setup({
      messages: [
        msg('a', today(9, 0)),
        msg('b', today(9, 2)),
        msg('c', today(9, 30), { own: true, author: { principalId: 'me', displayName: 'Ich' } }),
      ],
    });
    const rows = view.container.querySelectorAll('.chat__row');
    expect(rows).toHaveLength(3);
    expect(rows[2]).toHaveClass('chat__row--own');
    // One name and one avatar for the group, the own message has neither.
    expect(screen.getAllByText('Jonas Albrecht')).toHaveLength(1);
    expect(view.container.querySelectorAll('app-avatar')).toHaveLength(1);
    expect(rows[0].querySelector('.chat__avSpace')).not.toBeNull();
    expect(rows[0].querySelector('time')).toBeNull();
    expect(rows[1].querySelector('time')?.textContent).toBe('09:02');
    expect(rows[2].querySelector('app-avatar')).toBeNull();
    expect(screen.getByText('Heute')).toBeInTheDocument();
  });

  it('labels the days and shows events small with their time', async () => {
    const old = new Date();
    old.setFullYear(old.getFullYear() - 2);
    const { view } = await setup({
      messages: [msg('y', daysAgo(1)), msg('w', daysAgo(3)), msg('o', old.toISOString())],
      events: [{ id: 'e', at: today(8, 12), text: 'Status: Neu → In Bearbeitung' }],
    });
    const seps = [...view.container.querySelectorAll('.chat__sep')].map((s) => s.textContent?.trim());
    expect(seps).toHaveLength(4);
    expect(seps[0]).toContain(String(old.getFullYear()));
    expect(seps[1]).toMatch(/\d{2}\.\d{2}\.$/);
    expect(seps[2]).toBe('Gestern');
    expect(seps[3]).toBe('Heute');
    expect(view.container.querySelector('.chat__event')?.textContent).toContain('Status: Neu → In Bearbeitung');
    expect(view.container.querySelector('.chat__event time')?.textContent).toBe('08:12');
  });

  it('names an author by label, a deleted person, or no one', async () => {
    const { view } = await setup({
      messages: [
        msg('a', today(9), { authorLabel: 'Studierendenparlament' }),
        msg('b', today(10), { author: { principalId: null, displayName: null } }),
        msg('c', today(11), { author: null }),
      ],
    });
    expect(screen.getByText('Studierendenparlament')).toBeInTheDocument();
    expect(screen.getByText('Gelöschte Person')).toBeInTheDocument();
    const rows = view.container.querySelectorAll('.chat__row');
    expect(rows[2].querySelector('app-avatar, .chat__avSpace, .chat__name')).toBeNull();
  });

  it('marks internal and public only where both exist', async () => {
    const { view, set } = await setup({
      messages: [msg('a', today(9), { visibility: 'internal' }), msg('b', today(10), { visibility: 'internal' })],
    });
    expect(view.container.querySelector('.chat__mark')).toBeNull();
    set('messages', [msg('a', today(9), { visibility: 'internal' }), msg('b', today(10), { visibility: 'public' })]);
    expect(view.container.querySelector('.chat__mark--internal')).toHaveTextContent('Intern');
    expect(view.container.querySelector('.chat__mark--public')).toHaveTextContent('Öffentlich');
    expect(view.container.querySelector('.chat__bubble--internal')).not.toBeNull();
    // A thread that offers both visibilities marks a single one too.
    set('messages', [msg('a', today(9), { visibility: 'internal' })]);
    set('visibilityOptions', ['public', 'internal']);
    expect(view.container.querySelector('.chat__mark--internal')).not.toBeNull();
  });

  it('renders Markdown and links bare URLs in full', async () => {
    await setup({ messages: [msg('a', today(9), { body: '**fett** https://lastenrad.example.de/angebot/2026-1187' })] });
    expect(screen.getByText('fett').tagName).toBe('STRONG');
    const link = screen.getByRole('link', { name: 'https://lastenrad.example.de/angebot/2026-1187' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('lists the attachments of a message', async () => {
    await setup({
      messages: [
        msg('a', today(9), {
          attachments: [
            { id: 'f', filename: 'angebot.pdf', mime: 'application/pdf', size: 10, url: '/api/attachments/f/download' },
            { id: 'g', filename: 'kopf.png', mime: 'image/png', size: 98_304, url: '/api/attachments/g/download' },
            { id: 'h', filename: 'README', mime: 'text/plain', size: 2048, url: '/api/attachments/h/download' },
          ],
        }),
      ],
    });
    expect(screen.getByRole('link', { name: /^angebot\.pdf/ })).toHaveAttribute('href', '/api/attachments/f/download');
    const metas = [...document.querySelectorAll('.chat__fileMeta')].map((m) => m.textContent?.trim());
    expect(metas).toEqual(['PDF · 1 KB', 'PNG · 96 KB', '2 KB']);
  });

  it('shows pending, failed and edited states', async () => {
    const { retry, view } = await setup({
      messages: [
        msg('e1', today(9, 0), { editedAt: today(9, 5) }),
        msg('e2', today(9, 1), { editedAt: today(9, 5) }),
        msg('s', today(10), { own: true, state: 'sending' }),
        msg('f', today(10), { own: true, state: 'failed' }),
      ],
    });
    const metas = [...view.container.querySelectorAll('.chat__meta')].map((m) => m.textContent?.replace(/\s+/g, ' ').trim());
    expect(metas).toEqual(['bearbeitet', '09:01·bearbeitet', 'wird gesendet …', 'Nicht gesendet Erneut senden']);
    expect(view.container.querySelector('.chat__bubble--failed')).not.toBeNull();
    // A pending message offers no edit.
    expect(screen.queryAllByRole('button', { name: 'Nachricht bearbeiten' })).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Erneut senden' }));
    expect(retry).toHaveBeenCalledWith({ id: 'f' });
  });

  describe('composer', () => {
    it('sends on Enter, keeps Shift+Enter, and clears the draft', async () => {
      const { input, send, user } = await setup();
      await user.type(input(), 'Hallo');
      expect(localStorage.getItem('ap.chat.draft.t1')).toBe('Hallo');
      await user.keyboard('{Shift>}{Enter}{/Shift}');
      expect(send).not.toHaveBeenCalled();
      await user.keyboard('{Enter}');
      expect(send).toHaveBeenCalledWith({ body: 'Hallo' });
      expect(input().value).toBe('');
      expect(localStorage.getItem('ap.chat.draft.t1')).toBeNull();
    });

    it('sends with the button and ignores an empty text', async () => {
      const { input, send } = await setup();
      const button = screen.getByRole('button', { name: 'Senden' });
      fireEvent.input(input(), { target: { value: '   ' } });
      fireEvent.keyDown(input(), { key: 'Enter' });
      fireEvent.submit(button.closest('form') as HTMLFormElement);
      expect(send).not.toHaveBeenCalled();
      fireEvent.keyDown(input(), { key: 'a' });
      fireEvent.input(input(), { target: { value: ' Text ' } });
      fireEvent.submit(button.closest('form') as HTMLFormElement);
      expect(send).toHaveBeenCalledWith({ body: 'Text' });
    });

    it('sends the chosen visibility and keeps it for the next message', async () => {
      const { input, send, user, cmp } = await setup({ visibilityOptions: ['public', 'internal'] });
      const group = screen.getByRole('radiogroup', { name: 'Sichtbarkeit' });
      await user.click(within(group).getByRole('radio', { name: 'Intern' }));
      fireEvent.input(input(), { target: { value: 'Geheim' } });
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenCalledWith({ body: 'Geheim', visibility: 'internal' });
      expect(within(group).getByRole('radio', { name: 'Intern' })).toHaveAttribute('aria-checked', 'true');
      cmp.setVisibility('other');
      expect(cmp.visibility()).toBeNull();
    });

    it('sends the only visibility without a toggle', async () => {
      const { input, send } = await setup({ visibilityOptions: ['internal'] });
      expect(screen.queryByRole('radiogroup')).toBeNull();
      fireEvent.input(input(), { target: { value: 'Notiz' } });
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenCalledWith({ body: 'Notiz', visibility: 'internal' });
    });

    it('makes a new line on Enter on a phone', async () => {
      const { input, send, view } = await setup({ phone: true });
      expect(view.container).toBeTruthy();
      fireEvent.input(input(), { target: { value: 'Zeile' } });
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).not.toHaveBeenCalled();
    });

    it('keeps the draft per thread', async () => {
      localStorage.setItem('ap.chat.draft.t1', 'Entwurf 1');
      localStorage.setItem('ap.chat.draft.t2', 'Entwurf 2');
      const { input, set } = await setup();
      expect(input().value).toBe('Entwurf 1');
      set('draftKey', 't2');
      expect(input().value).toBe('Entwurf 2');
    });

    it('works without browser storage', async () => {
      jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      const { input, send } = await setup({ messages: [msg('a', today(9))] });
      fireEvent.input(input(), { target: { value: 'x' } });
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenCalledWith({ body: 'x' });
    });

    it('has no composer without the right to post', async () => {
      await setup({ canPost: false });
      expect(screen.queryByRole('textbox')).toBeNull();
    });
  });

  describe('own messages on a desktop', () => {
    const own = () => [msg('m', today(9), { own: true, body: 'Alt' }), msg('n', today(9, 1), { own: true })];

    it('edits inline: Enter saves, Escape cancels, an unchanged text emits nothing', async () => {
      const { edit } = await setup({ messages: own() });
      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[0]);
      const box = () => screen.getByRole('textbox', { name: 'Nachricht bearbeiten' }) as HTMLTextAreaElement;
      expect(box().value).toBe('Alt');
      fireEvent.keyDown(box(), { key: 'Enter' });
      expect(edit).not.toHaveBeenCalled();

      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[0]);
      fireEvent.keyDown(box(), { key: 'Escape' });
      expect(screen.queryByRole('textbox', { name: 'Nachricht bearbeiten' })).toBeNull();

      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[0]);
      fireEvent.input(box(), { target: { value: 'Neu' } });
      fireEvent.keyDown(box(), { key: 'Enter', shiftKey: true });
      fireEvent.keyDown(box(), { key: 'a' });
      expect(edit).not.toHaveBeenCalled();
      fireEvent.keyDown(box(), { key: 'Enter' });
      expect(edit).toHaveBeenCalledWith({ id: 'm', body: 'Neu' });
    });

    it('saves with the button, cancels with Abbrechen and needs a text', async () => {
      const { edit, cmp } = await setup({ messages: own() });
      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[1]);
      const box = screen.getByRole('textbox', { name: 'Nachricht bearbeiten' });
      fireEvent.input(box, { target: { value: ' ' } });
      fireEvent.submit(box.closest('form') as HTMLFormElement);
      expect(edit).not.toHaveBeenCalled();
      fireEvent.input(box, { target: { value: 'Geändert' } });
      fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      expect(edit).toHaveBeenCalledWith({ id: 'n', body: 'Geändert' });

      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[1]);
      fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
      expect(screen.queryByRole('textbox', { name: 'Nachricht bearbeiten' })).toBeNull();
      // Nothing is being edited: a save does nothing; a vanished message emits nothing.
      cmp.saveEdit();
      cmp.editingId.set('gone');
      cmp.editDraft.set('x');
      cmp.saveEdit();
      expect(edit).toHaveBeenCalledTimes(1);
    });

    it('deletes after a confirmation', async () => {
      const { del, view } = await setup({ messages: own() });
      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht löschen' })[0]);
      const dialog = screen.getByRole('dialog', { name: 'Nachricht löschen' });
      fireEvent.click(within(dialog).getAllByRole('button', { name: 'Abbrechen' })[1]);
      expect(del).not.toHaveBeenCalled();
      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht löschen' })[0]);
      fireEvent.click(within(screen.getByRole('dialog', { name: 'Nachricht löschen' })).getByRole('button', { name: 'Löschen' }));
      expect(del).toHaveBeenCalledWith({ id: 'm' });
      // A confirm without a message does nothing.
      (view.fixture.componentInstance as unknown as { confirmDelete(): void }).confirmDelete();
      expect(del).toHaveBeenCalledTimes(1);
    });
  });

  describe('actions in a narrow window with a mouse', () => {
    it('keeps the hover and focus actions when the width is a phone but the pointer is fine', async () => {
      const { edit, view } = await setup({ fine: true, messages: [msg('m', today(8, 21), { own: true, body: 'Prüfe ich' })] });
      expect(view.fixture.nativeElement).toHaveClass('chat--phone');
      fireEvent.click(screen.getByRole('button', { name: 'Nachricht bearbeiten' }));
      const box = screen.getByRole('textbox', { name: 'Nachricht bearbeiten' });
      fireEvent.input(box, { target: { value: 'Neu' } });
      fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      expect(edit).toHaveBeenCalledWith({ id: 'm', body: 'Neu' });
      expect(screen.getByRole('button', { name: 'Nachricht löschen' })).toBeInTheDocument();
    });
  });

  describe('messages the viewer may moderate', () => {
    it('offers edit and delete on a message of another person with canEdit, and not without', async () => {
      const { del } = await setup({
        messages: [
          msg('a', today(8, 20), { own: false, canEdit: true, body: 'Fremd' }),
          msg('b', today(9, 20), { own: false, body: 'Auch fremd' }),
          msg('c', today(10, 20), { own: true, canEdit: false, body: 'Gesperrt' }),
        ],
      });
      expect(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })).toHaveLength(1);
      fireEvent.click(screen.getByRole('button', { name: 'Nachricht löschen' }));
      fireEvent.click(within(screen.getByRole('dialog', { name: 'Nachricht löschen' })).getByRole('button', { name: 'Löschen' }));
      expect(del).toHaveBeenCalledWith({ id: 'a' });
    });
  });

  describe('own messages on a phone', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    async function longPress() {
      const ctx = await setup({ phone: true, messages: [msg('m', today(8, 21), { own: true, body: 'Prüfe ich' })] });
      expect(screen.queryByRole('button', { name: 'Nachricht bearbeiten' })).toBeNull();
      const bubble = ctx.view.container.querySelector('.chat__bubble') as HTMLElement;
      fireEvent.pointerDown(bubble);
      jest.advanceTimersByTime(500);
      ctx.view.fixture.detectChanges();
      return ctx;
    }

    it('opens the sheet on a long press and copies the text', async () => {
      const { view } = await longPress();
      // After the setup: user-event puts its own clipboard on the navigator.
      const writeText = jest.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
      const sheet = screen.getByRole('dialog', { name: 'Deine Nachricht · 08:21' });
      fireEvent.click(within(sheet).getByRole('button', { name: 'Text kopieren' }));
      expect(writeText).toHaveBeenCalledWith('Prüfe ich');
      view.fixture.detectChanges();
      expect(screen.queryByRole('dialog', { name: 'Deine Nachricht · 08:21' })).toBeNull();
    });

    it('copies nothing without a clipboard and survives a refused copy', async () => {
      const { cmp } = await longPress();
      Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
      cmp.copy(msg('m', today(9), { own: true }));
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: jest.fn().mockRejectedValue(new Error('denied')) },
        configurable: true,
      });
      cmp.copy(msg('m', today(9), { own: true }));
      await Promise.resolve();
      expect(cmp.menuFor()).toBeNull();
    });

    it('edits and deletes from the sheet', async () => {
      const { view, cmp } = await longPress();
      fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Bearbeiten' }));
      view.fixture.detectChanges();
      expect(screen.getByRole('textbox', { name: 'Nachricht bearbeiten' })).toHaveValue('Prüfe ich');
      // Enter is a new line on a phone.
      fireEvent.keyDown(screen.getByRole('textbox', { name: 'Nachricht bearbeiten' }), { key: 'Enter' });
      expect(screen.getByRole('textbox', { name: 'Nachricht bearbeiten' })).toBeInTheDocument();
      cmp.cancelEdit();
      view.fixture.detectChanges();

      cmp.openMenu(cmp.messages()[0]);
      view.fixture.detectChanges();
      fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Löschen' }));
      view.fixture.detectChanges();
      expect(screen.getByRole('dialog', { name: 'Nachricht löschen' })).toBeInTheDocument();
    });

    it('closes the sheet with its close button', async () => {
      const { view, cmp } = await longPress();
      fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Schließen' }));
      view.fixture.detectChanges();
      expect(cmp.menuFor()).toBeNull();
      cmp.onMenuOpen(true);
      expect(cmp.menuFor()).toBeNull();
    });
  });

  describe('scrolling and new messages', () => {
    /** Give the log a size: 1000px of content in a 200px window, scrolled to `top`. */
    function size(el: HTMLElement, top: number): void {
      Object.defineProperty(el, 'scrollHeight', { value: 1000, configurable: true });
      Object.defineProperty(el, 'clientHeight', { value: 200, configurable: true });
      el.scrollTop = top;
    }

    it('opens at the newest message and remembers it', async () => {
      const { log } = await setup({ messages: [msg('a', today(9)), msg('b', today(10))] });
      expect(localStorage.getItem('ap.chat.seen.t1')).toBe(today(10));
      expect(log()).toBeInTheDocument();
    });

    it('shows "N neue" where the viewer was last', async () => {
      localStorage.setItem('ap.chat.seen.t1', today(9));
      const { view } = await setup({ messages: [msg('a', today(9)), msg('b', today(10)), msg('c', today(10, 1))] });
      const sep = view.container.querySelector('.chat__sep--new');
      expect(sep).toHaveTextContent('2 neue');
    });

    it('offers a button for new messages below and follows at the end', async () => {
      const { log, set, view } = await setup({ messages: [msg('a', today(9))] });
      size(log(), 0);
      fireEvent.scroll(log());
      view.fixture.detectChanges();
      set('messages', [msg('a', today(9)), msg('b', today(10))]);
      expect(screen.getByRole('button', { name: /1 neue Nachricht$/ })).toBeInTheDocument();
      set('messages', [msg('a', today(9)), msg('b', today(10)), msg('c', today(11))]);
      const pill = screen.getByRole('button', { name: /2 neue Nachrichten/ });
      fireEvent.click(pill);
      view.fixture.detectChanges();
      expect(log().scrollTop).toBe(1000);
      expect(screen.queryByRole('button', { name: /neue Nachricht/ })).toBeNull();
      expect(localStorage.getItem('ap.chat.seen.t1')).toBe(today(11));

      // Back at the end by scrolling: the log follows again.
      size(log(), 0);
      fireEvent.scroll(log());
      size(log(), 800);
      fireEvent.scroll(log());
      view.fixture.detectChanges();
      set('messages', [msg('a', today(9)), msg('b', today(10)), msg('c', today(11)), msg('d', today(12))]);
      expect(screen.queryByRole('button', { name: /neue Nachricht/ })).toBeNull();
    });

    it('follows when the log changes its size', async () => {
      const observers: ResizeObserverCallback[] = [];
      const Real = globalThis.ResizeObserver;
      globalThis.ResizeObserver = class {
        constructor(cb: ResizeObserverCallback) {
          observers.push(cb);
        }
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      } as unknown as typeof ResizeObserver;
      try {
        const { log, view } = await setup({ messages: [msg('a', today(9))] });
        size(log(), 0);
        observers.forEach((cb) => cb([], {} as ResizeObserver));
        expect(log().scrollTop).toBe(1000);
        view.fixture.destroy();
      } finally {
        globalThis.ResizeObserver = Real;
      }
    });

    it('scrolls to the end after an own send', async () => {
      const { log, input } = await setup({ messages: [msg('a', today(9))] });
      size(log(), 0);
      fireEvent.scroll(log());
      fireEvent.input(input(), { target: { value: 'x' } });
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(log().scrollTop).toBe(1000);
    });
  });
});
