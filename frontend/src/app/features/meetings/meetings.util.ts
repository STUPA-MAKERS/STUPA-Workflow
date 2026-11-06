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
import { withEntry } from '@shared/util/immutable';
import { dateOptionLabel } from '../voting/poll.util';

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
export function votesInText(body: string, votes: readonly MeetingVote[]): ReadonlySet<string> {
  const closed = votes.filter((v) => v.status === 'closed');
  const lines = body.split('\n').map((line) => line.trim());
  const heads: ReadonlyMap<string, number> = new Map(
    closed.map((v) => voteSnippetHead(v)).map((head) => [head, countLines(lines, head)]),
  );
  const start: HeadMatch = { heads, exact: new Map(), found: new Set() };
  const byText = closed.reduce((state, vote) => matchExact(state, vote, body), start);
  const byHead = closed.reduce(
    (state, vote) =>
      !state.found.has(vote.id) && headsLeft(state, vote) > 0 ? takeVote(state, vote) : state,
    byText,
  );
  return byHead.found;
}

/** The state of `votesInText`: the head lines left, the exact snippets left, the votes found. */
interface HeadMatch {
  readonly heads: ReadonlyMap<string, number>;
  readonly exact: ReadonlyMap<string, number>;
  readonly found: ReadonlySet<string>;
}

function countLines(lines: readonly string[], line: string): number {
  return lines.filter((l) => l === line).length;
}

function headsLeft(state: HeadMatch, vote: MeetingVote): number {
  return state.heads.get(voteSnippetHead(vote)) ?? 0;
}

/** Gives `vote` one of the head lines left. */
function takeVote(state: HeadMatch, vote: MeetingVote): HeadMatch {
  const head = voteSnippetHead(vote);
  return {
    ...state,
    heads: withEntry(state.heads, head, (state.heads.get(head) ?? 0) - 1),
    found: new Set([...state.found, vote.id]),
  };
}

/** Gives `vote` its head line when a callout with the whole text of its snippet is left. */
function matchExact(state: HeadMatch, vote: MeetingVote, body: string): HeadMatch {
  const snippet = voteSnippet(vote);
  const exact = state.exact.has(snippet)
    ? state.exact
    : withEntry(state.exact, snippet, countOf(body, snippet));
  const left = exact.get(snippet) ?? 0;
  return left > 0 && headsLeft(state, vote) > 0
    ? takeVote({ ...state, exact: withEntry(exact, snippet, left - 1) }, vote)
    : { ...state, exact };
}

function countOf(text: string, part: string): number {
  return text.split(part).length - 1;
}

/**
 * The question in the head line of the callout. A runoff copies the question of its
 * election, so its head names the round: "Frage (2. Wahlgang)". A repeat ("Erneut
 * abstimmen") copies the question of the vote it repeats, so its head names the attempt:
 * "Frage (2. Abstimmung)", for an election the next round. Each round and each attempt
 * then has its own head line, as in the backend `build_election_snippet` and `_snippet`.
 */
export function voteSnippetQuestion(vote: MeetingVote): string {
  const attempt = vote.attempt ?? 1;
  const again = (head: string): string => (attempt > 1 ? `${head} (${attempt}. Abstimmung)` : head);
  if (vote.kind === 'poll') return again(vote.question?.trim() || 'Umfrage');
  if (vote.kind === 'election') {
    const head = vote.question?.trim() || 'Wahlgang';
    const round = (vote.round ?? 1) + attempt - 1;
    return round > 1 ? `${head} (${round}. Wahlgang)` : head;
  }
  return again(vote.question?.trim() || vote.title?.trim() || 'Beschlussfrage');
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
  const counts = Object.entries(vote.counts ?? {});
  const tally = counts.length
    ? [`> ${counts.map(([option, n]) => `${option}: ${n}`).join(', ')}`]
    : [];
  return [voteSnippetHead(vote), ...tally].join('\n');
}

/**
 * The protocol callout of a personnel election, the same text as the backend
 * `build_election_snippet` writes: "Wahl · 2 Posten", the votes per candidate (best
 * first) and the abstentions, "Gewählt: …" and the notes of the lot and the runoff. A
 * single candidate writes its Ja/Nein/Enthaltung line.
 */
export function electionSnippet(vote: MeetingVote): string {
  const election = vote.election;
  const result = vote.electionResult ?? null;
  const round = vote.round ?? 1;
  const lines = [voteSnippetHead(vote), `> ${electionMeta(vote)}`];
  if (!election || !result) return lines.join('\n');
  const names = new Map(election.candidates.map((c) => [c.id, c.name]));
  const yesNo = typeof result.yes === 'number' && typeof result.no === 'number';
  const unsorted = election.candidates.map((c) => ({
    name: c.name,
    votes: result.counts[c.id] ?? 0,
    elected: result.elected.includes(c.id),
  }));
  const rows = yesNo ? unsorted : [...unsorted].sort((a, b) => b.votes - a.votes);
  const tally = yesNo
    ? [
        `> Kandidatur: ${election.candidates[0]?.name ?? ''}`,
        `> ja: ${result.yes}, nein: ${result.no}, enthaltung: ${result.abstentions}`,
      ]
    : [
        `> ${rows.map((r) => `${r.name}: ${r.votes}`).join(' · ')} · Enthaltungen: ${result.abstentions}`,
      ];
  const elected = rows.filter((r) => r.elected).map((r) => r.name);
  const lot = result.lot
    ? [result.lot.drawn ? '> Durch Los entschieden.' : '> Gleichstand: das Los steht aus.']
    : [];
  const runoff = result.runoff?.seats
    ? [
        `> Stichwahl (${round + 1}. Wahlgang) um ${result.runoff.seats} Posten: ${result.runoff.candidateIds
          .map((id) => names.get(id) ?? id)
          .join(', ')}`,
      ]
    : [];
  return [
    ...lines,
    ...tally,
    `> Gewählt: ${elected.length ? elected.join(', ') : 'niemand'}`,
    ...lot,
    ...runoff,
  ].join('\n');
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
  const rows = order.map((id) => {
    const count = result.counts[id] ?? 0;
    const text = date ? `${count} (+${result.maybe?.[id] ?? 0})` : `${count}`;
    return `> ${oneLine(labels.get(id) ?? id)}: ${text}`;
  });
  const legend = date ? '> Zahl = Ja, (+n) = Vielleicht' : `> Enthaltungen: ${result.abstentions}`;
  const best = order.filter((id) => top.has(id)).map((id) => oneLine(labels.get(id) ?? id));
  const bestLine = best.length
    ? [`> ${date ? 'Bester Termin' : 'Meiste Stimmen'}: ${best.join(', ')}`]
    : [];
  const answers = `> ${result.ballots} ${result.ballots === 1 ? 'Antwort' : 'Antworten'}`;
  return [...lines, ...rows, legend, ...bestLine, answers].join('\n');
}

/** The kind line of an election callout: "Wahl · 2 Posten", a runoff names its round. */
export function electionMeta(vote: MeetingVote): string {
  const round = vote.round ?? 1;
  const meta = `Wahl · ${vote.election?.seats ?? 1} Posten`;
  return round > 1 ? `${meta} · Stichwahl (${round}. Wahlgang)` : meta;
}

/** The kind line of a poll callout, as the backend `poll_meta` writes it. */
export function pollMeta(poll: PollConfig): string {
  if (poll.mode === 'date') return 'Terminumfrage';
  if (poll.mode === 'single') return 'Umfrage · Einzelwahl';
  return poll.maxChoices != null
    ? `Umfrage · Mehrfachwahl, höchstens ${poll.maxChoices}`
    : 'Umfrage · Mehrfachwahl';
}

/** "Di, 3.11. · 18:00–20:00" in the time zone of the protocol, as the backend writes it. */
function pollSnippetLabel(option: PollOption): string {
  if (!option.start) return option.label ?? option.id;
  return dateOptionLabel(option.start, option.end, 'de');
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
