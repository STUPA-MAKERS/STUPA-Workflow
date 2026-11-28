import { type Observable, concat, last, of } from 'rxjs';
import { type PretixEventOption, SalesApiService } from '@core/api/sales.service';
import type { SelectOption } from '@stupa-makers/ui-kit';

/** The pretix event and the field "Einnahmen-Kostenstelle" of an Event in its form. */
export interface PretixChoice {
  readonly slug: string;
  readonly incomeBudgetId: string;
}

export const NO_PRETIX: PretixChoice = { slug: '', incomeBudgetId: '' };

/** The two fields of the form of a link. */
export function pretixValue(choice: PretixChoice): Readonly<Record<string, string>> {
  return { pretixSlug: choice.slug, incomeBudgetId: choice.incomeBudgetId };
}

/** The picker "Pretix-Veranstaltung": none, then each event that no other Event links (003083). */
export function pretixOptions(
  events: readonly PretixEventOption[],
  own: string,
  none: string,
  date: (iso: string) => string,
): readonly SelectOption[] {
  return [
    { value: '', label: none },
    ...events
      .filter((e) => !e.taken || e.slug === own)
      .map((e) => ({ value: e.slug, label: e.dateFrom ? `${e.name} · ${date(e.dateFrom)}` : e.name })),
  ];
}

/**
 * The calls that bring the link of the Event from `before` to `after`: link or unlink, then
 * the field "Einnahmen-Kostenstelle" when the person may book (003086). Nothing to do is one
 * `null`.
 */
export function pretixSteps(
  api: SalesApiService,
  eventId: string,
  before: PretixChoice,
  after: PretixChoice,
  mayBook: boolean,
): Observable<unknown> {
  const link =
    after.slug === before.slug ? [] : [after.slug ? api.link(eventId, after.slug) : api.unlink(eventId)];
  const was = after.slug === before.slug ? before.incomeBudgetId : '';
  const budgetChanged = !!after.slug && mayBook && after.incomeBudgetId !== was;
  const budget = budgetChanged ? [api.setIncomeBudget(eventId, after.incomeBudgetId || null)] : [];
  return concat(of(null), ...link, ...budget).pipe(last());
}
