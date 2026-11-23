import type { PersonRef, ScanState } from '@core/api/models';
import type {
  TicketArea,
  TicketEvent,
  TicketEventPayload,
  TicketKind,
  TicketMail,
  TicketReporter,
  TicketSource,
  TicketStatus,
} from '@core/api/tickets.service';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import type { IconName } from '@stupa-makers/ui-kit';
import { daysUntil, shortDay } from '@shared/date-format';
import { personLabel, personName } from '@shared/person-label.util';
import {
  formatBytes,
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
  waiting: 'tickets.status.waiting',
  done: 'tickets.status.done',
  rejected: 'tickets.status.rejected',
};

/** The source of a ticket by name. */
export const SOURCE_LABEL: Record<TicketSource, TranslationKey> = {
  help: 'tickets.source.help',
  mail: 'tickets.source.mail',
  team: 'tickets.source.team',
};

/** The colour of a state: new is the accent, work in progress the warning colour. */
export const STATUS_KIND: Record<TicketStatus, StatusKind> = {
  new: 'accent',
  in_progress: 'warn',
  waiting: 'neutral',
  done: 'neutral',
  rejected: 'muted',
};

/** The open states in the order of the list. "Wartet auf Antwort" is open. */
export const OPEN_STATUSES: readonly TicketStatus[] = ['new', 'in_progress', 'waiting'];

/** Done and rejected close a ticket; the other three are open. */
export function isOpen(status: TicketStatus): boolean {
  return OPEN_STATUSES.includes(status);
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
    case 'mail_auto':
      return t('tickets.event.mailAuto', {
        name: typeof p.from === 'string' ? p.from : reporter,
        subject: p.subject ?? '',
      });
  }
}

/** The file name of the source of a mail in the thread. */
export const MAIL_SOURCE_NAME = 'Original-Mail.eml';

/** The scan state of a mail source as the chat shows it; null when the source is gone. */
export function mailSourceScan(mail: TicketMail): ScanState | null {
  if (mail.source === 'gone') return null;
  if (mail.source === 'clean') return 'clean';
  return mail.source === 'infected' ? 'quarantined' : 'scanning';
}

/**
 * The line that names the files of a mail that were left out, with the size of each
 * ("Nicht übernommen: plan.zip (2 MB, Dateityp nicht erlaubt)"); empty without one.
 */
export function skippedLine(mail: TicketMail | undefined, locale: string, t: Translate): string {
  if (!mail?.skipped.length) return '';
  const files = mail.skipped.map((f) =>
    t(f.reason === 'size' ? 'tickets.mail.skippedSize' : 'tickets.mail.skippedType', {
      name: f.name,
      size: formatBytes(f.size, locale, 'file'),
    }),
  );
  return t('tickets.mail.skipped', { files: files.join(', ') });
}

/** The text of a message with the line of its left-out files under it. */
export function withSkipped(body: string, line: string): string {
  return line ? (body ? `${body}\n\n${line}` : line) : body;
}
