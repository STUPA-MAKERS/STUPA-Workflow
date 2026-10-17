import { HttpErrorResponse } from '@angular/common/http';
import { Component, signal } from '@angular/core';
import { By } from '@angular/platform-browser';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { DraftUpload } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { AltchaService } from '../../../features/apply/altcha.service';
import { ChatDrafts } from './chat-drafts';
import { ChatComponent, SCAN_BACKOFF, chatUploadError } from './chat.component';
import type { ChatEvent, ChatMessage, ChatVisibility } from './chat.models';
import type { ChatPerson } from './chat-mentions';

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
  canAttach?: boolean;
  loading?: boolean;
  mentionables?: ChatPerson[];
  publicMentions?: boolean;
  /** The answer of an upload; default: a draft with the file's name. */
  upload?: (file: File, opts: { token?: string | null }) => Observable<DraftUpload>;
}

function draftOf(file: File, n: number): DraftUpload {
  return {
    attachment: {
      id: `d${n}`,
      filename: file.name,
      mime: file.type,
      size: file.size,
      scanned: false,
      isComparisonOffer: false,
      scanState: 'scanning',
    },
    draftToken: 'tok',
    draftExpiresAt: '2999-01-01T00:00:00Z',
  };
}

async function setup(opts: SetupOpts = {}) {
  mockPhone(!!opts.phone || !!opts.fine, !!opts.phone);
  const send = jest.fn();
  const edit = jest.fn();
  const del = jest.fn();
  const retry = jest.fn();
  const discard = jest.fn();
  const refresh = jest.fn();
  let n = 0;
  const api = {
    uploadDraftAttachment: jest.fn((file: File, o: { token?: string | null }) =>
      opts.upload ? opts.upload(file, o) : of(draftOf(file, ++n)),
    ),
    deleteDraftAttachment: jest.fn((): Observable<void> => of(undefined)),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(ChatComponent, {
    inputs: {
      messages: opts.messages ?? [],
      events: opts.events ?? [],
      canPost: opts.canPost ?? true,
      visibilityOptions: opts.visibilityOptions ?? [],
      draftKey: opts.draftKey ?? 't1',
      canAttach: opts.canAttach ?? false,
      loading: opts.loading ?? false,
      mentionables: opts.mentionables ?? [],
      publicMentions: opts.publicMentions ?? true,
    },
    on: { send, edit, delete: del, retry, discard, refresh },
    providers: [
      { provide: ApiClient, useValue: api },
      { provide: AuthService, useValue: { isAuthenticated: signal(true) } },
      { provide: AltchaService, useValue: { solve: jest.fn(async () => 'sol') } },
      { provide: ToastService, useValue: toast },
    ],
  });
  const set = (name: string, value: unknown) => {
    view.fixture.componentRef.setInput(name, value);
    view.fixture.detectChanges();
  };
  const log = () => screen.getByRole('log');
  const input = () => screen.getByRole('textbox', { name: 'Nachricht schreiben …' }) as HTMLTextAreaElement;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  /** Pick files with the hidden input and let the uploads finish. */
  const pick = async (...files: File[]) => {
    const box = view.container.querySelector('.chat__fileInput') as HTMLInputElement;
    Object.defineProperty(box, 'files', { value: files, configurable: true });
    fireEvent.change(box);
    await settle();
  };
  const settle = async () => {
    await new Promise((r) => setTimeout(r));
    view.fixture.detectChanges();
  };
  return { view, send, edit, del, retry, discard, refresh, set, log, input, cmp, api, toast, pick, settle, user: userEvent.setup() };
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

  it('draws bubbles, not "no messages", while the thread is on its way', async () => {
    const { log } = await setup({ loading: true });
    expect(within(log()).queryByText('Noch keine Nachrichten.')).toBeNull();
    expect(log().querySelector('app-skeleton')).not.toBeNull();
    expect(log().querySelectorAll('.sk__msg')).toHaveLength(5);
    expect(within(log()).getByRole('status')).toHaveTextContent('Nachrichten werden geladen');
    // The composer is there at once.
    expect(document.querySelector('textarea.chat__input')).not.toBeNull();
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
    expect(metas).toEqual(['bearbeitet', '09:01·bearbeitet', 'wird gesendet …', 'Nicht gesendet Erneut senden Bearbeiten Verwerfen']);
    expect(view.container.querySelector('.chat__bubble--failed')).not.toBeNull();
    // A pending message offers no edit.
    expect(screen.queryAllByRole('button', { name: 'Nachricht bearbeiten' })).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Erneut senden' }));
    expect(retry).toHaveBeenCalledWith({ id: 'f' });
  });

  it('discards a failed message, or puts its text back into the composer', async () => {
    const { discard, input, view } = await setup({
      messages: [msg('f', today(10), { own: true, state: 'failed', body: 'Zu lang' })],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    expect(discard).toHaveBeenCalledWith({ id: 'f' });
    discard.mockClear();
    fireEvent.input(input(), { target: { value: 'Neu' } });
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    expect(discard).toHaveBeenCalledWith({ id: 'f' });
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    expect(input().value).toBe('Zu lang\n\nNeu');
    expect(localStorage.getItem('ap.chat.draft.t1')).toBe('Zu lang\n\nNeu');
    expect(document.activeElement).toBe(input());
  });

  it('resends a failed message with its own visibility, not the one the composer shows', async () => {
    const { input, send, view, cmp } = await setup({
      visibilityOptions: ['public', 'internal'],
      messages: [msg('f', today(10), { own: true, state: 'failed', body: 'Kosten noch unklar', visibility: 'internal' })],
    });
    expect(cmp.visibility()).toBe('public');
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    view.fixture.detectChanges();
    expect(cmp.visibility()).toBe('internal');
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(send).toHaveBeenCalledWith({ body: 'Kosten noch unklar', visibility: 'internal' });
  });

  it('keeps the composer visibility for a failed message of a kind it does not offer', async () => {
    const { view, cmp } = await setup({
      visibilityOptions: ['internal'],
      messages: [msg('f', today(10), { own: true, state: 'failed', body: 'x', visibility: 'public' })],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    view.fixture.detectChanges();
    expect(cmp.visibility()).toBe('internal');
  });

  it('keeps the focus in the thread after "Erneut senden" or "Verwerfen"', async () => {
    const { retry, discard, input, log, view, set } = await setup({
      messages: [msg('f', today(10), { own: true, state: 'failed' })],
    });
    const settle = async () => {
      view.fixture.detectChanges();
      await view.fixture.whenStable();
    };
    screen.getByRole('button', { name: 'Erneut senden' }).focus();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut senden' }));
    set('messages', [msg('f', today(10), { own: true, state: 'sending' })]);
    await settle();
    expect(retry).toHaveBeenCalledWith({ id: 'f' });
    expect(document.activeElement).toBe(input());

    set('messages', [msg('f', today(10), { own: true, state: 'failed' })]);
    set('canPost', false);
    screen.getByRole('button', { name: 'Verwerfen' }).focus();
    fireEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    set('messages', []);
    await settle();
    expect(discard).toHaveBeenCalledWith({ id: 'f' });
    expect(document.activeElement).toBe(log());
  });

  it('puts the text of a failed message into an empty composer as it is', async () => {
    const { input, view } = await setup({
      messages: [msg('f', today(10), { own: true, state: 'failed', body: 'Hallo' })],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    view.fixture.detectChanges();
    expect(input().value).toBe('Hallo');
  });

  it('caps the composer and the edit at the length the server takes', async () => {
    const { input, cmp, view } = await setup({ messages: [msg('o', today(10), { own: true })] });
    expect(input().getAttribute('maxlength')).toBe('10000');
    cmp.startEdit(cmp.messages()[0]);
    view.fixture.detectChanges();
    expect(view.container.querySelector('.chat__editInput')?.getAttribute('maxlength')).toBe('10000');
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

    it('starts each thread on the default visibility', async () => {
      const { user, set } = await setup({ visibilityOptions: ['public', 'internal'] });
      const group = () => screen.getByRole('radiogroup', { name: 'Sichtbarkeit' });
      await user.click(within(group()).getByRole('radio', { name: 'Intern' }));
      expect(within(group()).getByRole('radio', { name: 'Intern' })).toHaveAttribute('aria-checked', 'true');
      set('draftKey', 't2');
      expect(within(group()).getByRole('radio', { name: 'Öffentlich' })).toHaveAttribute('aria-checked', 'true');
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

  describe('mentions', () => {
    const people: ChatPerson[] = [
      { principalId: 'p-1', displayName: 'Jonas Weber' },
      { principalId: 'p-2', displayName: 'Selin Yıldız' },
    ];
    const type = (box: HTMLTextAreaElement, value: string) =>
      fireEvent.input(box, { target: { value, selectionStart: value.length } });
    const list = () => screen.queryByRole('listbox', { name: 'Personen erwähnen' });

    it('lists the people after "@" and takes one with the keys, then sends the ids', async () => {
      const { input, send, view } = await setup({ mentionables: people });
      type(input(), 'Hallo @');
      view.fixture.detectChanges();
      expect(within(list()!).getAllByRole('option')).toHaveLength(2);
      expect(input()).toHaveAttribute('aria-controls', list()!.id);
      expect(input().getAttribute('aria-activedescendant')).toBe(
        within(list()!).getAllByRole('option')[0].id,
      );
      fireEvent.keyDown(input(), { key: 'ArrowDown' });
      fireEvent.keyUp(input(), { key: 'ArrowDown' });
      view.fixture.detectChanges();
      expect(within(list()!).getByRole('option', { name: 'Selin Yıldız' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      fireEvent.keyDown(input(), { key: 'Tab' });
      fireEvent.keyUp(input(), { key: 'Tab' });
      view.fixture.detectChanges();
      expect(input().value).toBe('Hallo @Selin Yıldız ');
      expect(list()).toBeNull();
      expect(input()).not.toHaveAttribute('aria-controls');
      expect(document.activeElement).toBe(input());
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenCalledWith({ body: 'Hallo @Selin Yıldız', mentions: ['p-2'] });
    });

    it('takes a person with a click, follows the pointer and keeps the focus in the text', async () => {
      const { input, view } = await setup({ mentionables: people });
      input().focus();
      type(input(), '@jo');
      view.fixture.detectChanges();
      const option = within(list()!).getByRole('option', { name: 'Jonas Weber' });
      fireEvent.mouseEnter(option);
      view.fixture.detectChanges();
      expect(option).toHaveAttribute('aria-selected', 'true');
      expect(fireEvent.mouseDown(option)).toBe(false);
      fireEvent.click(option);
      view.fixture.detectChanges();
      expect(input().value).toBe('@Jonas Weber ');
      expect(input().selectionStart).toBe(13);
    });

    it('closes on Escape and on blur, and sends no mentions without a name', async () => {
      const { input, send, view } = await setup({ mentionables: people });
      type(input(), '@se');
      view.fixture.detectChanges();
      fireEvent.keyDown(input(), { key: 'Escape' });
      view.fixture.detectChanges();
      expect(list()).toBeNull();
      fireEvent.click(input());
      view.fixture.detectChanges();
      expect(list()).toBeNull();
      type(input(), '@se @jo');
      view.fixture.detectChanges();
      expect(list()).not.toBeNull();
      fireEvent.blur(input());
      view.fixture.detectChanges();
      expect(list()).toBeNull();
      type(input(), 'Ohne Namen');
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenCalledWith({ body: 'Ohne Namen' });
    });

    it('offers no list without people', async () => {
      const { input, view } = await setup();
      type(input(), '@jo');
      view.fixture.detectChanges();
      expect(list()).toBeNull();
    });

    it('marks the mentioned people in a message', async () => {
      await setup({
        messages: [
          msg('a', today(9), {
            body: 'Hallo @Selin Yıldız, schau mal',
            mentions: [
              { principalId: 'p-2', displayName: 'Selin Yıldız' },
              { principalId: null, displayName: null },
            ],
          }),
        ],
      });
      expect(document.querySelector('.chat__mention')).toHaveTextContent('@Selin Yıldız');
    });

    it('lists the people in an edit and sends the new mentions; without people the mentions stay', async () => {
      const own = [msg('m', today(9), { own: true, body: 'Alt' })];
      const { edit, view, set } = await setup({ messages: own, mentionables: people });
      fireEvent.click(screen.getByRole('button', { name: 'Nachricht bearbeiten' }));
      const box = () =>
        screen.getByRole('textbox', { name: 'Nachricht bearbeiten' }) as HTMLTextAreaElement;
      type(box(), 'Alt @jo');
      view.fixture.detectChanges();
      expect(list()).toHaveClass('chat__mentions--below');
      fireEvent.keyDown(box(), { key: 'Enter' });
      view.fixture.detectChanges();
      expect(box().value).toBe('Alt @Jonas Weber ');
      fireEvent.keyDown(box(), { key: 'Escape' });
      expect(screen.queryByRole('textbox', { name: 'Nachricht bearbeiten' })).toBeNull();

      fireEvent.click(screen.getByRole('button', { name: 'Nachricht bearbeiten' }));
      type(box(), 'Alt @Jonas Weber!');
      fireEvent.keyDown(box(), { key: 'Enter' });
      expect(edit).toHaveBeenLastCalledWith({
        id: 'm',
        body: 'Alt @Jonas Weber!',
        mentions: ['p-1'],
        restore: expect.any(Function),
      });

      set('mentionables', []);
      fireEvent.click(screen.getByRole('button', { name: 'Nachricht bearbeiten' }));
      type(box(), 'Neu');
      fireEvent.click(box());
      fireEvent.keyUp(box(), { key: 'a' });
      fireEvent.blur(box());
      fireEvent.keyDown(box(), { key: 'Enter' });
      expect(edit).toHaveBeenLastCalledWith({
        id: 'm',
        body: 'Neu',
        restore: expect.any(Function),
      });
    });

    it('mentions only in an internal message where the other side reads the public ones', async () => {
      const own = [
        msg('pub', today(9), { own: true, body: 'Alt', visibility: 'public' }),
        msg('int', today(9, 1), { own: true, body: 'Intern', visibility: 'internal' }),
      ];
      const { cmp, input, send, edit, view } = await setup({
        messages: own,
        mentionables: people,
        publicMentions: false,
        visibilityOptions: ['public', 'internal'],
      });
      type(input(), '@jo');
      view.fixture.detectChanges();
      expect(list()).toBeNull();
      cmp.setVisibility('internal');
      type(input(), '@jo');
      view.fixture.detectChanges();
      expect(list()).not.toBeNull();
      // The switch back to public closes the open list.
      cmp.setVisibility('public');
      view.fixture.detectChanges();
      expect(list()).toBeNull();
      type(input(), '@Jonas Weber');
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenLastCalledWith({ body: '@Jonas Weber', visibility: 'public' });

      const editButton = (i: number) =>
        screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[i];
      const box = () =>
        screen.getByRole('textbox', { name: 'Nachricht bearbeiten' }) as HTMLTextAreaElement;
      fireEvent.click(editButton(0));
      type(box(), 'Alt @jo');
      view.fixture.detectChanges();
      expect(list()).toBeNull();
      fireEvent.keyDown(box(), { key: 'Enter' });
      expect(edit).toHaveBeenLastCalledWith({
        id: 'pub',
        body: 'Alt @jo',
        restore: expect.any(Function),
      });
      view.fixture.detectChanges();
      fireEvent.click(editButton(1));
      type(box(), 'Intern @Jonas Weber!');
      fireEvent.keyDown(box(), { key: 'Enter' });
      expect(edit).toHaveBeenLastCalledWith({
        id: 'int',
        body: 'Intern @Jonas Weber!',
        mentions: ['p-1'],
        restore: expect.any(Function),
      });
    });

    it('keeps the chosen person where two people have the same name', async () => {
      const twins: ChatPerson[] = [
        { principalId: 'k-1', displayName: 'Kim' },
        { principalId: 'k-2', displayName: 'Kim' },
      ];
      const own = [
        msg('m', today(9), {
          own: true,
          body: '@Kim',
          mentions: [{ principalId: 'k-2', displayName: 'Kim' }],
        }),
      ];
      const { input, send, edit, view } = await setup({ messages: own, mentionables: twins });
      type(input(), '@ki');
      view.fixture.detectChanges();
      fireEvent.keyDown(input(), { key: 'ArrowDown' });
      fireEvent.keyDown(input(), { key: 'Enter' });
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenLastCalledWith({ body: '@Kim', mentions: ['k-2'] });
      // The next message starts without the earlier choice.
      type(input(), '@Kim ');
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenLastCalledWith({ body: '@Kim', mentions: ['k-1'] });
      // An edit keeps the person that the message mentions.
      fireEvent.click(screen.getByRole('button', { name: 'Nachricht bearbeiten' }));
      const box = screen.getByRole('textbox', { name: 'Nachricht bearbeiten' });
      type(box as HTMLTextAreaElement, '@Kim, bitte');
      fireEvent.keyDown(box, { key: 'Enter' });
      expect(edit).toHaveBeenLastCalledWith({
        id: 'm',
        body: '@Kim, bitte',
        mentions: ['k-2'],
        restore: expect.any(Function),
      });
    });

    it('does nothing when the text box of a pick is gone', async () => {
      const { cmp } = await setup({ mentionables: people });
      cmp.editMentions.update('@jo', 3);
      cmp.pickMention(cmp.editMentions, people[0]);
      expect(cmp.editMentions.open()).toBe(true);
      cmp.composerMentions.close();
      const box = screen.getByRole('textbox', {
        name: 'Nachricht schreiben …',
      }) as HTMLTextAreaElement;
      box.value = 'x';
      cmp.pickMention(cmp.composerMentions, people[0]);
      expect(box.value).toBe('x');
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
      expect(edit).toHaveBeenCalledWith({ id: 'm', body: 'Neu', restore: expect.any(Function) });
    });

    it('moves the focus into the edit field and back to the Edit button', async () => {
      const { view } = await setup({ messages: own() });
      const settle = async () => {
        view.fixture.detectChanges();
        await view.fixture.whenStable();
      };
      const editOf = (i: number) => screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[i];
      const box = () => screen.getByRole('textbox', { name: 'Nachricht bearbeiten' }) as HTMLTextAreaElement;
      editOf(1).focus();
      fireEvent.click(editOf(1));
      await settle();
      expect(box()).toHaveFocus();
      expect(box().selectionStart).toBe(box().value.length);
      expect(box().value.length).toBeGreaterThan(0);
      fireEvent.keyDown(box(), { key: 'Escape' });
      await settle();
      expect(editOf(1)).toHaveFocus();

      fireEvent.click(editOf(0));
      await settle();
      fireEvent.input(box(), { target: { value: 'Neu' } });
      fireEvent.keyDown(box(), { key: 'Enter' });
      await settle();
      expect(editOf(0)).toHaveFocus();

      // An edit closed while the focus is elsewhere leaves the focus there.
      fireEvent.click(editOf(0));
      await settle();
      const outside = screen.getByRole('textbox', { name: 'Nachricht schreiben …' });
      outside.focus();
      fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
      await settle();
      expect(outside).toHaveFocus();
    });

    it('opens a refused edit again with the new text, not over another edit or a gone message', async () => {
      const { edit, view, set } = await setup({ messages: own() });
      const settle = async () => {
        view.fixture.detectChanges();
        await view.fixture.whenStable();
      };
      const box = () => screen.queryByRole('textbox', { name: 'Nachricht bearbeiten' }) as HTMLTextAreaElement | null;
      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[0]);
      fireEvent.input(box() as HTMLTextAreaElement, { target: { value: 'Lange neue Fassung' } });
      fireEvent.keyDown(box() as HTMLTextAreaElement, { key: 'Enter' });
      await settle();
      expect(box()).toBeNull();
      const first = edit.mock.calls[0][0] as { restore: () => void };
      first.restore();
      await settle();
      expect(box()?.value).toBe('Lange neue Fassung');
      expect(box()).toHaveFocus();

      // Another edit is open: the refused one waits.
      fireEvent.keyDown(box() as HTMLTextAreaElement, { key: 'Escape' });
      fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[1]);
      await settle();
      first.restore();
      await settle();
      expect(box()?.value).not.toBe('Lange neue Fassung');

      // The message is gone: nothing opens.
      fireEvent.keyDown(box() as HTMLTextAreaElement, { key: 'Escape' });
      set('messages', [own()[1]]);
      first.restore();
      await settle();
      expect(box()).toBeNull();
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
      expect(edit).toHaveBeenCalledWith({ id: 'n', body: 'Geändert', restore: expect.any(Function) });

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

    it('keeps the focus in the thread when the deleted message leaves the list', async () => {
      const { set, input, view } = await setup({ messages: own() });
      const trash = screen.getAllByRole('button', { name: 'Nachricht löschen' })[0];
      trash.focus();
      fireEvent.click(trash);
      view.fixture.detectChanges();
      fireEvent.click(within(screen.getByRole('dialog', { name: 'Nachricht löschen' })).getByRole('button', { name: 'Löschen' }));
      view.fixture.detectChanges();
      // The answer is still out: the message and its button stay.
      set('messages', own());
      set('messages', own().filter((m) => m.id !== 'm'));
      await view.fixture.whenStable();
      expect(document.activeElement).toBe(input());
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
      expect(edit).toHaveBeenCalledWith({ id: 'm', body: 'Neu', restore: expect.any(Function) });
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
      expect(screen.getByRole('textbox', { name: 'Nachricht bearbeiten' })).toHaveFocus();
      cmp.cancelEdit();
      view.fixture.detectChanges();
      // A phone has no Edit button: the focus goes to the log.
      expect(screen.getByRole('log')).toHaveFocus();

      cmp.openMenu(cmp.messages()[0]);
      view.fixture.detectChanges();
      fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Löschen' }));
      view.fixture.detectChanges();
      expect(screen.getByRole('dialog', { name: 'Nachricht löschen' })).toBeInTheDocument();
    });

    it('offers no copy for a message of files only', async () => {
      const { view, cmp } = await setup({
        phone: true,
        messages: [msg('m', today(8, 21), { own: true, body: '  ' })],
      });
      cmp.openMenu(cmp.messages()[0]);
      view.fixture.detectChanges();
      const sheet = screen.getByRole('dialog');
      expect(within(sheet).queryByRole('button', { name: 'Text kopieren' })).not.toBeInTheDocument();
      expect(within(sheet).getByRole('button', { name: 'Bearbeiten' })).toBeInTheDocument();
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
      // A separator role would make the text presentational: the day and the marker reach AT as text.
      expect(screen.queryAllByRole('separator')).toHaveLength(0);
      expect(sep).not.toHaveAttribute('role');
      expect(screen.getByText('Heute').closest('[role]')).toBe(screen.getByRole('log'));
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

  describe('files', () => {
    const pdf = (name = 'angebot.pdf', size = 4) => {
      const f = new File(['%PDF'], name, { type: 'application/pdf' });
      if (size !== 4) Object.defineProperty(f, 'size', { value: size });
      return f;
    };

    it('shows the paperclip only where the thread takes files', async () => {
      await setup();
      expect(screen.queryByRole('button', { name: 'Datei anhängen' })).not.toBeInTheDocument();
      expect(document.querySelector('.chat__fileInput')).toBeNull();
    });

    it('uploads picked files as chips and sends them with the message', async () => {
      const { pick, api, send, input, view, cmp } = await setup({ canAttach: true });
      const clip = screen.getByRole('button', { name: 'Datei anhängen' });
      const click = jest.spyOn(view.container.querySelector('.chat__fileInput') as HTMLInputElement, 'click');
      fireEvent.click(clip);
      expect(click).toHaveBeenCalled();
      await pick(pdf(), pdf('kopf.png'));
      expect(api.uploadDraftAttachment.mock.calls[0][1]).toMatchObject({ token: null, altcha: null });
      expect(api.uploadDraftAttachment.mock.calls[1][1]).toMatchObject({ token: 'tok' });
      const chips = [...view.container.querySelectorAll('.chat__draft')].map((c) => c.textContent?.replace(/\s+/g, ' ').trim());
      expect(chips).toEqual(['angebot.pdf PDF · 1 KB · In Prüfung', 'kopf.png PNG · 1 KB · In Prüfung']);
      // The input is emptied, so the same file can be picked again.
      expect((view.container.querySelector('.chat__fileInput') as HTMLInputElement).value).toBe('');

      // A message of files only goes out with an empty text.
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send).toHaveBeenCalledWith({
        body: '',
        attachmentIds: ['d1', 'd2'],
        draftToken: 'tok',
        files: [
          { id: 'd1', filename: 'angebot.pdf', mime: 'application/pdf', size: 4, scanState: 'scanning', url: '/api/attachments/d1/download' },
          { id: 'd2', filename: 'kopf.png', mime: 'application/pdf', size: 4, scanState: 'scanning', url: '/api/attachments/d2/download' },
        ],
      });
      view.fixture.detectChanges();
      expect(view.container.querySelectorAll('.chat__draft')).toHaveLength(0);
      // The next message starts a new draft.
      await pick(pdf());
      expect(api.uploadDraftAttachment.mock.calls[2][1]).toMatchObject({ token: null });
      expect(cmp.files()).toHaveLength(1);
    });

    it('sends text and files with the visibility', async () => {
      const { pick, send, input } = await setup({ canAttach: true, visibilityOptions: ['public', 'internal'] });
      await pick(pdf());
      fireEvent.input(input(), { target: { value: 'Siehe Anhang' } });
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send.mock.calls[0][0]).toMatchObject({ body: 'Siehe Anhang', visibility: 'public', attachmentIds: ['d1'] });
    });

    it('shows the upload, and sends nothing while it runs', async () => {
      const answer = new Subject<DraftUpload>();
      const { pick, send, input, view, settle } = await setup({ canAttach: true, upload: () => answer });
      await pick(pdf());
      const chip = view.container.querySelector('.chat__draft--pending') as HTMLElement;
      expect(chip).toHaveTextContent('angebot.pdf');
      expect(chip).toHaveTextContent('wird hochgeladen …');
      expect(screen.getByRole('button', { name: 'Senden' })).toBeDisabled();
      fireEvent.input(input(), { target: { value: 'Text' } });
      fireEvent.submit(input().closest('form') as HTMLFormElement);
      expect(send).not.toHaveBeenCalled();
      answer.next(draftOf(pdf(), 1));
      answer.complete();
      await settle();
      expect(view.container.querySelector('.chat__draft--pending')).toBeNull();
      expect(screen.getByRole('button', { name: 'Senden' })).not.toBeDisabled();
    });

    it('removes a chip before the send, and says when the server refuses', async () => {
      const { pick, api, toast, view, settle, cmp } = await setup({ canAttach: true });
      await pick(pdf(), pdf('b.pdf'));
      fireEvent.click(screen.getByRole('button', { name: 'angebot.pdf entfernen' }));
      await settle();
      expect(api.deleteDraftAttachment).toHaveBeenCalledWith('d1', 'tok');
      expect(view.container.querySelectorAll('.chat__draft')).toHaveLength(1);
      api.deleteDraftAttachment.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
      await cmp.removeFile(cmp.files()[0]);
      await settle();
      expect(toast.error).toHaveBeenCalledWith('Die Datei konnte nicht entfernt werden.');
      expect(view.container.querySelectorAll('.chat__draft')).toHaveLength(1);
    });

    it('takes at most 5 files per message and disables the paperclip when full', async () => {
      const { pick, api, toast, cmp } = await setup({ canAttach: true });
      await pick(...Array.from({ length: 6 }, (_, i) => pdf(`f${i}.pdf`)));
      expect(toast.error).toHaveBeenCalledWith('Höchstens 5 Dateien pro Nachricht.');
      expect(api.uploadDraftAttachment).toHaveBeenCalledTimes(5);
      expect(cmp.files()).toHaveLength(5);
      expect(screen.getByRole('button', { name: 'Datei anhängen' })).toBeDisabled();
      await pick(pdf());
      expect(api.uploadDraftAttachment).toHaveBeenCalledTimes(5);
    });

    it('moves the focus from the paperclip to the text box when a pick fills the message', async () => {
      const { pick, input } = await setup({ canAttach: true });
      const clip = () => screen.getByRole('button', { name: 'Datei anhängen' });
      clip().focus();
      await pick(pdf('a.pdf'));
      expect(clip()).toHaveFocus();
      await pick(...Array.from({ length: 4 }, (_, i) => pdf(`f${i}.pdf`)));
      expect(clip()).toBeDisabled();
      expect(input()).toHaveFocus();
    });

    it('leaves the focus where it is when the paperclip had none', async () => {
      const { cmp, view } = await setup({ canAttach: true });
      const other = document.createElement('button');
      document.body.appendChild(other);
      other.focus();
      await cmp.addFiles(Array.from({ length: 5 }, (_, i) => pdf(`f${i}.pdf`)));
      view.fixture.detectChanges();
      expect(other).toHaveFocus();
      other.remove();
    });

    it('keeps the uploading chip a list item, with the status inside', async () => {
      const answer = new Subject<DraftUpload>();
      const { pick, view } = await setup({ canAttach: true, upload: () => answer });
      await pick(pdf());
      const chip = view.container.querySelector('.chat__draft--pending') as HTMLElement;
      expect(chip.tagName).toBe('LI');
      expect(chip).not.toHaveAttribute('role');
      expect(within(chip).getByRole('status')).toHaveTextContent('angebot.pdf');
      expect(within(view.container.querySelector('.chat__drafts') as HTMLElement).getAllByRole('listitem')).toHaveLength(1);
    });

    it('counts a batch still on its way against the 5 files of a message', async () => {
      const answers: Subject<DraftUpload>[] = [];
      const { pick, api, toast, cmp } = await setup({
        canAttach: true,
        upload: () => {
          const a = new Subject<DraftUpload>();
          answers.push(a);
          return a;
        },
      });
      await pick(...Array.from({ length: 4 }, (_, i) => pdf(`a${i}.pdf`)));
      expect(api.uploadDraftAttachment).toHaveBeenCalledTimes(1);
      expect(cmp.uploads()).toHaveLength(4);
      await pick(...Array.from({ length: 4 }, (_, i) => pdf(`b${i}.pdf`)));
      expect(toast.error).toHaveBeenCalledWith('Höchstens 5 Dateien pro Nachricht.');
      expect(cmp.uploads().map((u: { filename: string }) => u.filename)).toEqual([
        'a0.pdf',
        'a1.pdf',
        'a2.pdf',
        'a3.pdf',
        'b0.pdf',
      ]);
      expect(screen.getByRole('button', { name: 'Datei anhängen' })).toBeDisabled();
    });

    it('never sends a file whose remove is still running', async () => {
      const gone = new Subject<void>();
      const { pick, api, send, input, view } = await setup({ canAttach: true });
      await pick(pdf(), pdf('b.pdf'));
      api.deleteDraftAttachment.mockReturnValueOnce(gone);
      fireEvent.click(screen.getByRole('button', { name: 'angebot.pdf entfernen' }));
      view.fixture.detectChanges();
      expect(view.container.querySelectorAll('.chat__draft')).toHaveLength(1);
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(send.mock.calls[0][0]).toMatchObject({ attachmentIds: ['d2'] });
      gone.next();
      gone.complete();
    });

    it('checks the size before the upload', async () => {
      const { pick, api, toast } = await setup({ canAttach: true });
      await pick(pdf('gross.pdf', 11 * 1024 * 1024));
      expect(toast.error).toHaveBeenCalledWith('gross.pdf: Datei zu groß (max. 10 MB).');
      expect(api.uploadDraftAttachment).not.toHaveBeenCalled();
    });

    it('names a refused upload', async () => {
      let status = 415;
      const { toast, cmp } = await setup({
        canAttach: true,
        upload: () => throwError(() => new HttpErrorResponse({ status })),
      });
      await cmp.addFiles([pdf('a.exe')]);
      expect(toast.error).toHaveBeenLastCalledWith('a.exe: Dieser Dateityp ist nicht erlaubt.');
      status = 413;
      await cmp.addFiles([pdf('b.pdf')]);
      expect(toast.error).toHaveBeenLastCalledWith('b.pdf: Datei zu groß (max. 10 MB).');
      status = 500;
      await cmp.addFiles([pdf('c.pdf')]);
      expect(toast.error).toHaveBeenLastCalledWith('c.pdf: Die Datei konnte nicht hochgeladen werden.');
    });

    it('maps the reasons of the draft service to the chat texts', () => {
      expect(chatUploadError('apply.files.error.type')).toBe('chat.error.fileType');
      expect(chatUploadError('apply.files.error.tooLarge')).toBe('chat.error.fileTooLarge');
      expect(chatUploadError('apply.files.error.rateLimit')).toBe('chat.error.upload');
    });

    it('ignores an empty pick', async () => {
      const { view, api, settle } = await setup({ canAttach: true });
      const box = view.container.querySelector('.chat__fileInput') as HTMLInputElement;
      Object.defineProperty(box, 'files', { value: null, configurable: true });
      fireEvent.change(box);
      await settle();
      expect(api.uploadDraftAttachment).not.toHaveBeenCalled();
    });

    it('takes a pasted image and names one without an extension', async () => {
      const { input, api, cmp, settle } = await setup({ canAttach: true });
      jest.spyOn(cmp, 'now').mockReturnValue(new Date(2026, 9, 15, 10, 45, 0));
      const paste = (files: File[]) => {
        const event = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent;
        Object.defineProperty(event, 'clipboardData', { value: { files, getData: () => '' } });
        input().dispatchEvent(event);
        return event;
      };
      const unnamed = paste([
        new File(['x'], 'image', { type: 'image/png' }),
        new File(['x'], '', { type: 'image/jpeg' }),
        new File(['x'], 'blob', { type: 'image/heic' }),
        new File(['x'], 'shot.png', { type: 'image/png' }),
      ]);
      expect(unnamed.defaultPrevented).toBe(true);
      await settle();
      const names = api.uploadDraftAttachment.mock.calls.map((c) => (c[0] as File).name);
      expect(names).toEqual(['Bild-20261015-104500.png', 'Bild-20261015-104500.jpg', 'Bild-20261015-104500.bin', 'shot.png']);
      expect((api.uploadDraftAttachment.mock.calls[0][0] as File).type).toBe('image/png');

      // Pasted text stays text.
      expect(paste([]).defaultPrevented).toBe(false);
      const plain = new Event('paste', { bubbles: true, cancelable: true });
      input().dispatchEvent(plain);
      expect(plain.defaultPrevented).toBe(false);
    });

    describe('a file dragged onto the composer', () => {
      const drag = (target: Element, type: 'dragover' | 'drop', files: File[], types = ['Files']) => {
        const event = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
        Object.defineProperty(event, 'dataTransfer', { value: { files, types, dropEffect: 'none' } });
        target.dispatchEvent(event);
        return event;
      };

      it('uploads the dropped files and keeps the tab', async () => {
        const { input, api, settle } = await setup({ canAttach: true });
        const over = drag(input(), 'dragover', []);
        expect(over.defaultPrevented).toBe(true);
        expect(over.dataTransfer?.dropEffect).toBe('copy');
        const drop = drag(input(), 'drop', [new File(['x'], 'a.pdf', { type: 'application/pdf' })]);
        expect(drop.defaultPrevented).toBe(true);
        await settle();
        expect(api.uploadDraftAttachment.mock.calls.map((c) => (c[0] as File).name)).toEqual(['a.pdf']);
      });

      it('applies the limit of five files', async () => {
        const { input, api, toast, settle } = await setup({ canAttach: true });
        const files = Array.from({ length: 6 }, (_, i) => new File(['x'], `f${i}.pdf`, { type: 'application/pdf' }));
        drag(input(), 'drop', files);
        await settle();
        expect(api.uploadDraftAttachment).toHaveBeenCalledTimes(5);
        expect(toast.error).toHaveBeenCalledWith('Höchstens 5 Dateien pro Nachricht.');
      });

      it('takes the drop without files too, so the browser does not open the file', async () => {
        const { input, api, settle } = await setup();
        const over = drag(input(), 'dragover', []);
        expect(over.defaultPrevented).toBe(true);
        expect(over.dataTransfer?.dropEffect).toBe('none');
        const drop = drag(input(), 'drop', [new File(['x'], 'a.pdf', { type: 'application/pdf' })]);
        expect(drop.defaultPrevented).toBe(true);
        await settle();
        expect(api.uploadDraftAttachment).not.toHaveBeenCalled();
      });

      it('leaves a text drag to the textarea', async () => {
        const { input } = await setup({ canAttach: true });
        expect(drag(input(), 'dragover', [], ['text/plain']).defaultPrevented).toBe(false);
        expect(drag(input(), 'drop', [], ['text/plain']).defaultPrevented).toBe(false);
      });
    });

    it('keeps the text of a paste that also holds a picture of it (Word, a web page)', async () => {
      const { input, api, settle } = await setup({ canAttach: true });
      const paste = (data: Record<string, string>) => {
        const event = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent;
        Object.defineProperty(event, 'clipboardData', {
          value: {
            types: [...Object.keys(data), 'Files'],
            files: [new File(['x'], 'image.png', { type: 'image/png' })],
            getData: (type: string) => data[type] ?? '',
          },
        });
        input().dispatchEvent(event);
        return event;
      };
      expect(paste({ 'text/plain': 'Tabelle', 'text/html': '<table></table>' }).defaultPrevented).toBe(false);
      await settle();
      expect(api.uploadDraftAttachment).not.toHaveBeenCalled();
      expect(paste({}).defaultPrevented).toBe(true);
      await settle();
      expect(api.uploadDraftAttachment).toHaveBeenCalledTimes(1);
    });

    it('takes a copied image that comes with HTML and no plain text (a browser, Slack, Teams)', async () => {
      const { input, api, settle } = await setup({ canAttach: true });
      const event = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent;
      Object.defineProperty(event, 'clipboardData', {
        value: {
          types: ['text/html', 'Files'],
          files: [new File(['x'], 'image.png', { type: 'image/png' })],
          getData: (type: string) => (type === 'text/html' ? '<img src="https://x/y.png">' : ' '),
        },
      });
      input().dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
      await settle();
      expect(api.uploadDraftAttachment).toHaveBeenCalledTimes(1);
      expect((api.uploadDraftAttachment.mock.calls[0][0] as File).name).toBe('image.png');
    });

    it('takes no pasted file where the thread takes none', async () => {
      const { input, api } = await setup();
      const event = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent;
      Object.defineProperty(event, 'clipboardData', { value: { files: [new File(['x'], 'a.png', { type: 'image/png' })] } });
      input().dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
      expect(api.uploadDraftAttachment).not.toHaveBeenCalled();
    });

    it('drops the files of a thread the viewer leaves, and on destroy', async () => {
      const { pick, set, api, cmp, view, settle } = await setup({ canAttach: true });
      await pick(pdf());
      set('draftKey', 't2');
      await settle();
      expect(api.deleteDraftAttachment).toHaveBeenCalledWith('d1', 'tok');
      expect(cmp.files()).toEqual([]);
      await pick(pdf('b.pdf'));
      view.fixture.destroy();
      expect(api.deleteDraftAttachment).toHaveBeenCalledWith('d2', 'tok');
    });

    it('keeps the files of the page (ChatDrafts) when a layout switch re-creates the chat', async () => {
      @Component({
        standalone: true,
        imports: [ChatComponent],
        providers: [ChatDrafts],
        template: `
          @if (wide()) {
            <app-chat class="one" [draftKey]="key()" [canAttach]="true" />
          } @else {
            <app-chat class="one" [draftKey]="key()" [canAttach]="true" />
          }
          @if (second()) {
            <app-chat class="two" draftKey="other" [canAttach]="true" />
          }
        `,
      })
      class PageHost {
        readonly wide = signal(true);
        readonly key = signal('t1');
        readonly second = signal(false);
      }
      mockPhone(false);
      let n = 0;
      const api = {
        uploadDraftAttachment: jest.fn((file: File) => of(draftOf(file, ++n))),
        deleteDraftAttachment: jest.fn((): Observable<void> => of(undefined)),
      };
      const { fixture } = await render(PageHost, {
        providers: [
          { provide: ApiClient, useValue: api },
          { provide: AuthService, useValue: { isAuthenticated: signal(true) } },
          { provide: AltchaService, useValue: { solve: jest.fn(async () => 'sol') } },
          { provide: ToastService, useValue: { success: jest.fn(), error: jest.fn() } },
        ],
      });
      const settle = async () => {
        await new Promise((r) => setTimeout(r));
        fixture.detectChanges();
      };
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const chat = (cls: string): any => fixture.debugElement.query(By.css(`app-chat.${cls}`)).componentInstance;
      const pick = async (cls: string, file: File) => {
        const box = fixture.nativeElement.querySelector(`app-chat.${cls} .chat__fileInput`) as HTMLInputElement;
        Object.defineProperty(box, 'files', { value: [file], configurable: true });
        fireEvent.change(box);
        await settle();
      };
      await pick('one', pdf('a.pdf'));
      const first = chat('one');
      fixture.componentInstance.wide.set(false);
      await settle();
      expect(chat('one')).not.toBe(first);
      expect(chat('one').files().map((f: { id: string }) => f.id)).toEqual(['d1']);
      expect(api.deleteDraftAttachment).not.toHaveBeenCalled();
      expect(screen.getByRole('button', { name: 'a.pdf entfernen' })).toBeInTheDocument();

      // A second chat beside it gets drafts of its own, and its files go with it.
      fixture.componentInstance.second.set(true);
      await settle();
      expect(chat('two').files()).toEqual([]);
      await pick('two', pdf('b.pdf'));
      expect(chat('one').files().map((f: { id: string }) => f.id)).toEqual(['d1']);
      fixture.componentInstance.second.set(false);
      await settle();
      expect(api.deleteDraftAttachment).toHaveBeenCalledWith('d2', 'tok');
      expect(api.deleteDraftAttachment).toHaveBeenCalledTimes(1);

      // Another thread drops them; so does the page when it goes.
      fixture.componentInstance.key.set('t2');
      await settle();
      expect(api.deleteDraftAttachment).toHaveBeenCalledWith('d1', 'tok');
      await pick('one', pdf('c.pdf'));
      fixture.destroy();
      await new Promise((r) => setTimeout(r));
      expect(api.deleteDraftAttachment).toHaveBeenCalledWith('d3', 'tok');
    });

    it('drops an upload that is still running when the thread changes', async () => {
      const answer = new Subject<DraftUpload>();
      const { pick, set, api, cmp, settle, view } = await setup({ canAttach: true, upload: () => answer });
      await pick(pdf());
      expect(cmp.uploads()).toHaveLength(1);
      set('draftKey', 't2');
      await settle();
      expect(cmp.uploads()).toEqual([]);
      answer.next(draftOf(pdf(), 1));
      answer.complete();
      await settle();
      expect(cmp.files()).toEqual([]);
      expect(view.container.querySelectorAll('.chat__draft')).toHaveLength(0);
      expect(api.deleteDraftAttachment).toHaveBeenCalledWith('d1', 'tok');
    });

    it('moves the focus to the next chip, then the one before, then the text box after a remove', async () => {
      const { pick, settle, input } = await setup({ canAttach: true });
      await pick(pdf('a.pdf'), pdf('b.pdf'), pdf('c.pdf'));
      fireEvent.click(screen.getByRole('button', { name: 'b.pdf entfernen' }));
      await settle();
      expect(screen.getByRole('button', { name: 'c.pdf entfernen' })).toHaveFocus();
      fireEvent.click(screen.getByRole('button', { name: 'c.pdf entfernen' }));
      await settle();
      expect(screen.getByRole('button', { name: 'a.pdf entfernen' })).toHaveFocus();
      fireEvent.click(screen.getByRole('button', { name: 'a.pdf entfernen' }));
      await settle();
      expect(input()).toHaveFocus();
    });

    describe('scan refresh', () => {
      const scanning = (id: string, extra: Partial<ChatMessage> = {}) =>
        msg(id, today(9), {
          attachments: [{ id: `f-${id}`, filename: 'a.png', mime: 'image/png', size: 1, url: '/a', scanState: 'scanning' }],
          ...extra,
        });
      beforeEach(() => jest.useFakeTimers());
      afterEach(() => jest.useRealTimers());

      it('reads the thread again with a back-off while a sent file is in the scan', async () => {
        const { refresh, set } = await setup({ messages: [scanning('a')] });
        expect(SCAN_BACKOFF.reduce((a, b) => a + b, 0)).toBe(30_000);
        jest.advanceTimersByTime(SCAN_BACKOFF[0] - 1);
        expect(refresh).not.toHaveBeenCalled();
        jest.advanceTimersByTime(1);
        expect(refresh).toHaveBeenCalledTimes(1);
        jest.advanceTimersByTime(SCAN_BACKOFF[1]);
        expect(refresh).toHaveBeenCalledTimes(2);
        // The same file still in the scan keeps the back-off where it is.
        set('messages', [scanning('a', { body: 'neu' })]);
        jest.advanceTimersByTime(SCAN_BACKOFF[2] + SCAN_BACKOFF[3]);
        expect(refresh).toHaveBeenCalledTimes(4);
        // The back-off has run out.
        jest.advanceTimersByTime(60_000);
        expect(refresh).toHaveBeenCalledTimes(4);
        // A new file in the scan starts it again.
        set('messages', [scanning('a'), scanning('b')]);
        jest.advanceTimersByTime(SCAN_BACKOFF[0]);
        expect(refresh).toHaveBeenCalledTimes(5);
        // One file out of the scan, another still in it: the back-off goes on.
        set('messages', [scanning('b')]);
        jest.advanceTimersByTime(SCAN_BACKOFF[1]);
        expect(refresh).toHaveBeenCalledTimes(6);
      });

      it('stops once the scan is done, and never runs for pending, lost or clean files', async () => {
        const { refresh, set, view } = await setup({ messages: [scanning('a')] });
        set('messages', [msg('a', today(9), { attachments: [{ id: 'f-a', filename: 'a.png', mime: 'image/png', size: 1, url: '/a', scanState: 'clean' }] })]);
        jest.advanceTimersByTime(60_000);
        expect(refresh).not.toHaveBeenCalled();
        set('messages', [
          scanning('p', { state: 'sending' }),
          msg('l', today(9), { attachments: [{ id: 'f-l', filename: 'a.png', mime: 'image/png', size: 1, url: '/a', scanState: 'scanning', lost: true }] }),
          msg('n', today(9)),
        ]);
        jest.advanceTimersByTime(60_000);
        expect(refresh).not.toHaveBeenCalled();
        set('messages', [scanning('a')]);
        view.fixture.destroy();
        jest.advanceTimersByTime(60_000);
        expect(refresh).not.toHaveBeenCalled();
      });
    });

    it('links only clean files of a message; others show their scan state', async () => {
      const file = (id: string, extra: object) => ({
        id,
        filename: `${id}.pdf`,
        mime: 'application/pdf',
        size: 10,
        url: `/api/attachments/${id}/download`,
        ...extra,
      });
      const { view } = await setup({
        messages: [
          msg('a', today(9), {
            attachments: [
              file('clean', { scanState: 'clean' }),
              file('plain', {}),
              file('scan', { scanState: 'scanning' }),
              file('bad', { scanState: 'quarantined' }),
              file('gone', { scanState: 'scanning', lost: true }),
              file('lost', { lost: true }),
            ],
          }),
        ],
      });
      expect(screen.getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual([
        '/api/attachments/clean/download',
        '/api/attachments/plain/download',
      ]);
      const off = [...view.container.querySelectorAll('.chat__file--off')].map((c) => c.textContent?.replace(/\s+/g, ' ').trim());
      expect(off).toEqual([
        'scan.pdf PDF · 1 KB · In Prüfung',
        'bad.pdf PDF · 1 KB · Quarantäne',
        'gone.pdf PDF · 1 KB · Nicht mehr vorhanden',
        'lost.pdf PDF · 1 KB · Nicht mehr vorhanden',
      ]);
    });

    it('keeps the files of a message in view, read-only, while it is in edit', async () => {
      const { view } = await setup({
        messages: [
          msg('m', today(9), {
            own: true,
            body: 'Alt',
            attachments: [
              { id: 'f1', filename: 'plan.pdf', mime: 'application/pdf', size: 10, url: '/api/attachments/f1/download', scanState: 'clean' },
              { id: 'f2', filename: 'bild.png', mime: 'image/png', size: 10, url: '/x', scanState: 'scanning' },
            ],
          }),
        ],
      });
      fireEvent.click(screen.getByRole('button', { name: 'Nachricht bearbeiten' }));
      const form = view.container.querySelector('.chat__edit') as HTMLElement;
      expect(form).not.toBeNull();
      expect(within(form).getByRole('link', { name: /plan\.pdf/ })).toHaveAttribute('href', '/api/attachments/f1/download');
      expect(within(form).getByText('bild.png')).toBeInTheDocument();
      expect(form.querySelectorAll('button[aria-label*="entfernen"]')).toHaveLength(0);
    });

    it('offers no edit for a failed message with files', async () => {
      await setup({
        messages: [
          msg('f', today(10), {
            own: true,
            state: 'failed',
            attachments: [{ id: 'x', filename: 'x.pdf', mime: 'application/pdf', size: 1, url: '/x', scanState: 'scanning' }],
          }),
        ],
      });
      expect(screen.getByRole('button', { name: 'Erneut senden' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Bearbeiten' })).not.toBeInTheDocument();
    });

    it('offers the edit once every file of a failed message is lost', async () => {
      const { discard } = await setup({
        messages: [
          msg('f', today(10), {
            own: true,
            body: '',
            state: 'failed',
            attachments: [{ id: 'x', filename: 'x.pdf', mime: 'application/pdf', size: 1, url: '/x', lost: true }],
          }),
        ],
      });
      fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
      expect(discard).toHaveBeenCalledWith({ id: 'f' });
    });

    it('marks a lost file in the composer', async () => {
      const { pick, cmp, view } = await setup({ canAttach: true });
      await pick(pdf());
      cmp.drafts.markFailed({ code: 'draft_attachments_missing', errors: [{ field: 'attachmentIds.d1' }] });
      view.fixture.detectChanges();
      const chip = view.container.querySelector('.chat__draft') as HTMLElement;
      expect(chip).toHaveClass('chat__draft--failed');
      expect(chip).toHaveTextContent('Nicht mehr vorhanden');
    });

    it('has no a11y violations with chips', async () => {
      const { pick, view } = await setup({ canAttach: true });
      await pick(pdf());
      expect(await runAxe(view.container)).toHaveNoViolations();
    });
  });
});

