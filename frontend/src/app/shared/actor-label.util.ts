/**
 * The display label of an actor: who did a status change, an edit or a comment.
 *
 * The server sends a resolved `ActorInfo` (`actorInfo`, `changedByInfo`, `authorInfo`).
 * This function turns it into text. The UI never shows a raw principal `sub`, a UUID or
 * a stored key such as `system:deadlines`:
 *
 * - a member: the name;
 * - the applicant: "Antragsteller:in" (or "Du" on the own status page);
 * - an automatic action: "System · Fristen", "System · Automatisch", …;
 * - the Gremium (applicant view, A12/O16): the Gremium name;
 * - an unknown or anonymized account: "Ehemaliges Konto".
 *
 * Without `ActorInfo` (an older server) the function reads the legacy string with the
 * same rules, and it hides a value that looks like an id.
 */
import type { ActorInfo } from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';

export type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

/** The actor value of the magic-link applicant in the timeline and the versions. */
export const APPLICANT_ACTOR = 'applicant';

const SYSTEM_PREFIX = 'system:';

/** Every system key that the backend writes, with its label. */
const SYSTEM_LABELS: Record<string, TranslationKey> = {
  auto: 'actor.system.auto',
  deadlines: 'actor.system.deadlines',
  flow: 'actor.system.flow',
  confirmation: 'actor.system.confirmation',
  retention: 'actor.system.retention',
  migration: 'actor.system.migration',
};

/** A UUID, or a long hex string such as a hashed OIDC `sub`. */
const ID_LIKE = /^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{24,})$/i;

export interface ActorLabelOptions {
  /** The label of the applicant. Default "Antragsteller:in"; the status page uses "Du". */
  applicantKey?: TranslationKey;
}

/** The label of a system key; an unknown key gives the plain "System". */
export function systemActorLabel(key: string | null | undefined, t: Translate): string {
  const k = key || 'auto';
  return t(SYSTEM_LABELS[k] ?? 'actor.system.other');
}

/** Convert a legacy actor string to an `ActorInfo`. */
export function actorInfoFromLegacy(value: string | null | undefined): ActorInfo | null {
  if (!value) return null;
  if (value === APPLICANT_ACTOR) return { kind: 'applicant' };
  if (value === 'system') return { kind: 'system', key: 'auto' };
  if (value.startsWith(SYSTEM_PREFIX)) {
    return { kind: 'system', key: value.slice(SYSTEM_PREFIX.length) || 'auto' };
  }
  if (ID_LIKE.test(value)) return { kind: 'deleted' };
  return { kind: 'principal', displayName: value };
}

/**
 * The label of an actor, or null when there is no actor.
 *
 * `info` wins over `legacy`. Pass both, so that an older response still renders.
 */
export function actorLabel(
  info: ActorInfo | null | undefined,
  legacy: string | null | undefined,
  t: Translate,
  options: ActorLabelOptions = {},
): string | null {
  const actor = info ?? actorInfoFromLegacy(legacy);
  if (!actor) return null;
  switch (actor.kind) {
    case 'principal':
      return actor.displayName || t('actor.deleted');
    case 'applicant':
      return t(options.applicantKey ?? 'applications.comments.author.applicant');
    case 'system':
      return systemActorLabel(actor.key, t);
    case 'gremium':
      return actor.displayName || t('applications.comments.author.committee');
    case 'deleted':
      return t('actor.deleted');
  }
}
