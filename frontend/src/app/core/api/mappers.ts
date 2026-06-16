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
  MeetingPage,
  MeetingPageWire,
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
    color: wire.color ?? null,
    editAllowed: wire.editAllowed,
    kind: wire.kind ?? 'normal',
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
    budgetId: wire.budgetId ?? null,
    amount: wire.amount ?? null,
    currency: wire.currency ?? null,
    data: wire.data ?? {},
    version: wire.version,
    lang: wire.lang ?? null,
    createdAt: wire.createdAt,
    updatedAt: wire.updatedAt,
    applicant: mapApplicant(wire.applicant),
    canEdit: wire.canEdit ?? false,
    isOwner: wire.isOwner ?? false,
  };
}

export function mapApplicationListItem(
  wire: ApplicationListItemWire,
  lang: string,
): ApplicationListItem {
  return {
    id: wire.id,
    typeId: wire.typeId,
    title: wire.title ?? null,
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
    color: wire.color ?? null,
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
    applicationId: wire.applicationId ?? null,
    agendaItemId: wire.agendaItemId ?? null,
    title: wire.title ?? null,
    question: wire.question ?? null,
    options: wire.options ?? [],
    status: wire.status,
    result: wire.result ?? null,
    counts: wire.counts ?? null,
    leading: wire.leading ?? null,
    closesAt: wire.closesAt ?? null,
    voted: wire.voted ?? 0,
    present: wire.present ?? 0,
    revealed: wire.revealed ?? true,
    failedReason: wire.failedReason ?? null,
  };
}

export function mapMeeting(wire: MeetingOutWire): Meeting {
  const canWrite = wire.canWrite ?? wire.canControl ?? false;
  return {
    id: wire.id,
    title: wire.title,
    date: wire.date ?? null,
    startTime: wire.startTime ?? null,
    endTime: wire.endTime ?? null,
    status: wire.status,
    activeApplicationId: wire.activeApplicationId ?? null,
    gremiumId: wire.gremiumId ?? null,
    gremiumName: wire.gremiumName ?? null,
    votes: (wire.votes ?? []).map(mapMeetingVote),
    protocolId: wire.protocolId ?? null,
    createdAt: wire.createdAt,
    protokollantId: wire.protokollantId ?? null,
    protokollantName: wire.protokollantName ?? null,
    isProtokollant: wire.isProtokollant ?? false,
    canControl: wire.canControl ?? canWrite,
    canManage: wire.canManage ?? false,
    canWrite,
    canManageVotes: wire.canManageVotes ?? false,
    canVote: wire.canVote ?? false,
  };
}

export function mapMeetingPage(wire: MeetingPageWire): MeetingPage {
  return {
    items: (wire.items ?? []).map(mapMeeting),
    nextCursor: wire.nextCursor ?? null,
  };
}

export function mapProtocol(wire: ProtocolOutWire): Protocol {
  return {
    id: wire.id,
    meetingId: wire.meetingId,
    markdown: wire.markdown ?? '',
    status: wire.status,
    isFinal: wire.status === 'final',
    isLocked: wire.status !== 'draft',
    pdfUrl: wire.pdfUrl ?? null,
    publicPdfUrl: wire.publicPdfUrl ?? null,
    sentAt: wire.sentAt ?? null,
  };
}

/** FE-Eingabe → camelCase-Request-Body für `POST /applications`. */
export function toApplicationCreateBody(input: NewApplication): ApplicationCreateBody {
  return {
    typeId: input.typeId,
    budgetPotId: input.budgetPotId ?? null,
    data: input.data,
    applicantEmail: input.applicantEmail ?? null,
    applicantName: input.applicantName ?? null,
    lang: input.lang,
    altcha: input.altcha ?? null,
  };
}
