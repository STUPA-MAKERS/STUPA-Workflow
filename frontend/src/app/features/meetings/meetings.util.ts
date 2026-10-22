/**
 * Pure, DI-free helpers for the protocol editor.
 *
 *  - Snippet builders produce the markdown blocks for applications and votes. A
 *    vote is the protocol callout `> [!abstimmung]`, the same block the
 *    backend writes.
 *  - `renderMarkdown` wraps the shared renderer (`@shared/markdown/markdown.util`)
 *    for the live preview. It escapes ALL HTML entities FIRST, so no raw HTML from
 *    the editor reaches the output. Angular also sanitizes the `innerHTML`.
 */

import type { MeetingVote, PollConfig, PollOption } from '@core/api/models';
import { escapeHtml, markdownToSafeHtml } from '@shared/markdown/markdown.util';

export { escapeHtml };

/**
 * First line of the vote callout: the marker and the bold question. The backend
 * writes the same line in `build_vote_snippet`, so a body that contains it already
 * carries the vote.
 */
export function voteSnippetHead(vote: MeetingVote): string {
  return `> [!abstimmung] **${voteSnippetQuestion(vote).replace(/\r\n|\r|\n/g, ' ')}**`;
}

/**
 * The ids of the closed votes whose callout is in `body`. Two votes can share a
 * question, and then they share the head line, so a head line counts for one vote only.
 * A callout whose whole text equals the snippet of a vote belongs to that vote first.
 * The other head lines go to the remaining votes in the given order (oldest first). The
 * backend matches the same way in `votes_in_body`.
 */
export function votesInText(body: string, votes: readonly MeetingVote[]): Set<string> {
  const closed = votes.filter((v) => v.status === 'closed');
  const heads = new Map<string, number>();
  for (const line of body.split('\n')) {
    const key = line.trim();
    heads.set(key, (heads.get(key) ?? 0) + 1);
  }
  const exact = new Map<string, number>();
  const found = new Set<string>();
  const take = (vote: MeetingVote): void => {
    const head = voteSnippetHead(vote);
    heads.set(head, (heads.get(head) ?? 0) - 1);
    found.add(vote.id);
  };
  for (const vote of closed) {
    const snippet = voteSnippet(vote);
    if (!exact.has(snippet)) exact.set(snippet, countOf(body, snippet));
    const left = exact.get(snippet) ?? 0;
    if (left > 0 && (heads.get(voteSnippetHead(vote)) ?? 0) > 0) {
      exact.set(snippet, left - 1);
      take(vote);
    }
  }
  for (const vote of closed) {
    if (!found.has(vote.id) && (heads.get(voteSnippetHead(vote)) ?? 0) > 0) take(vote);
  }
  return found;
}

function countOf(text: string, part: string): number {
  let n = 0;
  for (let i = text.indexOf(part); i >= 0; i = text.indexOf(part, i + part.length)) n++;
  return n;
}

/**
 * The question in the head line of the callout. A runoff (F2) copies the question of its
 * election, so its head names the round: "Frage (2. Wahlgang)". Each round then has its
 * own head line, as in the backend `build_election_snippet`.
 */
export function voteSnippetQuestion(vote: MeetingVote): string {
  if (vote.kind === 'poll') return vote.question?.trim() || 'Umfrage';
  if (vote.kind === 'election') {
    const head = vote.question?.trim() || 'Wahlgang';
    const round = vote.round ?? 1;
    return round > 1 ? `${head} (${round}. Wahlgang)` : head;
  }
  return vote.question?.trim() || vote.title?.trim() || 'Beschlussfrage';
}

/**
 * Markdown snippet that embeds a vote result as the protocol callout: a
 * `> [!abstimmung]` quote with the bold question and one tally line. The renderer reads
 * the counts from that line and renders its tally box. The backend writes the
 * identical snippet, so one syntax serves the editor, the PDF and the mail.
 */
export function voteSnippet(vote: MeetingVote): string {
  if (vote.kind === 'election' && vote.election) return electionSnippet(vote);
  if (vote.kind === 'poll' && vote.poll) return pollSnippet(vote, vote.poll);
  const lines = [voteSnippetHead(vote)];
  const counts = Object.entries(vote.counts ?? {});
  if (counts.length) {
    lines.push(`> ${counts.map(([option, n]) => `${option}: ${n}`).join(', ')}`);
  }
  return lines.join('\n');
}

/**
 * The protocol callout of a personnel election (F2), the same text as the backend
 * `build_election_snippet` writes: "Wahl · 2 Posten", the votes per candidate (best
 * first) and the abstentions, "Gewählt: …" and the notes of the lot and the runoff. A
 * single candidate writes its Ja/Nein/Enthaltung line.
 */
export function electionSnippet(vote: MeetingVote): string {
  const election = vote.election;
  const result = vote.electionResult ?? null;
  const round = vote.round ?? 1;
  const lines = [voteSnippetHead(vote)];
  let meta = `Wahl · ${election?.seats ?? 1} Posten`;
  if (round > 1) meta += ` · Stichwahl (${round}. Wahlgang)`;
  lines.push(`> ${meta}`);
  if (!election || !result) return lines.join('\n');
  const names = new Map(election.candidates.map((c) => [c.id, c.name]));
  const yesNo = typeof result.yes === 'number' && typeof result.no === 'number';
  // Best first, as the backend writes them; the single candidate keeps its place.
  const rows = election.candidates.map((c) => ({
    name: c.name,
    votes: result.counts[c.id] ?? 0,
    elected: result.elected.includes(c.id),
  }));
  if (!yesNo) rows.sort((a, b) => b.votes - a.votes);
  if (yesNo) {
    lines.push(`> Kandidatur: ${election.candidates[0]?.name ?? ''}`);
    lines.push(`> ja: ${result.yes}, nein: ${result.no}, enthaltung: ${result.abstentions}`);
  } else {
    const votes = rows.map((r) => `${r.name}: ${r.votes}`).join(' · ');
    lines.push(`> ${votes} · Enthaltungen: ${result.abstentions}`);
  }
  const elected = rows.filter((r) => r.elected).map((r) => r.name);
  lines.push(`> Gewählt: ${elected.length ? elected.join(', ') : 'niemand'}`);
  if (result.lot?.drawn) lines.push('> Durch Los entschieden.');
  if (result.lot && !result.lot.drawn) lines.push('> Gleichstand: das Los steht aus.');
  if (result.runoff?.seats) {
    const who = result.runoff.candidateIds.map((id) => names.get(id) ?? id).join(', ');
    lines.push(`> Stichwahl (${round + 1}. Wahlgang) um ${result.runoff.seats} Posten: ${who}`);
  }
  return lines.join('\n');
}

/**
 * The protocol callout of a poll, the same text as the backend `build_poll_snippet`
 * writes: the kind line ("Umfrage · Einzelwahl", "Terminumfrage") and, once closed, one
 * line per option (highest first; a date poll "3 (+2)" = Ja and Vielleicht), the
 * abstentions, the options with the most votes and the number of answers. A poll lists
 * counts only, never a name.
 */
export function pollSnippet(vote: MeetingVote, poll: PollConfig): string {
  const lines = [voteSnippetHead(vote), `> ${pollMeta(poll)}`];
  const result = vote.pollResult;
  if (!result) return lines.join('\n');
  const date = poll.mode === 'date';
  const labels = new Map(poll.options.map((o) => [o.id, pollSnippetLabel(o)]));
  const known = result.order.filter((id) => labels.has(id));
  const order = known.length ? known : [...labels.keys()];
  const top = new Set(result.top);
  for (const id of order) {
    const count = result.counts[id] ?? 0;
    const text = date ? `${count} (+${result.maybe?.[id] ?? 0})` : `${count}`;
    lines.push(`> ${oneLine(labels.get(id) ?? id)}: ${text}`);
  }
  if (!date) lines.push(`> Enthaltungen: ${result.abstentions}`);
  else lines.push('> Zahl = Ja, (+n) = Vielleicht');
  const best = order.filter((id) => top.has(id)).map((id) => oneLine(labels.get(id) ?? id));
  if (best.length) lines.push(`> ${date ? 'Bester Termin' : 'Meiste Stimmen'}: ${best.join(', ')}`);
  lines.push(`> ${result.ballots} Antworten · Meinungsbild, kein Beschluss`);
  return lines.join('\n');
}

/** The kind line of a poll callout, as the backend `poll_meta` writes it. */
function pollMeta(poll: PollConfig): string {
  if (poll.mode === 'date') return 'Terminumfrage';
  if (poll.mode === 'single') return 'Umfrage · Einzelwahl';
  return poll.maxChoices != null
    ? `Umfrage · Mehrfachwahl, höchstens ${poll.maxChoices}`
    : 'Umfrage · Mehrfachwahl';
}

const SNIPPET_TZ = 'Europe/Berlin';
const WEEKDAYS = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];

/** "Di, 3.11. · 18:00–20:00" in the time zone of the protocol, as the backend writes it. */
function pollSnippetLabel(option: PollOption): string {
  if (!option.start) return option.label ?? option.id;
  const part = (iso: string): Record<string, string> =>
    Object.fromEntries(
      new Intl.DateTimeFormat('en-GB', {
        timeZone: SNIPPET_TZ,
        weekday: 'short',
        day: 'numeric',
        month: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      })
        .formatToParts(new Date(iso))
        .map((p) => [p.type, p.value]),
    );
  const s = part(option.start);
  const day = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(s['weekday'] ?? '');
  let text = `${WEEKDAYS[day] ?? ''}, ${Number(s['day'])}.${Number(s['month'])}. · ${s['hour']}:${s['minute']}`;
  if (option.end) {
    const e = part(option.end);
    text += `–${e['hour']}:${e['minute']}`;
  }
  return text;
}

function oneLine(text: string): string {
  return text.replace(/\r\n|\r|\n/g, ' ');
}

/**
 * The Markdown→HTML renderer of the protocol preview, the apply wizard and the branding
 * preview: the shared renderer with full-size headings and no images. These contexts
 * can be anonymous, so an image renders as its alt text. The `:::antrag` fences stay as
 * text.
 */
export function renderMarkdown(markdown: string): string {
  return markdownToSafeHtml(markdown ?? '', { headingOffset: 0, imageSrc: null });
}
