import type { I18nService } from '@core/i18n/i18n.service';
import type { AgendaItem } from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { formatMoney } from '@shared/format-money';
import type { LinkedLead } from '../todos/linked-list/todo-linked-list.component';

/**
 * The row of the application of an agenda item, the first row of its linked list: its
 * title and "Antrag · Entwurf · 1.250,00 €". It opens the application in a new tab, so the
 * minutes stay open. `null` for an item without an application.
 */
export function topApplicationLead(top: AgendaItem | null, i18n: I18nService): LinkedLead | null {
  if (!top?.applicationId) return null;
  const state = resolveI18n(top.stateLabel, i18n.uiLocale());
  const amount = formatMoney(top.amount, i18n.formatLocale());
  const parts = [
    i18n.translate('meetings.agenda.kindApplication'),
    ...(state ? [state] : []),
    ...(amount ? [amount] : []),
  ];
  return {
    icon: 'file',
    title: top.applicationTitle || top.title || i18n.translate('meetings.agenda.untitled'),
    sub: parts.join(' · '),
    link: ['/applications', top.applicationId],
  };
}
