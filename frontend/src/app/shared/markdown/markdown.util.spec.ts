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
});
