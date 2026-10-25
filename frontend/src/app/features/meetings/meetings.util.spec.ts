import type { MeetingVote } from '@core/api/models';
import {
  escapeHtml,
  renderMarkdown,
  voteSnippet,
  voteSnippetHead,
  votesInText,
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

describe('voteSnippet', () => {
  /** The backend `build_vote_snippet` writes the identical block. */
  it('renders the protocol vote callout with the title and one tally line', () => {
    expect(voteSnippet(vote())).toBe(
      '> [!abstimmung] **Förderung Ersti-Wochenende**\n> yes: 12, no: 3, abstain: 1',
    );
  });

  it('carries no tally line without counts', () => {
    expect(voteSnippet(vote({ counts: null }))).toBe('> [!abstimmung] **Förderung Ersti-Wochenende**');
    expect(voteSnippet(vote({ counts: {} }))).not.toContain('\n');
  });

  it('prefers the question over the title', () => {
    const snip = voteSnippet(vote({ question: 'Soll X gefördert werden?' }));
    expect(snip.startsWith('> [!abstimmung] **Soll X gefördert werden?**')).toBe(true);
  });

  it('names the round in the head of a runoff', () => {
    const election = vote({ kind: 'election', question: 'Vorsitz', counts: null } as Partial<MeetingVote>);
    expect(voteSnippetHead(election)).toBe('> [!abstimmung] **Vorsitz**');
    expect(voteSnippetHead({ ...election, round: 2 } as MeetingVote)).toBe(
      '> [!abstimmung] **Vorsitz (2. Wahlgang)**',
    );
  });

  it('falls back to "Beschlussfrage" and keeps the marker on one line', () => {
    expect(voteSnippet(vote({ title: '  ', question: null }))).toContain('**Beschlussfrage**');
    expect(voteSnippetHead(vote({ question: 'Zeile 1\nZeile 2' }))).toBe(
      '> [!abstimmung] **Zeile 1 Zeile 2**',
    );
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
    expect(renderMarkdown('> Zitat')).toContain('<blockquote><p>Zitat</p></blockquote>');
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

  /**
   * A URL that carries a quote must never become an href attribute. The Markdown link stays text;
   * the autolink stops before the escaped quote, and no raw double-quote leaks into the rendered
   * HTML.
   */
  it('rejects a link whose URL contains a double-quote (no attribute break-out)', () => {
    const out = renderMarkdown('[x](https://e"x=)');
    expect(out).toContain('[x](');
    expect(out).not.toMatch(/href="[^"]*&quot;/);
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
    expect(renderMarkdown('> Zitat')).toContain('<blockquote><p>Zitat</p></blockquote>');
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

  it('renders a multi-line blockquote as one paragraph joined by <br>', () => {
    const out = renderMarkdown('> eins\n> zwei');
    expect(out).toBe('<blockquote><p>eins<br>zwei</p></blockquote>');
  });

  it('stops collecting quote lines at the first non-quote line', () => {
    const out = renderMarkdown('> zitat\nnormaler Absatz');
    expect(out).toContain('<blockquote><p>zitat</p></blockquote>');
    expect(out).toContain('<p>normaler Absatz</p>');
  });

  it('renders an aligned pipe-table separator (:--:)', () => {
    const out = renderMarkdown('| a | b |\n| :--: | --- |\n| 1 | 2 |');
    expect(out).toContain('<table>');
    expect(out).toContain('<th class="mdv__al--center">a</th>');
    expect(out).toContain('<td class="mdv__al--center">1</td>');
    expect(out).toContain('<th>b</th>');
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

  it('renders an image as its alt text only (anonymous contexts)', () => {
    const out = renderMarkdown('![Foto](/api/media/images/0b8f3c3e-4d6a-4f43-9a1e-2f0c1d2e3f40)');
    expect(out).toBe('<p>Foto</p>');
  });

  it('switches from an unordered to an ordered list', () => {
    const out = renderMarkdown('- a\n1. b');
    expect((out.match(/<ul>/g) ?? []).length).toBe(1);
    expect((out.match(/<ol>/g) ?? []).length).toBe(1);
  });
});

describe('votesInText', () => {
  const a = vote({ id: 'a', question: 'Bla', counts: { yes: 1, no: 0, abstain: 0 } });
  const b = vote({ id: 'b', question: 'Bla', counts: { yes: 2, no: 1, abstain: 0 } });

  it('gives a shared head line to the vote whose whole callout is in the text', () => {
    expect([...votesInText(`Text\n\n${voteSnippet(b)}`, [a, b])]).toEqual(['b']);
  });

  it('counts each head line for one vote only', () => {
    const edited = `${voteSnippetHead(a)}\n> geändert`;
    expect([...votesInText(edited, [a, b])]).toEqual(['a']);
    expect([...votesInText(`${edited}\n\n${edited}`, [a, b])].sort()).toEqual(['a', 'b']);
  });

  it('ignores a vote that is not closed', () => {
    const open = vote({ id: 'o', question: 'Bla', status: 'open' });
    expect(votesInText(voteSnippetHead(open), [open]).size).toBe(0);
  });
});
