/**
 * Wire shapes of the public protocol routes under `/api/public` (no login).
 *
 * Only FINAL protocols of a gremium with `protocolsPublic` appear, in their public
 * version: the public agenda items, the attendance as counts, never a name. A meeting is
 * never public on its own; its title and date appear only as part of a protocol.
 */

/** The result of one decision. */
/** A personnel election (F2) gives `elected`, `runoff`, `tie` or `rejected`. */
export type PublicVoteResult = 'passed' | 'rejected' | 'tie' | 'elected' | 'runoff';

/** A gremium that publishes its protocols (`GET /public/gremien`). */
export interface PublicGremium {
  id: string;
  name: string;
  slug: string;
  protocolCount: number;
}

/** The gremium of a protocol. */
export interface PublicGremiumRef {
  id: string;
  name: string;
  slug: string;
}

/** One agenda item in the list. A non-public item has no title. */
export interface PublicTopSummary {
  number: number;
  title: string | null;
  nonPublic: boolean;
  results: PublicVoteResult[];
}

/** One protocol in the list (`GET /public/protocols`). */
export interface PublicProtocolSummary {
  id: string;
  title: string;
  /** The meeting date, `YYYY-MM-DD`. */
  date: string;
  /** `ws-2026` (Wintersemester 2026/27) or `ss-2026` (Sommersemester 2026). */
  semester: string;
  finalizedAt: string | null;
  gremium: PublicGremiumRef;
  tops: PublicTopSummary[];
  hasPdf: boolean;
  /** The size of the public PDF in bytes. */
  pdfSize: number | null;
}

/** One decision of a public agenda item. */
export interface PublicDecision {
  question: string | null;
  /** The counts per option, for example `ja`/`nein`/`enthaltung` or `yes`/`no`/`abstain`. */
  counts: Record<string, number>;
  result: PublicVoteResult | null;
  majorityRule: 'simple' | 'absolute' | 'two_thirds';
  secret: boolean;
  /** The vote is already in the TOP text as a callout: the page shows no second box. */
  inText?: boolean;
  /** F1: the conditions of the decision of a passed vote. An older snapshot has none. */
  conditions?: string[];
  /** A personnel election (F2): only the names of the elected persons travel; the
   *  other candidates are a count, and an election has no counts. */
  kind?: 'motion' | 'election';
  seats?: number | null;
  round?: number;
  elected?: string[];
  otherCandidates?: number;
  byLot?: boolean;
}

/** One agenda item in the detail. A non-public item has no title, text or decision. */
export interface PublicTop extends PublicTopSummary {
  markdown: string | null;
  decisions: PublicDecision[];
}

/** The attendance as counts. The public version never names anybody. */
export interface PublicAttendance {
  present: number;
  excused: number;
  absent: number;
  guests: number;
}

/** One protocol (`GET /public/protocols/{id}`). */
export interface PublicProtocolDetail extends Omit<PublicProtocolSummary, 'tops'> {
  tops: PublicTop[];
  attendance: PublicAttendance;
  /** The free text of a meeting without agenda items (then `tops` is empty). */
  markdown: string | null;
}

/** One page of the list. */
export interface PublicProtocolPage {
  items: PublicProtocolSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** One semester with its number of protocols (`GET /public/protocols/semesters`). */
export interface PublicSemester {
  key: string;
  count: number;
}

/** The filters of the list. */
export interface PublicProtocolQuery {
  gremium?: readonly string[];
  semester?: string;
  q?: string;
  limit?: number;
  offset?: number;
}
