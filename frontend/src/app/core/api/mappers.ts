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
  CommentOutWire,
  ApplicationComment,
  NewApplication,
  StateOutWire,
  TimelineEntry,
  TimelineEventOutWire,
  Transition,
  TransitionOutWire,
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
