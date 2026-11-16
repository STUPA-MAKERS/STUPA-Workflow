import { type Injector, type Signal, computed } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { map, of, switchMap } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
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

/**
 * The row of the Haushaltsplan of an agenda item: the title of the item and "Haushaltsplan".
 * It opens the version on the plan page in a new tab. `null` for an item without a plan and
 * for a reader who may not read the plan (`readableId` is the version that the reader may read).
 */
export function topPlanLead(
  top: AgendaItem | null,
  readableId: string | null,
  i18n: I18nService,
): LinkedLead | null {
  if (!top?.planVersionId || top.planVersionId !== readableId) return null;
  return {
    icon: 'euro',
    title: top.title || i18n.translate('meetings.agenda.untitled'),
    sub: i18n.translate('meetings.agenda.planSub'),
    link: ['/budget/plan'],
    queryParams: { planVersion: top.planVersionId },
  };
}

/**
 * The first row of the linked list of an agenda item: its application, or its Haushaltsplan
 * when the reader may read the plan. Only an item with a plan asks the API, so `ApiClient`
 * comes from the injector at that moment. Call it in an injection context.
 */
export function topLead(
  top: Signal<AgendaItem | null>,
  injector: Injector,
  i18n: I18nService,
): Signal<LinkedLead | null> {
  const planId = computed(() => top()?.planVersionId ?? null);
  const readableId = toSignal(
    toObservable(planId).pipe(
      switchMap((id) => (id ? injector.get(ApiClient).planOfVersionReadable(id).pipe(map((ok) => (ok ? id : null))) : of(null))),
    ),
    { initialValue: null },
  );
  return computed(() => topApplicationLead(top(), i18n) ?? topPlanLead(top(), readableId(), i18n));
}
