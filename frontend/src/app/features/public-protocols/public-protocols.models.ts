/**
 * Wire shapes of the public protocol routes under `/api/public` (no login).
 *
 * Only FINAL protocols of a gremium with `protocolsPublic` appear, in their public
 * version: the public agenda items, the attendance as counts, never a name. A meeting is
 * never public on its own; its title and date appear only as part of a protocol.
 */

/** The result of one decision. */
/** A personnel election gives `elected`, `runoff`, `tie` or `rejected`. */
export type PublicVoteResult = 'passed' | 'rejected' | 'tie' | 'elected' | 'runoff';

/** A gremium that publishes its protocols (`GET /public/gremien`). */
export interface PublicGremium {
  readonly id: string;
  readonly name: string;
  readonly slug: string;
  readonly protocolCount: number;
}

/** The gremium of a protocol. */
export interface PublicGremiumRef {
  readonly id: string;
  readonly name: string;
  readonly slug: string;
}

/** One agenda item in the list. A non-public item has no title. */
export interface PublicTopSummary {
  readonly number: number;
  readonly title: string | null;
  readonly nonPublic: boolean;
  readonly results: readonly PublicVoteResult[];
}

/** One protocol in the list (`GET /public/protocols`). */
export interface PublicProtocolSummary {
  readonly id: string;
  readonly title: string;
  /** The meeting date, `YYYY-MM-DD`. */
  readonly date: string;
  /** `ws-2026` (Wintersemester 2026/27) or `ss-2026` (Sommersemester 2026). */
  readonly semester: string;
  readonly finalizedAt: string | null;
  readonly gremium: PublicGremiumRef;
  readonly tops: readonly PublicTopSummary[];
  readonly hasPdf: boolean;
  /** The size of the public PDF in bytes. */
  readonly pdfSize: number | null;
}

/** One decision of a public agenda item. */
export interface PublicDecision {
  readonly question: string | null;
  /** The counts per option, for example `ja`/`nein`/`enthaltung` or `yes`/`no`/`abstain`. */
  readonly counts: Record<string, number>;
  readonly result: PublicVoteResult | null;
  readonly majorityRule: 'simple' | 'absolute' | 'two_thirds';
  readonly secret: boolean;
  /** The vote is already in the TOP text as a callout: the page shows no second box. */
  readonly inText?: boolean;
  /** The conditions of the decision of a passed vote. An older snapshot has none. */
  readonly conditions?: readonly string[];
  /** A personnel election: only the names of the elected persons travel; the
   *  other candidates are a count, and an election has no counts. */
  readonly kind?: 'motion' | 'election';
  readonly seats?: number | null;
  readonly round?: number;
  readonly elected?: readonly string[];
  readonly otherCandidates?: number;
  readonly byLot?: boolean;
}

/** One agenda item in the detail. A non-public item has no title, text or decision. */
export interface PublicTop extends PublicTopSummary {
  readonly markdown: string | null;
  readonly decisions: readonly PublicDecision[];
}

/** The attendance as counts. The public version never names anybody. */
export interface PublicAttendance {
  readonly present: number;
  readonly excused: number;
  readonly absent: number;
  readonly guests: number;
}

/** One protocol (`GET /public/protocols/{id}`). */
export interface PublicProtocolDetail extends Omit<PublicProtocolSummary, 'tops'> {
  readonly tops: readonly PublicTop[];
  readonly attendance: PublicAttendance;
  /** The content language of the protocol text: the default language of the gremium. */
  readonly lang?: string;
  /** The free text of a meeting without agenda items (then `tops` is empty). */
  readonly markdown: string | null;
}

/** One page of the list. */
export interface PublicProtocolPage {
  readonly items: readonly PublicProtocolSummary[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

/** One semester with its number of protocols (`GET /public/protocols/semesters`). */
export interface PublicSemester {
  readonly key: string;
  readonly count: number;
}

/** The filters of the list. */
export interface PublicProtocolQuery {
  readonly gremium?: readonly string[];
  readonly semester?: string;
  readonly q?: string;
  readonly limit?: number;
  readonly offset?: number;
}
