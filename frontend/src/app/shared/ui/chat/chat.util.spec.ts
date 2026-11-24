import { linkify } from '@shared/markdown/linkify';
import { appendOnce, chatFileUrl, toChatAttachments, withScanStates } from './chat.util';

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
