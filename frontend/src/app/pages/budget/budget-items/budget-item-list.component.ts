import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { Params } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { i18nLabel } from '@shared/forms/i18n-text';
import { SimplifyPathPipe } from '@shared/budget-path';
import { shortDay } from '@shared/date-format';
import { formatMoney } from '@shared/format-money';
import { flowColorKind } from '@shared/ui';
import {
  IconComponent,
  type IconName,
  ListItemComponent,
  type StatusKind,
  StatusTextComponent,
} from '@stupa-makers/ui-kit';
import { signedEur } from '../expense-display.util';
import { type BudgetItem, budgetItemKey } from './budget-items';

/** One row of the list, ready for the template. */
interface ItemRow {
  readonly key: string;
  readonly icon: IconName;
  /** The name of the type, for a screen reader. */
  readonly typeLabel: string;
  readonly title: string;
  readonly link: readonly unknown[];
  readonly queryParams: Params | null;
  readonly statusLabel: string | null;
  readonly statusKind: StatusKind;
  readonly pathKey: string | null;
  readonly costCentre: string | null;
  /** The date of a booking; `''` for an application. */
  readonly date: string;
  readonly amount: string;
  readonly income: boolean;
}

/**
 * The applications and the bookings of a cost centre in one row group.
 *
 * The lead icon tells the two types apart: the icon of the applications page for an
 * application, the icon of the bookings page for a booking. An application row opens the
 * application, a booking row opens the booking on the bookings page.
 *
 * The host is no element of the row group, because `.rowgroup` styles only its direct
 * `app-list-item` children; the group is inside the template.
 */
@Component({
  selector: 'app-budget-item-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, ListItemComponent, SimplifyPathPipe, StatusTextComponent],
  templateUrl: './budget-item-list.component.html',
  styleUrl: './budget-item-list.component.scss',
})
export class BudgetItemListComponent {
  private readonly i18n = inject(I18nService);

  readonly items = input.required<readonly BudgetItem[]>();
  /** The names of the cost centres by id, for the cost centre of each row. */
  readonly names = input<ReadonlyMap<string, { name: string }>>(new Map());

  protected readonly rows = computed<ItemRow[]>(() => {
    const names = this.names();
    const locale = this.i18n.formatLocale();
    return this.items().map((item): ItemRow => {
      const key = budgetItemKey(item);
      if (item.type === 'application') {
        const app = item.app;
        const label = app.stateLabel ? i18nLabel(app.stateLabel, this.i18n.uiLocale(), Object.values(app.stateLabel)[0] ?? '') : '';
        return {
          key,
          icon: 'file',
          typeLabel: this.i18n.translate('budget.dash.itemApplication'),
          title: app.title?.trim() || this.i18n.translate('applications.list.untitled'),
          link: ['/applications', app.applicationId],
          queryParams: null,
          statusLabel: label || null,
          statusKind: flowColorKind(app.stateColor),
          pathKey: app.pathKey,
          costCentre: app.budgetId ? (names.get(app.budgetId)?.name ?? null) : null,
          date: '',
          amount: app.amount === null ? '—' : formatMoney(app.amount, locale, { currency: app.currency ?? 'EUR' }),
          income: false,
        };
      }
      const b = item.booking;
      const income = b.kind === 'income';
      return {
        key,
        icon: 'swap',
        typeLabel: this.i18n.translate('budget.dash.itemBooking'),
        title: b.description,
        link: ['/expenses'],
        queryParams: { id: b.id },
        statusLabel: this.i18n.translate(income ? 'expenses.kind.income' : 'expenses.kind.expense'),
        statusKind: income ? 'accent' : 'muted',
        pathKey: null,
        costCentre: names.get(b.budgetId)?.name ?? null,
        date: shortDay((b.paymentDate ?? b.createdAt).slice(0, 10), locale),
        amount: signedEur(b.kind, b.amount, locale),
        income,
      };
    });
  });
}
