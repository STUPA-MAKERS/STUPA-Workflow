/**
 * Reine Helfer für den Protokoll-Editor (T-33) — DI-frei, isoliert testbar.
 *
 *  - **Snippet-Bausteine**: erzeugen Markdown-Referenzen auf Anträge/Abstimmungen,
 *    die der pytex-Renderer (T-20/T-21) als Shortcodes auflöst. Die `:::antrag` /
 *    `:::vote`-Fences sind bewusst leichtgewichtig und für Menschen lesbar (Risiko
 *    „Snippets ↔ pytex-Shortcodes", T-33).
 *  - **`renderMarkdown`**: minimaler, abhängigkeitsfreier Markdown→HTML-Renderer
 *    für die Live-Vorschau. Escapt **zuerst** alle HTML-Entities → kein Roh-HTML
 *    aus dem Editor gelangt in die Ausgabe; Angular sanitisiert das `innerHTML`
 *    zusätzlich. Unterstützt Überschriften, Fett/Kursiv, Inline-Code, Listen,
 *    Zitate und Absätze — genug für Sitzungsprotokolle.
 */

import type { MeetingVote } from '@core/api/models';

/** HTML-Entities escapen (XSS-Schutz: Editor-Eingabe ist nie vertrauenswürdig). */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Markdown-Snippet, das einen Antrag referenziert (pytex-Shortcode `:::antrag`). */
export function antragSnippet(applicationId: string, title: string | null): string {
  const heading = title?.trim() ? title.trim() : applicationId;
  return `\n:::antrag{#${applicationId}}\n### ${heading}\n:::\n`;
}

/**
 * Markdown-Snippet, das das Ergebnis einer Abstimmung einbettet. Enthält eine
 * lesbare Ergebnistabelle (Option → Stimmen) **und** den `:::vote`-Shortcode, an
 * den pytex die kanonische Auswertung hängt.
 */
export function voteSnippet(vote: MeetingVote): string {
  const lines: string[] = [`\n:::vote{#${vote.id}}`];
  const heading = vote.title?.trim() ? vote.title.trim() : vote.applicationId;
  lines.push(`### ${heading}`);
  if (vote.counts && Object.keys(vote.counts).length > 0) {
    lines.push('', '| Option | Stimmen |', '| --- | --- |');
    for (const [option, count] of Object.entries(vote.counts)) {
      lines.push(`| ${option} | ${count} |`);
    }
  }
  if (vote.result) lines.push('', `**Ergebnis:** ${vote.result}`);
  lines.push(':::', '');
  return `\n${lines.join('\n')}`;
}

/** Markdown an der Cursor-Position (oder am Ende) in den Text einfügen. */
export function insertAt(text: string, snippet: string, caret: number | null): string {
  if (caret === null || caret < 0 || caret > text.length) return text + snippet;
  return text.slice(0, caret) + snippet + text.slice(caret);
}

function inline(text: string): string {
  // Reihenfolge: Code zuerst (schützt Inhalt), dann fett vor kursiv.
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

/** Minimaler Markdown→HTML-Renderer für die Vorschau (siehe Datei-Header). */
export function renderMarkdown(markdown: string): string {
  const lines = (markdown ?? '').replace(/\r\n/g, '\n').split('\n');
  const html: string[] = [];
  let listOpen = false;
  let paragraph: string[] = [];

  const flushParagraph = (): void => {
    if (paragraph.length) {
      html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);
      paragraph = [];
    }
  };
  const closeList = (): void => {
    if (listOpen) {
      html.push('</ul>');
      listOpen = false;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    const listItem = /^[-*]\s+(.*)$/.exec(line);
    const quote = /^>\s?(.*)$/.exec(line);

    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (listItem) {
      flushParagraph();
      if (!listOpen) {
        html.push('<ul>');
        listOpen = true;
      }
      html.push(`<li>${inline(listItem[1])}</li>`);
    } else if (quote) {
      flushParagraph();
      closeList();
      html.push(`<blockquote>${inline(quote[1])}</blockquote>`);
    } else if (line.trim() === '') {
      flushParagraph();
      closeList();
    } else {
      closeList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  closeList();
  return html.join('\n');
}
