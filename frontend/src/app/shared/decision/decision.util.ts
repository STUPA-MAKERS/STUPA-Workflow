import type { DecisionProposal } from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';

/** At most this many conditions, each 1 to MAX_CONDITION_LENGTH characters (as the server). */
export const MAX_CONDITIONS = 20;
export const MAX_CONDITION_LENGTH = 1000;

/**
 * The editor state of a decision proposal (F1, approval with deviations).
 *
 * `amount` is the canonical decimal string of the currency input (`"900.00"`, `''` for
 * empty). `conditions` keeps empty rows while the user types; `toProposal` drops them.
 */
export interface DecisionDraft {
  enabled: boolean;
  amount: string;
  conditions: string[];
}

/** The first problem of a draft, or null. The keys are i18n keys. */
export type DecisionDraftError =
  | 'decision.error.amountInvalid'
  | 'decision.error.amountExceeds'
  | 'decision.error.conditionLength'
  | 'decision.error.conditionCount';

type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

/** A new draft: switched off, the amount set to the requested amount. */
export function emptyDraft(requested: string | null | undefined): DecisionDraft {
  return { enabled: false, amount: requested ?? '', conditions: [] };
}

function toNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** The conditions that count: trimmed, empty rows dropped. */
export function cleanConditions(conditions: readonly string[]): string[] {
  return conditions.map((c) => c.trim()).filter((c) => c.length > 0);
}

/**
 * Check a draft as the server does: an amount greater than 0 with at most two decimals
 * and not above the requested amount, at most 20 conditions of 1 to 1000 characters.
 * A switched-off draft has no error.
 */
export function draftError(
  draft: DecisionDraft,
  requested: string | null | undefined,
): DecisionDraftError | null {
  if (!draft.enabled) return null;
  const req = toNumber(requested);
  if (draft.amount.trim() !== '') {
    const amount = toNumber(draft.amount);
    if (amount === null || amount <= 0 || req === null || !/^\d+(\.\d{1,2})?$/.test(draft.amount)) {
      return 'decision.error.amountInvalid';
    }
    if (amount > req) return 'decision.error.amountExceeds';
  }
  const conditions = cleanConditions(draft.conditions);
  if (conditions.length > MAX_CONDITIONS) return 'decision.error.conditionCount';
  if (conditions.some((c) => c.length > MAX_CONDITION_LENGTH)) {
    return 'decision.error.conditionLength';
  }
  return null;
}

/**
 * The proposal of a draft for the server, or null when the draft is off or changes
 * nothing. An amount equal to the requested one (or empty) goes as `null` ("as
 * requested").
 */
export function toProposal(
  draft: DecisionDraft,
  requested: string | null | undefined,
): DecisionProposal | null {
  if (!draft.enabled) return null;
  const amount = toNumber(draft.amount);
  const req = toNumber(requested);
  const approvedAmount = amount !== null && amount !== req ? draft.amount : null;
  const conditions = cleanConditions(draft.conditions);
  if (approvedAmount === null && conditions.length === 0) return null;
  return { approvedAmount, conditions };
}

/** Format an amount as money in the given format locale, or `''` without a value. */
export function formatMoney(
  value: string | number | null | undefined,
  locale: string,
  currency: string | null = 'EUR',
): string {
  const n = typeof value === 'number' ? value : toNumber(value);
  if (n === null) return '';
  return new Intl.NumberFormat(locale, { style: 'currency', currency: currency ?? 'EUR' }).format(n);
}

/** The signed difference `approved − requested` as money ("−350,00 €"), or `''`. */
export function formatDiff(
  requested: string | null | undefined,
  approved: string | null | undefined,
  locale: string,
  currency: string | null = 'EUR',
): string {
  const req = toNumber(requested);
  const appr = toNumber(approved);
  if (req === null || appr === null || req === appr) return '';
  const diff = Math.round((appr - req) * 100) / 100;
  const text = formatMoney(Math.abs(diff), locale, currency);
  return `${diff < 0 ? '−' : '+'}${text}`;
}

/** "1 Auflage" / "2 Auflagen". */
export function conditionCount(n: number, t: Translate): string {
  return n === 1 ? t('decision.conditionCount.one') : t('decision.conditionCount.other', { n });
}

/**
 * The prefill of the decision question of an application vote (F1).
 *
 * Without a deviation it is the plain question. With one it names the approved amount
 * (with the requested one) and/or the number of conditions.
 */
export function decisionQuestion(
  name: string,
  proposal: DecisionProposal | null,
  requested: string | null | undefined,
  locale: string,
  t: Translate,
): string {
  if (!proposal) return t('meetings.vote.questionPrefill', { name });
  const n = proposal.conditions.length;
  if (proposal.approvedAmount !== null) {
    const params = {
      name,
      approved: formatMoney(proposal.approvedAmount, locale),
      requested: formatMoney(requested, locale),
    };
    return n
      ? t('meetings.vote.questionPrefillDecision', { ...params, conditions: conditionCount(n, t) })
      : t('meetings.vote.questionPrefillAmount', params);
  }
  return t('meetings.vote.questionPrefillConditions', { name, conditions: conditionCount(n, t) });
}

/** The line of a status change that carried a decision, for the history. */
export function decisionHistoryLine(
  decision: {
    requestedAmount: string | null;
    approvedAmount: string | null;
    amountDeviates: boolean;
    conditionCount: number;
  },
  locale: string,
  currency: string | null,
  t: Translate,
): string | null {
  const n = decision.conditionCount;
  if (decision.amountDeviates) {
    const params = {
      approved: formatMoney(decision.approvedAmount, locale, currency),
      requested: formatMoney(decision.requestedAmount, locale, currency),
    };
    return n
      ? t('applications.history.decisionAmountConditions', {
          ...params,
          conditions: conditionCount(n, t),
        })
      : t('applications.history.decisionAmount', params);
  }
  return n ? t('applications.history.decisionConditions', { conditions: conditionCount(n, t) }) : null;
}
