/**
 * Wire → View Mapper (T-40, Issue #17).
 *
 * Reine Funktionen, die das Backend-JSON (`*Wire`, camelCase via T-12
 * `_CamelModel`) in die FE-View-Modelle übersetzen: i18n-Labels werden für die
 * angeforderte Sprache aufgelöst, Komfort-Felder (`isPublic`) abgeleitet und
 * optionale Felder auf einen festen `null`-Default normalisiert.
 *
 * Bewusst DI-frei (kein Angular) → in `mappers.spec.ts` isoliert testbar; die
 * `lang` wird vom `ApiClient` (über `I18nService`) durchgereicht.
 */

import { resolveI18n } from '@shared/forms/i18n-text';
import type {
  Applicant,
  ApplicantOutWire,
  Application,
  BudgetPotInfo,
  BudgetPotOutWire,
  BudgetStats,
  BudgetStatsOutWire,
  PotUsage,
  PotUsageOutWire,
  StatusBucket,
  StatusBucketOutWire,
  Uuid,
  ApplicationCreateBody,
  ApplicationCreated,
  ApplicationCreatedWire,
  ApplicationListItem,
  ApplicationListItemWire,
  ApplicationOutWire,
  ApplicationState,
  ApplicationType,
  ApplicationTypeListItemWire,
  ApplicationVersion,
  Attachment,
  AttachmentOutWire,
  CommentOutWire,
  ApplicationComment,
  DataDiff,
  DataDiffWire,
  Meeting,
  MeetingOutWire,
  MeetingVote,
  MeetingVoteOutWire,
  NewApplication,
  Protocol,
  ProtocolOutWire,
  SignedUrl,
  SignedUrlOutWire,
  StateOutWire,
  TimelineEntry,
  TimelineEventOutWire,
  Transition,
  TransitionOutWire,
  VersionOutWire,
} from './models';

export function mapState(
  wire: StateOutWire | null | undefined,
  lang: string,
): ApplicationState | null {
  if (!wire) return null;
  return {
    id: wire.id,
    key: wire.key,
    label: resolveI18n(wire.label, lang),
    category: wire.category,
    editAllowed: wire.editAllowed,
  };
}

function mapApplicant(wire: ApplicantOutWire | null | undefined): Applicant | null {
  if (!wire) return null;
  return {
    email: wire.email ?? null,
    name: wire.name ?? null,
    anonymized: wire.anonymized ?? false,
  };
}

export function mapApplication(wire: ApplicationOutWire, lang: string): Application {
  return {
    id: wire.id,
    typeId: wire.typeId,
    state: mapState(wire.state, lang),
    gremiumId: wire.gremiumId ?? null,
    budgetPotId: wire.budgetPotId ?? null,
    amount: wire.amount ?? null,
    currency: wire.currency ?? null,
    data: wire.data ?? {},
    version: wire.version,
    lang: wire.lang ?? null,
    createdAt: wire.createdAt,
    updatedAt: wire.updatedAt,
    applicant: mapApplicant(wire.applicant),
  };
}

export function mapApplicationListItem(
  wire: ApplicationListItemWire,
  lang: string,
): ApplicationListItem {
  return {
    id: wire.id,
    typeId: wire.typeId,
    state: mapState(wire.state, lang),
    gremiumId: wire.gremiumId ?? null,
    budgetPotId: wire.budgetPotId ?? null,
    amount: wire.amount ?? null,
    currency: wire.currency ?? null,
    createdAt: wire.createdAt,
    updatedAt: wire.updatedAt,
  };
}

export function mapApplicationCreated(wire: ApplicationCreatedWire): ApplicationCreated {
  return { applicationId: wire.applicationId };
}

export function mapTimelineEvent(wire: TimelineEventOutWire, lang: string): TimelineEntry {
  const toState = mapState(wire.toState, lang);
  return {
    toStateId: wire.toStateId,
    toState,
    label: toState?.label ?? '',
    actor: wire.actor ?? null,
    at: wire.at,
    note: wire.note ?? null,
  };
}

export function mapComment(wire: CommentOutWire): ApplicationComment {
  return {
    id: wire.id,
    author: wire.author ?? null,
    authorKind: wire.authorKind,
    body: wire.body,
    visibility: wire.visibility,
    isPublic: wire.visibility === 'public',
    at: wire.at,
  };
}

export function mapApplicationType(wire: ApplicationTypeListItemWire): ApplicationType {
  return {
    id: wire.id,
    name: wire.name,
    active: wire.active,
    hasBudget: wire.hasBudget,
    activeFormVersionId: wire.activeFormVersionId ?? null,
    key: wire.key ?? null,
    gremiumId: wire.gremiumId ?? null,
  };
}

export function mapTransition(wire: TransitionOutWire, lang: string): Transition {
  return {
    id: wire.id,
    fromStateId: wire.fromStateId,
    toStateId: wire.toStateId,
    label: resolveI18n(wire.label, lang),
  };
}

/**
 * Backend-Diff-Maps in iterierbare, schlüsseltragende Listen auflösen. `null`
 * (kein Diff, z. B. erste Version) wird durchgereicht; fehlende Teil-Maps werden
 * defensiv auf `{}` normalisiert.
 */
function mapDiff(wire: DataDiffWire | null | undefined): DataDiff | null {
  if (!wire) return null;
  return {
    added: Object.entries(wire.added ?? {}).map(([key, value]) => ({ key, value })),
    removed: Object.entries(wire.removed ?? {}).map(([key, value]) => ({ key, value })),
    changed: Object.entries(wire.changed ?? {}).map(([key, change]) => ({
      key,
      old: change.old,
      new: change.new,
    })),
  };
}

export function mapAttachment(wire: AttachmentOutWire): Attachment {
  return {
    id: wire.id,
    filename: wire.filename,
    mime: wire.mime,
    size: wire.size,
    scanned: wire.scanned,
    isComparisonOffer: wire.is_comparison_offer,
    // `scanned=true` heißt nur „Scan fertig"; sauber-vs-Befund klärt der Download.
    scanState: wire.scanned ? 'clean' : 'scanning',
  };
}

export function mapSignedUrl(wire: SignedUrlOutWire): SignedUrl {
  return { url: wire.url, expiresIn: wire.expiresIn };
}

export function mapVersion(wire: VersionOutWire): ApplicationVersion {
  return {
    version: wire.version,
    data: wire.data ?? {},
    diff: mapDiff(wire.diff),
    changedBy: wire.changedBy ?? null,
    at: wire.at,
  };
}

// --- Meetings + Protokoll (T-33) ------------------------------------------- //

export function mapMeetingVote(wire: MeetingVoteOutWire): MeetingVote {
  return {
    id: wire.id,
    applicationId: wire.applicationId,
    title: wire.title ?? null,
    status: wire.status,
    result: wire.result ?? null,
    counts: wire.counts ?? null,
    leading: wire.leading ?? null,
    closesAt: wire.closesAt ?? null,
  };
}

export function mapMeeting(wire: MeetingOutWire): Meeting {
  return {
    id: wire.id,
    title: wire.title,
    status: wire.status,
    activeApplicationId: wire.activeApplicationId ?? null,
    gremiumId: wire.gremiumId ?? null,
    votes: (wire.votes ?? []).map(mapMeetingVote),
    protocolId: wire.protocolId ?? null,
    createdAt: wire.createdAt,
  };
}

export function mapProtocol(wire: ProtocolOutWire): Protocol {
  return {
    id: wire.id,
    meetingId: wire.meetingId,
    markdown: wire.markdown ?? '',
    status: wire.status,
    isFinal: wire.status === 'final',
    pdfUrl: wire.pdfUrl ?? null,
    sentAt: wire.sentAt ?? null,
  };
}

// --- Budget (T-17/T-35, api.md »budget«) ----------------------------------- //

/**
 * Geld-String (`Decimal` → JSON-String, numeric(12,2)) in eine `number` für
 * Anzeige/Charts wandeln. `null`/leer → `null`; unparsebar → `0` (defensiv,
 * statt `NaN` ins UI durchzulassen).
 */
function money(value: string | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function moneyOrNull(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function mapBudgetPotInfo(wire: BudgetPotOutWire): BudgetPotInfo {
  return {
    id: wire.id,
    gremiumId: wire.gremiumId,
    name: wire.name,
    total: moneyOrNull(wire.total),
    currency: wire.currency,
    period: wire.period ?? null,
    active: wire.active,
  };
}

/**
 * Topf-Auslastung in die View-Form bringen. `names` (id → Anzeigename, aus
 * /budget-pots) ist optional — fehlt der Name (nur `budget.view`), fällt die
 * Anzeige auf eine gekürzte ID zurück, statt nichts zu zeigen.
 */
export function mapPotUsage(
  wire: PotUsageOutWire,
  names?: ReadonlyMap<Uuid, string>,
): PotUsage {
  return {
    budgetPotId: wire.budgetPotId,
    name: names?.get(wire.budgetPotId) ?? shortId(wire.budgetPotId),
    period: wire.period ?? null,
    total: moneyOrNull(wire.total),
    currency: wire.currency,
    requested: money(wire.requested),
    reserved: money(wire.reserved),
    approved: money(wire.approved),
    paid: money(wire.paid),
    committed: money(wire.committed),
    available: moneyOrNull(wire.available),
  };
}

export function mapStatusBucket(wire: StatusBucketOutWire): StatusBucket {
  return {
    gremiumId: wire.gremiumId ?? null,
    stateId: wire.stateId ?? null,
    count: wire.count,
  };
}

export function mapBudgetStats(
  wire: BudgetStatsOutWire,
  names?: ReadonlyMap<Uuid, string>,
): BudgetStats {
  return {
    pots: (wire.pots ?? []).map((p) => mapPotUsage(p, names)),
    statusDistribution: (wire.statusDistribution ?? []).map(mapStatusBucket),
  };
}

/** UUID auf ein kurzes, im UI brauchbares Label kürzen (`1234abcd…`). */
function shortId(id: Uuid): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

/** FE-Eingabe → camelCase-Request-Body für `POST /applications`. */
export function toApplicationCreateBody(input: NewApplication): ApplicationCreateBody {
  return {
    typeId: input.typeId,
    budgetPotId: input.budgetPotId ?? null,
    data: input.data,
    applicantEmail: input.applicantEmail,
    applicantName: input.applicantName ?? null,
    lang: input.lang,
    altcha: input.altcha,
  };
}
