import type { MeetingVote } from '@core/api/models';
import {
  antragSnippet,
  escapeHtml,
  insertAt,
  renderMarkdown,
  voteSnippet,
} from './meetings.util';

function vote(overrides: Partial<MeetingVote> = {}): MeetingVote {
  return {
    id: 'v-1',
    applicationId: 'app-1',
    title: 'Förderung Ersti-Wochenende',
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
});
