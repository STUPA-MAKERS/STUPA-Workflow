import type { PersonRef } from '@core/api/models';
import type {
  TicketArea,
  TicketEvent,
  TicketEventPayload,
  TicketKind,
  TicketReporter,
  TicketStatus,
} from '@core/api/tickets.service';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import type { IconName } from '@stupa-makers/ui-kit';
import { daysUntil, shortDay } from '@shared/date-format';
import { personLabel, personName } from '@shared/person-label.util';
import {
  type StatusKind,
} from '@stupa-makers/ui-kit';

export const KIND_ICON: Record<TicketKind, IconName> = {
  bug: 'bug',
  question: 'help',
  idea: 'bulb',
  barrier: 'eye',
};

export const KIND_LABEL: Record<TicketKind, TranslationKey> = {
  bug: 'tickets.kind.bug',
  question: 'tickets.kind.question',
  idea: 'tickets.kind.idea',
  barrier: 'tickets.kind.barrier',
};

/** The icon of a ticket: the icon of its kind, else the ticket of a Bereich without kinds. */
export function ticketIcon(kind: TicketKind | null): IconName {
  return kind ? KIND_ICON[kind] : 'ticket';
}

/** The Bereich of a ticket in the list of the Bereiche; null while the list loads. */
export function areaOf(areaId: string, areas: readonly TicketArea[]): TicketArea | null {
  return areas.find((a) => a.id === areaId) ?? null;
}

/**
 * The Kategorie of a ticket by name: the kind in the Bereich "Plattform", else the
 * Kategorie of its Bereich. The empty string: no Kategorie.
 */
export function categoryName(
  ticket: { readonly kind: TicketKind | null; readonly categoryId: string | null; readonly areaId: string },
  areas: readonly TicketArea[],
  t: Translate,
): string {
  if (ticket.kind) return t(KIND_LABEL[ticket.kind]);
  const area = areaOf(ticket.areaId, areas);
  return area?.categories.find((c) => c.id === ticket.categoryId)?.name ?? '';
}

export const STATUS_LABEL: Record<TicketStatus, TranslationKey> = {
  new: 'tickets.status.new',
  in_progress: 'tickets.status.in_progress',
  done: 'tickets.status.done',
  rejected: 'tickets.status.rejected',
};

/** The colour of a state: new is the accent, work in progress the warning colour. */
export const STATUS_KIND: Record<TicketStatus, StatusKind> = {
  new: 'accent',
  in_progress: 'warn',
  done: 'neutral',
  rejected: 'muted',
};

/** Done and rejected close a ticket; the other two are open. */
export function isOpen(status: TicketStatus): boolean {
  return status === 'new' || status === 'in_progress';
}

/** The reporter: the name, else the e-mail, else "Anonymisiert". */
export function reporterName(reporter: TicketReporter, t: Translate): string {
  if (reporter.anonymized) return t('tickets.reporter.anonymized');
  return personLabel(reporter, t, { fallback: 'chat.deletedPerson' });
}

/**
 * The reporter in the sub line of a list row, which is cut with an ellipsis. An
 * e-mail is never cut, so a reporter known only by the e-mail gives null there; the
 * detail shows the full address.
 */
export function reporterRowName(reporter: TicketReporter, t: Translate): string | null {
  if (reporter.anonymized) return t('tickets.reporter.anonymized');
  if (reporter.displayName) return reporter.displayName;
  return reporter.email ? null : t('chat.deletedPerson');
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

/**
 * The age of a ticket for a list row: "gerade eben", "vor 12 Min.", "vor 3 Std.",
 * "gestern", then the date ("12.10.", with the year when it is another year).
 */
export function ticketAge(at: string, now: Date, locale: string, t: Translate): string {
  const then = new Date(at);
  if (Number.isNaN(then.getTime())) return '';
  const diff = now.getTime() - then.getTime();
  if (diff < MINUTE) return t('tickets.age.now');
  if (diff < HOUR) return t('tickets.age.minutes', { n: Math.floor(diff / MINUTE) });
  const days = daysUntil(now, then);
  if (days === 0) return t('tickets.age.hours', { n: Math.floor(diff / HOUR) });
  if (days === 1) return t('tickets.age.yesterday');
  return shortDay(then, locale, now);
}

/**
 * The text of a status change in the thread of the reporter, which carries no actor
 * ("Status Neu → In Arbeit").
 */
export function reporterEventText(payload: TicketEventPayload, t: Translate): string {
  const from = t(STATUS_LABEL[payload.from as TicketStatus] ?? 'tickets.status.new');
  const to = t(STATUS_LABEL[payload.to as TicketStatus] ?? 'tickets.status.new');
  return t('tickets.event.statusPlain', { from, to });
}

/** The text of an event in the thread ("Mara Keller hat das Ticket übernommen"). */
export function eventText(event: TicketEvent, reporter: string, t: Translate): string {
  const actor = event.actor ? personName(event.actor, t) : t('tickets.event.system');
  const p = event.payload;
  switch (event.kind) {
    case 'created':
      return p.confirmationSent
        ? t('tickets.event.confirmation', { name: reporter })
        : t('tickets.event.created');
    case 'status': {
      if (p.duplicateOf) return t('tickets.event.duplicate', { actor, number: p.duplicateOf });
      const from = t(STATUS_LABEL[p.from as TicketStatus] ?? 'tickets.status.new');
      const to = t(STATUS_LABEL[p.to as TicketStatus] ?? 'tickets.status.new');
      return t('tickets.event.status', { actor, from, to });
    }
    case 'assignee': {
      const to = (p.to ?? null) as PersonRef | null;
      if (!to) return t('tickets.event.unassigned', { actor });
      if (event.actor && to.principalId && to.principalId === event.actor.principalId) {
        return t('tickets.event.took', { actor });
      }
      return t('tickets.event.assigned', { actor, name: personName(to, t) });
    }
    case 'kind': {
      const from = t(KIND_LABEL[p.from as TicketKind] ?? 'tickets.kind.bug');
      const to = t(KIND_LABEL[p.to as TicketKind] ?? 'tickets.kind.bug');
      return t('tickets.event.kind', { actor, from, to });
    }
    case 'category': {
      const none = t('tickets.detail.noCategory');
      const from = typeof p.from === 'string' ? p.from : none;
      const to = typeof p.to === 'string' ? p.to : none;
      return t('tickets.event.kind', { actor, from, to });
    }
    case 'area':
      return t('tickets.event.area', {
        actor,
        from: p.fromName ?? t('tickets.event.areaGone'),
        to: p.toName ?? t('tickets.event.areaGone'),
      });
    case 'todo_done':
      return p.cardTitle
        ? t('tickets.event.todoDone', { actor, title: p.cardTitle })
        : t('tickets.event.todoDoneHidden', { actor });
  }
}
