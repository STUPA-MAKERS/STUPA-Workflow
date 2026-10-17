import { markdownToSafeHtml } from './markdown.util';

describe('markdownToSafeHtml', () => {
  it('escapes raw HTML before rendering (XSS-safe)', () => {
    const html = markdownToSafeHtml('<script>alert(1)</script>');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('preserves single line breaks inside a paragraph as <br>', () => {
    expect(markdownToSafeHtml('Zeile 1\nZeile 2')).toBe('<p>Zeile 1<br>Zeile 2</p>');
  });

  it('splits paragraphs on blank lines', () => {
    expect(markdownToSafeHtml('Absatz 1\n\nAbsatz 2')).toBe('<p>Absatz 1</p>\n<p>Absatz 2</p>');
  });

  it('renders bold, italic and inline code', () => {
    const html = markdownToSafeHtml('**fett** und *kursiv* und `code`');
    expect(html).toContain('<strong>fett</strong>');
    expect(html).toContain('<em>kursiv</em>');
    expect(html).toContain('<code>code</code>');
  });

  it('does not apply markup inside code spans', () => {
    expect(markdownToSafeHtml('`**nicht fett**`')).toContain('<code>**nicht fett**</code>');
  });

  it('renders http links with rel=noopener and rejects other protocols', () => {
    const ok = markdownToSafeHtml('[Seite](https://example.org/a?b=1&c=2)');
    expect(ok).toContain('<a href="https://example.org/a?b=1&amp;c=2"');
    expect(ok).toContain('rel="noopener noreferrer"');
    const bad = markdownToSafeHtml('[x](javascript:alert(1))');
    expect(bad).not.toContain('<a ');
  });

  it('renders unordered and ordered lists', () => {
    expect(markdownToSafeHtml('- a\n- b')).toBe('<ul><li>a</li><li>b</li></ul>');
    expect(markdownToSafeHtml('1. a\n2. b')).toBe('<ol><li>a</li><li>b</li></ol>');
  });

  it('renders headings shifted down to h4–h6', () => {
    expect(markdownToSafeHtml('# Titel')).toBe('<h4>Titel</h4>');
    expect(markdownToSafeHtml('### Klein')).toBe('<h6>Klein</h6>');
  });

  it('renders quotes and fenced code blocks', () => {
    expect(markdownToSafeHtml('> Zitat')).toBe('<blockquote>Zitat</blockquote>');
    expect(markdownToSafeHtml('```\ncode <x>\n```')).toBe('<pre><code>code &lt;x&gt;</code></pre>');
  });

  describe('tables', () => {
    const table = '| Antrag | Status | Betrag |\n|---|:---:|---:|\n| A-1 | offen | 12,00 |';

    it('renders a GFM pipe table with alignment inside a scroll wrapper', () => {
      const html = markdownToSafeHtml(table);
      expect(html.startsWith('<div class="mdv__table"><table><thead><tr><th>Antrag</th>')).toBe(true);
      expect(html).toContain('<th class="mdv__al--center">Status</th>');
      expect(html).toContain('<td class="mdv__al--right">12,00</td>');
      expect(html).toContain('<td>A-1</td>');
    });

    it('renders left alignment, short rows and rows without outer pipes', () => {
      const html = markdownToSafeHtml('a | b\n:-- | ---\n1 |\nnach');
      expect(html).toContain('<th class="mdv__al--left">a</th>');
      expect(html).toContain('<tr><td class="mdv__al--left">1</td><td></td></tr>');
      expect(html).toContain('<p>nach</p>');
    });

    it('keeps an escaped pipe inside its cell', () => {
      expect(markdownToSafeHtml('| a |\n| --- |\n| x \\| y |')).toContain('<td>x | y</td>');
    });

    it('escapes HTML in cells', () => {
      const html = markdownToSafeHtml('| a |\n| --- |\n| <script>alert(1)</script> |');
      expect(html).not.toContain('<script>');
      expect(html).toContain('<td>&lt;script&gt;alert(1)&lt;/script&gt;</td>');
    });

    it('needs a separator row with the column count of the header', () => {
      expect(markdownToSafeHtml('| a | b |\n| --- |')).not.toContain('<table>');
      expect(markdownToSafeHtml('a | b\nkein Trenner')).toBe('<p>a | b<br>kein Trenner</p>');
      expect(markdownToSafeHtml('a | b\n| x | -- |')).not.toContain('<table>');
      expect(markdownToSafeHtml('a | b\n---')).toBe('<p>a | b</p>\n<hr>');
      expect(markdownToSafeHtml('a | b\nfoo-bar')).not.toContain('<table>');
    });
  });

  describe('images', () => {
    const id = '0b8f3c3e-4d6a-4f43-9a1e-2f0c1d2e3f40';

    it('renders the canonical path as a lazy image', () => {
      expect(markdownToSafeHtml(`![Plan](/api/media/images/${id})`)).toBe(
        `<p><img src="/api/media/images/${id}" alt="Plan" loading="lazy" decoding="async"></p>`,
      );
    });

    it('maps the source through imageSrc', () => {
      const html = markdownToSafeHtml(`![x](/api/media/images/${id})`, {
        imageSrc: (i) => `/api/public/protocols/p"1/images/${i}`,
      });
      expect(html).toContain(`src="/api/public/protocols/p&quot;1/images/${id}"`);
    });

    it('renders the alt text only when imageSrc is null', () => {
      expect(markdownToSafeHtml(`![Plan](/api/media/images/${id})`, { imageSrc: null })).toBe(
        '<p>Plan</p>',
      );
      expect(markdownToSafeHtml(`a ![](/api/media/images/${id}) b`, { imageSrc: null })).toBe(
        '<p>a  b</p>',
      );
    });

    it.each([
      ['javascript', '![x](javascript:alert(1))'],
      ['external', '![x](https://evil/p.png)'],
      ['traversal', '![x](/api/media/images/../../x)'],
      ['upper case uuid', `![x](/api/media/images/${id.toUpperCase()})`],
      ['data', '![x](data:image/png;base64,AAAA)'],
    ])('never loads a %s image', (_kind, src) => {
      const html = markdownToSafeHtml(src);
      expect(html).not.toContain('<img');
      expect(html).not.toContain('<a ');
      expect(html).toContain('x');
    });

    it('escapes quotes and markup in the alt text', () => {
      const html = markdownToSafeHtml(`![a" onerror="x' **b**](/api/media/images/${id})`);
      expect(html).toContain('alt="a&quot; onerror=&quot;x&#39; **b**"');
      expect(html).not.toContain('<strong>');
    });
  });

  it('renders horizontal rules, strike-through and task items', () => {
    expect(markdownToSafeHtml('---')).toBe('<hr>');
    expect(markdownToSafeHtml('* * *')).toBe('<hr>');
    expect(markdownToSafeHtml('~~alt~~ neu')).toBe('<p><del>alt</del> neu</p>');
    expect(markdownToSafeHtml('- [ ] offen\n- [x] fertig')).toBe(
      '<ul><li class="mdv__task"><input type="checkbox" disabled> offen</li>' +
        '<li class="mdv__task"><input type="checkbox" disabled checked> fertig</li></ul>',
    );
  });

  it('renders callouts and keeps an unknown marker as a quote', () => {
    const html = markdownToSafeHtml('> [!abstimmung] **Frage**\n> ja: 3');
    expect(html).toBe(
      '<div class="callout callout--abstimmung"><p class="callout__title">Abstimmung</p>' +
        '<p><strong>Frage</strong><br>ja: 3</p></div>',
    );
    expect(markdownToSafeHtml('> [!NOTE]')).toContain('callout--note');
    expect(markdownToSafeHtml('> [!FOO] bar')).toBe('<blockquote>[!FOO] bar</blockquote>');
  });

  it('honours headingOffset', () => {
    expect(markdownToSafeHtml('# Titel', { headingOffset: 0 })).toBe('<h1>Titel</h1>');
    expect(markdownToSafeHtml('###### Tief', { headingOffset: 3 })).toBe('<h6>Tief</h6>');
  });

  it('renders app paths as links but no protocol-relative URL', () => {
    expect(markdownToSafeHtml('[A](/applications/1)')).toContain('<a href="/applications/1"');
    expect(markdownToSafeHtml('[A](//evil.test)')).not.toContain('<a ');
    const quoted = markdownToSafeHtml('[A](https://e.test/"x)');
    expect(quoted).toContain('[A](');
    expect(quoted).not.toMatch(/href="[^"]*&quot;/);
  });

  describe('links', () => {
    it('renders app paths and anchors in the same tab', () => {
      expect(markdownToSafeHtml('[Antrag](/applications/1?tab=a&b=2)')).toBe(
        '<p><a href="/applications/1?tab=a&amp;b=2">Antrag</a></p>',
      );
      expect(markdownToSafeHtml('[oben](#top)')).toBe('<p><a href="#top">oben</a></p>');
    });

    it('opens http, https and mailto links in a new tab', () => {
      expect(markdownToSafeHtml('[M](mailto:a@b.de)')).toContain(
        '<a href="mailto:a@b.de" target="_blank" rel="noopener noreferrer">M</a>',
      );
      expect(markdownToSafeHtml('[H](http://x.de)')).toContain('target="_blank"');
    });

    it('keeps balanced parentheses in the destination', () => {
      expect(markdownToSafeHtml('[W](https://de.wikipedia.org/wiki/A_(B)) danach')).toBe(
        '<p><a href="https://de.wikipedia.org/wiki/A_(B)" target="_blank" rel="noopener noreferrer">W</a> danach</p>',
      );
    });

    it.each([
      ['javascript', '[x](javascript:alert(1))'],
      ['data', '[x](data:text/html,1)'],
      ['vbscript', '[x](vbscript:msgbox)'],
      ['backslash', '[x](/\\evil.test)'],
      ['protocol-relative', '[x](//evil.test)'],
      ['relative', '[x](foo/bar)'],
      ['empty label', '[](/a)'],
      ['space', '[x](/a b)'],
      ['unclosed', '[x](/a'],
      ['no paren', '[x] /a'],
    ])('keeps a %s link as text', (_kind, src) => {
      const html = markdownToSafeHtml(src);
      expect(html).not.toContain('<a ');
      expect(html).toContain('[');
    });

    it('links only the inner part of a nested label', () => {
      expect(markdownToSafeHtml('[a [b](/c)')).toBe('<p>[a <a href="/c">b</a></p>');
    });

    it('renders a link inside a table cell', () => {
      const html = markdownToSafeHtml('| A |\n| --- |\n| [T-1](/tickets/1) |');
      expect(html).toContain('<td><a href="/tickets/1">T-1</a></td>');
    });

    it('autolinks bare URLs, but not inside code or links', () => {
      expect(markdownToSafeHtml('Siehe https://x.de/a.')).toBe(
        '<p>Siehe <a href="https://x.de/a" target="_blank" rel="noopener noreferrer">https://x.de/a</a>.</p>',
      );
      expect(markdownToSafeHtml('`https://x.de`')).toBe('<p><code>https://x.de</code></p>');
      expect(markdownToSafeHtml('[https://x.de](https://y.de)')).toBe(
        '<p><a href="https://y.de" target="_blank" rel="noopener noreferrer">https://x.de</a></p>',
      );
    });

    it('wraps an image in a link', () => {
      const id = '0b8f3c3e-4d6a-4f43-9a1e-2f0c1d2e3f40';
      expect(markdownToSafeHtml(`[![P](/api/media/images/${id})](/x)`)).toContain(
        `<a href="/x"><img src="/api/media/images/${id}"`,
      );
    });
  });

  it('keeps code spans inside a link label and emphasis out of attributes', () => {
    expect(markdownToSafeHtml('[`x` **y**](https://e.test/a_b_c)')).toBe(
      '<p><a href="https://e.test/a_b_c" target="_blank" rel="noopener noreferrer">' +
        '<code>x</code> <strong>y</strong></a></p>',
    );
  });

  it('closes an unterminated fence at the end', () => {
    expect(markdownToSafeHtml('```\na')).toBe('<pre><code>a</code></pre>');
  });
});
