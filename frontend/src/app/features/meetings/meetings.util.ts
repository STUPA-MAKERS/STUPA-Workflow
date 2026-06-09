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
 * TOP-Snippet aus einem Tagesordnungspunkt: nummerierte TOP-Überschrift, bei
 * Antrags-TOPs zusätzlich die Antrags-Referenz (pytex-Shortcode). Freitext-TOPs
 * (``applicationId === null``) tragen nur die Überschrift (#58).
 */
export function topSnippet(
  position: number,
  title: string | null,
  applicationId: string | null,
): string {
  const heading = title?.trim() ? title.trim() : (applicationId ?? `TOP ${position}`);
  const ref = applicationId ? `\n:::antrag{#${applicationId}}\n:::\n` : '';
  return `\n## TOP ${position}: ${heading}\n${ref}`;
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

/** Nur Links mit sicherem Schema (kein `javascript:`-Vektor) durchlassen. */
function safeUrl(url: string): boolean {
  return /^(https?:\/\/|mailto:|\/)/i.test(url);
}

function inline(text: string): string {
  // Reihenfolge: Code zuerst (schützt Inhalt), dann Links, fett vor kursiv.
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label: string, url: string) =>
      safeUrl(url)
        ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : match,
    )
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

/** Zellen einer Pipe-Tabellen-Zeile (`| a | b |`) trimmen. */
function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());
}

/** Trenn-Zeile einer Pipe-Tabelle? (`| --- | :--: |`). */
function isTableSeparator(line: string): boolean {
  return /^\|?[\s:|-]+\|?$/.test(line.trim()) && line.includes('-') && line.includes('|');
}

// GitHub-Callout-Typen (`> [!NOTE]` …) → Titel + CSS-Modifier.
const CALLOUT_TITLES: Record<string, string> = {
  note: 'Note',
  tip: 'Tip',
  important: 'Important',
  warning: 'Warning',
  caution: 'Caution',
};

/**
 * Eine Gruppe zusammenhängender ``>``-Zeilen rendern: GitHub-Callout
 * (`> [!NOTE]`/`[!TIP]`/`[!IMPORTANT]`/`[!WARNING]`/`[!CAUTION]`) oder sonst ein
 * gewöhnliches Blockzitat. Inhalt wird zeilenweise inline-gerendert.
 */
function renderQuote(lines: string[]): string {
  const marker = /^\[!(\w+)\]\s*(.*)$/.exec(lines[0].trim());
  const kind = marker ? marker[1].toLowerCase() : '';
  if (marker && kind in CALLOUT_TITLES) {
    const first = marker[2].trim();
    const body = [...(first ? [first] : []), ...lines.slice(1)];
    const inner = body.length ? `<p>${body.map(inline).join('<br>')}</p>` : '';
    return (
      `<div class="callout callout--${kind}">` +
      `<p class="callout__title">${CALLOUT_TITLES[kind]}</p>${inner}</div>`
    );
  }
  return `<blockquote>${lines.map(inline).join('<br>')}</blockquote>`;
}

/**
 * Minimaler, abhängigkeitsfreier Markdown→HTML-Renderer für die Vorschau
 * (siehe Datei-Header). Unterstützt Überschriften, Fett/Kursiv/Code, **Links**,
 * geordnete + ungeordnete Listen, Zitate, **Pipe-Tabellen**, Trennlinien und
 * Absätze — genug für Sitzungsprotokolle (inkl. der `voteSnippet`-Ergebnistabellen).
 */
export function renderMarkdown(markdown: string): string {
  const lines = (markdown ?? '').replace(/\r\n/g, '\n').split('\n');
  const html: string[] = [];
  let list: 'ul' | 'ol' | null = null;
  let paragraph: string[] = [];

  const flushParagraph = (): void => {
    if (paragraph.length) {
      html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);
      paragraph = [];
    }
  };
  const closeList = (): void => {
    if (list) {
      html.push(`</${list}>`);
      list = null;
    }
  };
  const openList = (kind: 'ul' | 'ol'): void => {
    if (list !== kind) {
      closeList();
      html.push(`<${kind}>`);
      list = kind;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    const ordered = /^\d+\.\s+(.*)$/.exec(line);
    const unordered = /^[-*]\s+(.*)$/.exec(line);
    const quote = /^>\s?(.*)$/.exec(line);
    const isHr = /^([-*_])\1{2,}$/.test(line.trim());
    const isTableHead =
      line.trim().startsWith('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1]);

    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (isHr) {
      flushParagraph();
      closeList();
      html.push('<hr>');
    } else if (isTableHead) {
      flushParagraph();
      closeList();
      const head = tableCells(line);
      i += 2; // Kopf + Trenn-Zeile überspringen
      const body: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        body.push(tableCells(lines[i]));
        i++;
      }
      i--; // die for-Schleife inkrementiert gleich wieder
      const thead = `<thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead>`;
      const rows = body
        .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`)
        .join('');
      html.push(`<table>${thead}<tbody>${rows}</tbody></table>`);
    } else if (ordered) {
      flushParagraph();
      openList('ol');
      html.push(`<li>${inline(ordered[1])}</li>`);
    } else if (unordered) {
      flushParagraph();
      openList('ul');
      html.push(`<li>${inline(unordered[1])}</li>`);
    } else if (quote) {
      flushParagraph();
      closeList();
      // Zusammenhängende ``>``-Zeilen sammeln (für GitHub-Callouts + mehrzeilige Zitate).
      const quoteLines: string[] = [quote[1]];
      while (i + 1 < lines.length) {
        const m = /^>\s?(.*)$/.exec(lines[i + 1].trimEnd());
        if (!m) break;
        quoteLines.push(m[1]);
        i++;
      }
      html.push(renderQuote(quoteLines));
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
