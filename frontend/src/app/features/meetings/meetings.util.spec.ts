import type { MeetingVote } from '@core/api/models';
import {
  antragSnippet,
  escapeHtml,
  insertAt,
  renderMarkdown,
  topSnippet,
  voteSnippet,
} from './meetings.util';

function vote(overrides: Partial<MeetingVote> = {}): MeetingVote {
  return {
    id: 'v-1',
    applicationId: 'app-1',
    agendaItemId: null,
    options: ['yes', 'no', 'abstain'],
    title: 'Förderung Ersti-Wochenende',
    question: null,
    status: 'closed',
    result: 'accepted',
    counts: { yes: 12, no: 3, abstain: 1 },
    leading: 'yes',
    closesAt: null,
    ...overrides,
  };
}

describe('escapeHtml', () => {
  it('neutralises HTML-significant characters', () => {
    expect(escapeHtml(`<script>"x"&'y'`)).toBe(
      '&lt;script&gt;&quot;x&quot;&amp;&#39;y&#39;',
    );
  });
});

describe('antragSnippet', () => {
  it('embeds the application id as a pytex shortcode with the title heading', () => {
    const snip = antragSnippet('app-1', 'Mein Antrag');
    expect(snip).toContain(':::antrag{#app-1}');
    expect(snip).toContain('### Mein Antrag');
    expect(snip.trimEnd().endsWith(':::')).toBe(true);
  });

  it('falls back to the id when no title is given', () => {
    expect(antragSnippet('app-9', null)).toContain('### app-9');
  });
});

describe('topSnippet', () => {
  it('numbers a freetext TOP heading without an application reference', () => {
    const snip = topSnippet(1, 'Begrüßung', null);
    expect(snip).toContain('## TOP 1: Begrüßung');
    expect(snip).not.toContain(':::antrag');
  });

  it('appends the application shortcode for an application TOP', () => {
    const snip = topSnippet(2, 'Förderantrag', 'app-7');
    expect(snip).toContain('## TOP 2: Förderantrag');
    expect(snip).toContain(':::antrag{#app-7}');
  });

  it('falls back to the application id when the title is blank', () => {
    expect(topSnippet(3, '   ', 'app-9')).toContain('## TOP 3: app-9');
  });

  it('falls back to a generic "TOP n" label when title and id are both missing', () => {
    expect(topSnippet(4, null, null)).toContain('## TOP 4: TOP 4');
  });
});

describe('voteSnippet', () => {
  it('renders a result table and the vote shortcode', () => {
    const snip = voteSnippet(vote());
    expect(snip).toContain(':::vote{#v-1}');
    expect(snip).toContain('| Option | Stimmen |');
    expect(snip).toContain('| yes | 12 |');
    expect(snip).toContain('**Ergebnis:** accepted');
  });

  it('omits the table when no counts are present', () => {
    const snip = voteSnippet(vote({ counts: null, result: null }));
    expect(snip).not.toContain('| Option |');
    expect(snip).toContain(':::vote{#v-1}');
  });

  it('omits the table when counts is an empty object', () => {
    const snip = voteSnippet(vote({ counts: {}, result: null }));
    expect(snip).not.toContain('| Option |');
  });

  it('uses the question as heading when there is no title', () => {
    const snip = voteSnippet(vote({ title: null, question: 'Soll X gefördert werden?' }));
    expect(snip).toContain('### Soll X gefördert werden?');
  });

  it('uses the applicationId as heading when title and question are blank', () => {
    const snip = voteSnippet(vote({ title: '  ', question: null, applicationId: 'app-42' }));
    expect(snip).toContain('### app-42');
  });

  it('falls back to "Beschluss" when nothing identifies the vote', () => {
    const snip = voteSnippet(vote({ title: null, question: null, applicationId: null }));
    expect(snip).toContain('### Beschluss');
  });
});

describe('insertAt', () => {
  it('inserts at the caret position', () => {
    expect(insertAt('abcd', 'X', 2)).toBe('abXcd');
  });

  it('appends when the caret is null or out of range', () => {
    expect(insertAt('abcd', 'X', null)).toBe('abcdX');
    expect(insertAt('abcd', 'X', 99)).toBe('abcdX');
  });
});

describe('renderMarkdown', () => {
  it('escapes raw HTML so editor input cannot inject markup', () => {
    const out = renderMarkdown('<img src=x onerror=alert(1)>');
    expect(out).not.toContain('<img');
    expect(out).toContain('&lt;img');
  });

  it('renders headings, bold, italic and inline code', () => {
    expect(renderMarkdown('# Titel')).toContain('<h1>Titel</h1>');
    expect(renderMarkdown('**fett**')).toContain('<strong>fett</strong>');
    expect(renderMarkdown('*kursiv*')).toContain('<em>kursiv</em>');
    expect(renderMarkdown('`code`')).toContain('<code>code</code>');
  });

  it('groups consecutive list items into a single list', () => {
    const out = renderMarkdown('- eins\n- zwei');
    expect(out).toContain('<ul>');
    expect((out.match(/<li>/g) ?? []).length).toBe(2);
    expect((out.match(/<ul>/g) ?? []).length).toBe(1);
  });

  it('renders blockquotes and paragraphs with line breaks', () => {
    expect(renderMarkdown('> Zitat')).toContain('<blockquote>Zitat</blockquote>');
    expect(renderMarkdown('a\nb')).toBe('<p>a<br>b</p>');
  });

  it('returns an empty string for empty input', () => {
    expect(renderMarkdown('')).toBe('');
  });

  it('renders ordered lists separately from unordered ones', () => {
    const out = renderMarkdown('1. eins\n2. zwei');
    expect(out).toContain('<ol>');
    expect((out.match(/<li>/g) ?? []).length).toBe(2);
  });

  it('renders a pipe table (as emitted by voteSnippet)', () => {
    const out = renderMarkdown('| Option | Stimmen |\n| --- | --- |\n| yes | 12 |');
    expect(out).toContain('<table>');
    expect(out).toContain('<th>Option</th>');
    expect(out).toContain('<td>yes</td>');
    expect(out).toContain('<td>12</td>');
  });

  it('renders safe links and drops dangerous schemes', () => {
    expect(renderMarkdown('[ok](https://x.test)')).toContain(
      '<a href="https://x.test" target="_blank" rel="noopener noreferrer">ok</a>',
    );
    const bad = renderMarkdown('[x](javascript:alert(1))');
    expect(bad).not.toContain('<a ');
    expect(bad).not.toContain('href');
  });

  it('rejects a link whose URL contains a double-quote (no attribute break-out, AUD-064)', () => {
    const out = renderMarkdown('[x](https://e"x=)');
    // The quote-bearing URL must not be turned into an href attribute …
    expect(out).not.toContain('<a ');
    expect(out).not.toContain('href');
    // … and no raw double-quote may leak into the rendered HTML.
    expect(out).not.toContain('"x=');
    expect(out).toContain('&quot;');
  });

  it('still renders a legitimate URL with an & query param without double-escaping', () => {
    expect(renderMarkdown('[ok](https://x.test?a=1&b=2)')).toContain(
      '<a href="https://x.test?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">ok</a>',
    );
  });

  it('renders a horizontal rule', () => {
    expect(renderMarkdown('---')).toContain('<hr>');
  });

  it('renders a GitHub callout from a [!NOTE] blockquote', () => {
    const out = renderMarkdown('> [!WARNING]\n> Achtung, Quorum knapp.');
    expect(out).toContain('class="callout callout--warning"');
    expect(out).toContain('<p class="callout__title">Warning</p>');
    expect(out).toContain('Achtung, Quorum knapp.');
  });

  it('keeps a plain blockquote when there is no callout marker', () => {
    expect(renderMarkdown('> Zitat')).toContain('<blockquote>Zitat</blockquote>');
  });

  it('treats a [!FOO] marker that is not a known callout as a plain blockquote', () => {
    const out = renderMarkdown('> [!FOO]\n> bar');
    expect(out).toContain('<blockquote>');
    expect(out).not.toContain('callout--foo');
  });

  it('renders a callout with body text on the marker line', () => {
    const out = renderMarkdown('> [!TIP] direkt hier');
    expect(out).toContain('class="callout callout--tip"');
    expect(out).toContain('direkt hier');
  });

  it('renders an empty callout when the marker has no body', () => {
    const out = renderMarkdown('> [!NOTE]');
    expect(out).toContain('class="callout callout--note"');
    expect(out).toContain('callout__title');
  });

  it('renders a multi-line blockquote joined by <br>', () => {
    const out = renderMarkdown('> eins\n> zwei');
    expect(out).toBe('<blockquote>eins<br>zwei</blockquote>');
  });

  it('stops collecting quote lines at the first non-quote line', () => {
    const out = renderMarkdown('> zitat\nnormaler Absatz');
    expect(out).toContain('<blockquote>zitat</blockquote>');
    expect(out).toContain('<p>normaler Absatz</p>');
  });

  it('renders an aligned pipe-table separator (:--:)', () => {
    const out = renderMarkdown('| a | b |\n| :--: | --- |\n| 1 | 2 |');
    expect(out).toContain('<table>');
    expect(out).toContain('<th>a</th>');
    expect(out).toContain('<td>1</td>');
  });

  it('renders a table with no body rows', () => {
    const out = renderMarkdown('| a | b |\n| --- | --- |');
    expect(out).toContain('<table>');
    expect(out).toContain('<tbody></tbody>');
  });

  it('normalises CRLF line endings', () => {
    expect(renderMarkdown('a\r\nb')).toBe('<p>a<br>b</p>');
  });

  it('handles a null/undefined input via the nullish guard', () => {
    expect(renderMarkdown(undefined as unknown as string)).toBe('');
  });

  it('closes an open list before a heading', () => {
    const out = renderMarkdown('- eins\n# Titel');
    expect(out).toContain('</ul>');
    expect(out).toContain('<h1>Titel</h1>');
  });

  it('switches from an unordered to an ordered list', () => {
    const out = renderMarkdown('- a\n1. b');
    expect((out.match(/<ul>/g) ?? []).length).toBe(1);
    expect((out.match(/<ol>/g) ?? []).length).toBe(1);
  });
});
