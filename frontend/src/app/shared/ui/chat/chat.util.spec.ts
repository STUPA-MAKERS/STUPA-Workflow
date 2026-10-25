import { linkify } from '@shared/markdown/linkify';
import type { ChatMessage } from './chat.models';
import {
  appendOnce,
  buildItems,
  chatFileUrl,
  dayKey,
  isPending,
  newCount,
  toChatAttachments,
  withScanStates,
  type BuildOptions,
  type ChatItem,
} from './chat.util';

const at = (iso: string) => new Date(iso).toISOString();

function msg(id: string, time: string, extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id,
    author: { principalId: 'p-1', displayName: 'Jonas Albrecht' },
    body: id,
    at: at(time),
    own: false,
    ...extra,
  };
}

const opts = (extra: Partial<BuildOptions> = {}): BuildOptions => ({
  marked: false,
  markerAt: null,
  dayLabel: (d) => `day ${d.getDate()}`,
  name: (m) => m.author?.displayName ?? null,
  ...extra,
});

const kinds = (items: ChatItem[]) =>
  items.map((i) => (i.kind === 'msg' ? `${i.msg.id}${i.head ? 'H' : ''}${i.tail ? 'T' : ''}` : i.kind));

describe('chat util', () => {
  it('tells pending messages', () => {
    expect(isPending(msg('a', '2026-10-12T10:00:00'))).toBe(false);
    expect(isPending(msg('a', '2026-10-12T10:00:00', { state: 'sent' }))).toBe(false);
    expect(isPending(msg('a', '2026-10-12T10:00:00', { state: 'sending' }))).toBe(true);
    expect(isPending(msg('a', '2026-10-12T10:00:00', { state: 'failed' }))).toBe(true);
  });

  it('keys a local day', () => {
    expect(dayKey(new Date(2026, 9, 12, 23, 59))).toBe('2026-10-12');
  });

  it('counts new messages of others only', () => {
    const list = [
      msg('a', '2026-10-12T10:00:00'),
      msg('b', '2026-10-12T11:00:00'),
      msg('c', '2026-10-12T12:00:00', { own: true }),
      msg('d', '2026-10-12T13:00:00', { state: 'sending' }),
    ];
    expect(newCount(list, null)).toBe(0);
    expect(newCount(list, at('2026-10-12T10:30:00'))).toBe(1);
    expect(newCount(list, at('2026-10-12T09:00:00'))).toBe(2);
  });

  it('groups one person within 5 minutes and puts the time on the last', () => {
    const items = buildItems(
      [
        msg('a', '2026-10-12T10:00:00'),
        msg('b', '2026-10-12T10:04:00'),
        msg('c', '2026-10-12T10:10:00'),
        msg('d', '2026-10-12T10:11:00', { author: { principalId: 'p-2', displayName: 'Selin' } }),
        msg('e', '2026-10-12T10:12:00', { own: true }),
        msg('f', '2026-10-12T10:13:00', { own: true }),
      ],
      [],
      opts(),
    );
    expect(kinds(items)).toEqual(['day', 'aH', 'bT', 'cHT', 'dHT', 'eH', 'fT']);
    const own = items.find((i) => i.kind === 'msg' && i.msg.id === 'e');
    expect(own && own.kind === 'msg' && own.name).toBeNull();
  });

  it('keeps a group over a change of visibility, labels each change, marks only when asked', () => {
    const list = [
      msg('a', '2026-10-12T10:00:00', { visibility: 'public' }),
      msg('b', '2026-10-12T10:01:00', { visibility: 'internal' }),
      msg('b2', '2026-10-12T10:01:30', { visibility: 'internal' }),
      msg('c', '2026-10-12T10:02:00'),
    ];
    const marked = buildItems(list, [], opts({ marked: true }));
    expect(kinds(marked)).toEqual(['day', 'aH', 'b', 'b2', 'cT']);
    expect(marked.map((i) => (i.kind === 'msg' ? i.mark : '-'))).toEqual(['-', 'public', 'internal', 'internal', null]);
    expect(marked.map((i) => (i.kind === 'msg' ? i.markLabel : '-'))).toEqual(['-', true, true, false, true]);
    const plain = buildItems(list, [], opts());
    expect(plain.map((i) => (i.kind === 'msg' ? i.mark : '-'))).toEqual(['-', null, null, null, null]);
  });

  it('puts day separators and events in time order, pending messages last', () => {
    const items = buildItems(
      [
        msg('pending', '2026-10-10T08:00:00', { own: true, state: 'failed' }),
        msg('b', '2026-10-13T09:00:00'),
        msg('a', '2026-10-12T09:00:00'),
      ],
      [{ id: 'ev', at: at('2026-10-13T08:00:00'), text: 'Status' }],
      opts(),
    );
    expect(kinds(items)).toEqual(['day', 'aHT', 'day', 'event', 'bHT', 'day', 'pendingHT']);
    expect(items[0]).toEqual({ kind: 'day', key: 'day-2026-10-12', label: 'day 12' });
    expect(items[3]).toMatchObject({ kind: 'event', text: 'Status', key: 'ev-ev' });
  });

  it('an event breaks a group', () => {
    const items = buildItems(
      [msg('a', '2026-10-12T10:00:00'), msg('b', '2026-10-12T10:02:00')],
      [{ id: 'ev', at: at('2026-10-12T10:01:00'), text: 'x' }],
      opts(),
    );
    expect(kinds(items)).toEqual(['day', 'aHT', 'event', 'bHT']);
  });

  /** When nothing is new there is no separator. */
  it('puts "N neue" before the first new message of another person', () => {
    const list = [
      msg('a', '2026-10-12T10:00:00'),
      msg('own', '2026-10-12T10:20:00', { own: true }),
      msg('b', '2026-10-12T10:21:00'),
      msg('c', '2026-10-12T10:22:00'),
    ];
    const items = buildItems(list, [], opts({ markerAt: at('2026-10-12T10:10:00') }));
    expect(kinds(items)).toEqual(['day', 'aHT', 'ownHT', 'new', 'bH', 'cT']);
    expect(items[3]).toEqual({ kind: 'new', key: 'new', count: 2 });
    expect(kinds(buildItems(list, [], opts({ markerAt: at('2026-10-12T11:00:00') })))).not.toContain('new');
  });

  it('names the authors through the callback', () => {
    const items = buildItems([msg('a', '2026-10-12T10:00:00', { author: null })], [], opts({ name: () => 'X' }));
    expect(items[1]).toMatchObject({ kind: 'msg', name: 'X' });
  });

  it('groups by label when there is no account', () => {
    const items = buildItems(
      [
        msg('a', '2026-10-12T10:00:00', { author: null, authorLabel: 'Gremium' }),
        msg('b', '2026-10-12T10:01:00', { author: null, authorLabel: 'Gremium' }),
        msg('c', '2026-10-12T10:02:00', { author: null }),
      ],
      [],
      opts(),
    );
    expect(kinds(items)).toEqual(['day', 'aH', 'bT', 'cHT']);
  });

  describe('linkify', () => {
    it('links a bare URL without shortening it', () => {
      expect(linkify('<p>Siehe https://example.de/a/b?c=1&amp;d=2</p>')).toBe(
        '<p>Siehe <a href="https://example.de/a/b?c=1&amp;d=2" target="_blank" rel="noopener noreferrer">https://example.de/a/b?c=1&amp;d=2</a></p>',
      );
    });

    it('leaves the punctuation after a URL outside the link', () => {
      expect(linkify('http://x.de/a.')).toBe(
        '<a href="http://x.de/a" target="_blank" rel="noopener noreferrer">http://x.de/a</a>.',
      );
      expect(linkify('&lt;https://x.de&gt;')).toBe(
        '&lt;<a href="https://x.de" target="_blank" rel="noopener noreferrer">https://x.de</a>&gt;',
      );
    });

    it('does not touch links and code', () => {
      const html =
        '<p><a href="https://a.de" target="_blank">https://a.de</a> <code>https://b.de</code></p><pre><code>https://c.de</code></pre>';
      expect(linkify(html)).toBe(html);
    });
  });
});

describe('message files', () => {
  it('maps the wire files to chat files with a streamed download', () => {
    expect(chatFileUrl('/api', 'f1')).toBe('/api/attachments/f1/download');
    expect(
      toChatAttachments('/api', [{ id: 'f1', filename: 'a.pdf', mime: 'application/pdf', size: 3, scanState: 'quarantined' }]),
    ).toEqual([
      { id: 'f1', filename: 'a.pdf', mime: 'application/pdf', size: 3, scanState: 'quarantined', url: '/api/attachments/f1/download' },
    ]);
    expect(toChatAttachments('/api', undefined)).toEqual([]);
    expect(toChatAttachments('/api', null)).toEqual([]);
  });
});

describe('withScanStates and appendOnce', () => {
  const file = (id: string, scanState: 'scanning' | 'clean' | 'quarantined') => ({
    id,
    filename: `${id}.pdf`,
    mime: 'application/pdf',
    size: 1,
    scanState,
  });

  it('takes only the scan states of a read, keeps every message on screen and the same objects without a change', () => {
    const plain: { id: string; body: string; attachments?: ReturnType<typeof file>[] } = { id: 'm0', body: 'ohne' };
    const same = { id: 'm1', body: 'a', attachments: [file('f1', 'clean')] };
    const scanning = { id: 'm2', body: 'neu', attachments: [file('f2', 'scanning'), file('f3', 'scanning')] };
    const delivered = { id: 'm3', body: 'nach dem Lesen', attachments: [file('f4', 'scanning')] };
    const fresh = [
      { id: 'm1', body: 'alt', attachments: [file('f1', 'clean')] },
      { id: 'm2', body: 'alt', attachments: [file('f2', 'quarantined')] },
      { id: 'gone', attachments: null },
    ];
    const out = withScanStates([plain, same, scanning, delivered], fresh);
    expect(out.map((m) => m.id)).toEqual(['m0', 'm1', 'm2', 'm3']);
    expect(out[0]).toBe(plain);
    expect(out[1]).toBe(same);
    expect(out[2].body).toBe('neu');
    expect(out[2].attachments?.map((f) => f.scanState)).toEqual(['quarantined', 'scanning']);
    expect(out[3]).toBe(delivered);
  });

  it('adds a delivered message once and replaces one already there', () => {
    const list = [{ id: 'a', v: 1 }];
    expect(appendOnce(list, { id: 'b', v: 1 })).toEqual([{ id: 'a', v: 1 }, { id: 'b', v: 1 }]);
    expect(appendOnce([...list, { id: 'b', v: 1 }], { id: 'a', v: 2 })).toEqual([{ id: 'a', v: 2 }, { id: 'b', v: 1 }]);
  });
});
