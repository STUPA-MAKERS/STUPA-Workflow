import type {
  ElectionConfig,
  ElectionFields,
  ElectionResult,
  VoteKind,
  VoteResult,
} from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';
import { voteResultStatus, type StatusView } from '@shared/status-kind.util';

/** The translate function of the I18nService. */
type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

/** The abstention option of a single-seat election ballot. */
export const ELECTION_ABSTAIN = 'abstain';

/**
 * The election of a vote (F2), or `null` for a motion. A single candidate gives a
 * Ja/Nein/Enthaltung ballot, so the caller checks `isYesNoElection` too.
 */
export function electionOf(vote: ElectionFields | null | undefined): ElectionConfig | null {
  if (!vote || vote.kind !== 'election') return null;
  return vote.election ?? null;
}

/** One candidate for one seat: the ballot is Ja/Nein/Enthaltung. */
export function isYesNoElection(election: ElectionConfig | null): boolean {
  return !!election && election.candidates.length === 1;
}

/** The name of a candidate id, or the id when the config does not know it. */
export function candidateName(election: ElectionConfig | null, id: string): string {
  return election?.candidates.find((c) => c.id === id)?.name ?? id;
}

/** The names of candidate ids, in the given order. */
export function candidateNames(election: ElectionConfig | null, ids: readonly string[]): string[] {
  return ids.map((id) => candidateName(election, id));
}

/**
 * The label of an election ballot: "Anna, Ben", "Anna · 1 Enthaltung" or "Enthaltung"
 * (a full abstention).
 */
export function electionChoiceLabel(
  election: ElectionConfig | null,
  picks: readonly string[],
  t: Translate,
): string {
  if (picks.length === 0) return t('vote.option.abstain');
  const names = candidateNames(election, picks).join(', ');
  const free = (election?.seats ?? 1) - picks.length;
  return free > 0 ? `${names} · ${abstentionsText(free, t)}` : names;
}

/** "1 Enthaltung", "2 Enthaltungen". */
export function abstentionsText(n: number, t: Translate): string {
  return n === 1 ? t('election.abstentions.one') : t('election.abstentions.other', { n });
}

/** "1 Name", "2 Namen". */
export function namesText(n: number, t: Translate): string {
  return n === 1 ? t('election.names.one') : t('election.names.other', { n });
}

/**
 * The counter of a multi-seat ballot: "2 Namen, 1 Enthaltung", "3 Namen" or
 * "3 Enthaltungen" (a full abstention). It stays short, so the confirm button of a
 * phone shows it whole; the list above shows the names.
 */
export function electionCountText(
  election: ElectionConfig | null,
  picks: readonly string[],
  t: Translate,
): string {
  const free = (election?.seats ?? 1) - picks.length;
  const parts: string[] = [];
  if (picks.length > 0) parts.push(namesText(picks.length, t));
  if (free > 0) parts.push(abstentionsText(free, t));
  return parts.join(', ');
}

/** "1 Posten", "2 Posten". */
export function seatsText(n: number, t: Translate): string {
  return n === 1 ? t('election.seats.one') : t('election.seats.other', { n });
}

/** One bar of an election result. */
export interface ElectionBar {
  id: string;
  label: string;
  count: number;
  elected: boolean;
  /** In the tie at the seat boundary: a runoff or the lot decides. */
  tied: boolean;
}

/**
 * The bars of an election result, by votes (best first), then the abstentions. A
 * single candidate gives Ja, Nein and Enthaltung.
 */
export function electionBars(
  election: ElectionConfig | null,
  result: ElectionResult | null,
  counts: Readonly<Record<string, number>>,
  t: Translate,
): ElectionBar[] {
  if (!election) return [];
  const elected = new Set(result?.elected ?? []);
  const tied = new Set([...(result?.runoff?.candidateIds ?? []), ...pendingLot(result)]);
  if (isYesNoElection(election)) {
    return (['yes', 'no', ELECTION_ABSTAIN] as const).map((key) => ({
      id: key,
      label: t(`vote.option.${key}`),
      count: counts[key] ?? (key === ELECTION_ABSTAIN ? (result?.abstentions ?? 0) : 0),
      elected: false,
      tied: false,
    }));
  }
  const rows = election.candidates.map((c) => ({
    id: c.id,
    label: c.name,
    count: result?.counts[c.id] ?? counts[c.id] ?? 0,
    elected: elected.has(c.id),
    tied: tied.has(c.id),
  }));
  rows.sort((a, b) => b.count - a.count);
  const abstain = result?.abstentions ?? counts[ELECTION_ABSTAIN] ?? 0;
  return [
    ...rows,
    {
      id: ELECTION_ABSTAIN,
      label: t('election.abstentionsLabel'),
      count: abstain,
      elected: false,
      tied: false,
    },
  ];
}

/** The candidates of a lot that is still pending, else none. */
function pendingLot(result: ElectionResult | null): string[] {
  const lot = result?.lot;
  return lot && !lot.drawn ? lot.among : [];
}

/** A lot is pending: the result is a tie and nobody drew it yet. */
export function lotPending(result: VoteResult | string | null, er: ElectionResult | null): boolean {
  return result === 'tie' && !!er?.lot && !er.lot.drawn;
}

/** A runoff is pending and does not exist yet. */
export function runoffPending(
  result: VoteResult | string | null,
  er: ElectionResult | null,
): boolean {
  return result === 'runoff' && !!er?.runoff && !er.runoff.voteId;
}

/** The result line of a closed election: "Gewählt: Anna, Ben", "Niemand gewählt" and so on. */
export function electionResultLine(
  election: ElectionConfig | null,
  result: VoteResult | string | null,
  er: ElectionResult | null,
  t: Translate,
): string {
  const elected = candidateNames(election, er?.elected ?? []);
  if (result === 'tie') return t('election.result.tie');
  if (result === 'rejected' || elected.length === 0) return t('election.result.nobody');
  return t('election.result.elected', { names: elected.join(', ') });
}

/** "Wahl · 2 Posten" or "Stichwahl (2. Wahlgang) · 1 Posten". */
export function electionCaption(
  election: ElectionConfig | null,
  round: number | undefined,
  t: Translate,
): string {
  const seats = election?.seats ?? 1;
  const head = (round ?? 1) > 1 ? t('election.runoffRound', { n: round ?? 2 }) : t('election.kind');
  return `${head} · ${seatsText(seats, t)}`;
}

/** The status of a closed election: "Gewählt", "Stichwahl", "Los steht aus", "Niemand gewählt". */
/**
 * The status of a closed vote in a list row: an election (F2) reads its result with
 * `electionStatus` ("Gewählt", "Stichwahl", "Los"), a motion with `voteResultStatus`.
 */
export function closedStatus(kind: VoteKind | null | undefined, result: VoteResult): StatusView {
  return kind === 'election' ? electionStatus(result) : voteResultStatus(result);
}

export function electionStatus(result: VoteResult | string | null): StatusView {
  if (result === 'elected') return { kind: 'accent', key: 'election.status.elected' };
  if (result === 'runoff') return { kind: 'warn', key: 'election.status.runoff' };
  if (result === 'tie') return { kind: 'warn', key: 'election.status.tie' };
  return { kind: 'error', key: 'election.status.rejected' };
}
