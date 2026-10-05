import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { Application } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import {
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SegBarComponent,
  SkeletonComponent,
  StatusTextComponent,
  flowColorKind,
  invoiceStatus,
} from '@shared/ui';
import { simplifyPathKey } from '@shared/budget-path';
import type { BudgetTreeNode, Expense, Invoice } from '../../budget/budget-tree.api';
import {
  type CostCentreLabel,
  costCentreFigures,
  costCentreLabel,
  costCentreTrail,
  findBudgetNode,
  findTopBudgetNode,
  formatEur,
  shortDate,
  signedEur,
} from '../../budget/expense-display.util';
import { bookedOn } from '../../invoices/invoice-figures';
import { SheetBarComponent } from '@shared/ui/sheet-bar/sheet-bar.component';

/**
 * The detail of a booking (boards Fin-Buchungen, Fin-Schmal-Buchung, Fin-Tel-Buchung):
 * "Buchung · HHJ 2026", the description, "Art · Kostenstelle · Betrag" and the sections
 * Zahlung, Details, Unterbuchungen, Verknüpft (application and invoice) and Kostenstelle.
 *
 * The page loads the linked records and hands them in; this component only shows them
 * and reports the actions.
 */
@Component({
  selector: 'app-booking-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SheetBarComponent,
    ButtonComponent,
    IconComponent,
    LocalizedDatePipe,
    RouterLink,
    RowMenuComponent,
    SegBarComponent,
    SkeletonComponent,
    StatusTextComponent,
    TranslatePipe,
  ],
  templateUrl: './booking-detail.component.html',
  styleUrl: './booking-detail.component.scss',
})
export class BookingDetailComponent {
  private readonly i18n = inject(I18nService);

  readonly expense = input.required<Expense>();
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());
  readonly tree = input<BudgetTreeNode[]>([]);
  /** The label of the fiscal year, null while unknown. */
  readonly fyLabel = input<string | null>(null);
  readonly invoice = input<Invoice | null>(null);
  readonly application = input<Application | null>(null);
  readonly subRows = input<readonly Expense[]>([]);
  readonly subLoading = input(false);
  /** `budget.book`: edit, delete and the sub-bookings. */
  readonly canManage = input(false);
  /** Side by side: the sheet look. */
  readonly split = input(false);
  readonly phone = input(false);

  readonly edit = output<Expense>();
  readonly remove = output<Expense>();
  readonly addSub = output<void>();
  readonly openFile = output<Invoice>();

  protected readonly invoiceStatus = invoiceStatus;

  protected readonly cc = computed(() => {
    const e = this.expense();
    return costCentreLabel(this.costCentres(), e.budgetId, e.pathKey);
  });

  /** "Fachschaften › Maschinenbau", or the name when the tree does not hold it. */
  protected readonly ccTrail = computed(
    () => costCentreTrail(this.tree(), this.expense().budgetId) ?? this.cc().name,
  );

  /** "Buchung · HHJ 2026" (or "Unterbuchung"). */
  protected readonly metaLine = computed(() => {
    const e = this.expense();
    const kind = this.i18n.translate(e.parentExpenseId ? 'expenses.detail.subKind' : 'expenses.detail.kind');
    const fy = this.fyLabel();
    return fy ? `${kind} · ${this.i18n.translate('expenses.detail.fy', { fy })}` : kind;
  });

  protected readonly amount = computed(() => {
    const e = this.expense();
    return signedEur(e.kind, e.amount, this.i18n.locale());
  });

  protected readonly paymentMethod = computed(() => {
    const m = this.expense().paymentMethod;
    return m ? this.i18n.translate(`expenses.paymentMethod.${m}`) : null;
  });

  /** "Konrad Pfeiffer · 25.09.2026, 10:14": who booked it and when. */
  protected readonly createdAt = computed(() =>
    new Date(this.expense().createdAt).toLocaleString(this.i18n.formatLocale(), {
      dateStyle: 'medium',
      timeStyle: 'short',
    }),
  );

  /** A parent booking: its amount is the sum of its sub-bookings. */
  protected readonly isParent = computed(() => (this.expense().childCount ?? 0) > 0);
  /** The sub-booking section: a parent, or a booking that can get its first one. */
  protected readonly showSubs = computed(
    () => this.isParent() || (this.canManage() && !this.expense().parentExpenseId),
  );

  /** The application card: the loaded application, else the title the booking carries. */
  protected readonly app = computed(() => {
    const e = this.expense();
    if (!e.applicationId) return null;
    const a = this.application();
    const loaded = a?.id === e.applicationId ? a : null;
    return {
      id: e.applicationId,
      title: e.applicationTitle || this.i18n.translate('expenses.col.application'),
      amount: loaded?.amount ? formatEur(Number(loaded.amount), this.i18n.locale()) : null,
      state: loaded?.state ?? null,
      stateKind: flowColorKind(loaded?.state?.color),
    };
  });

  /** The invoice card: number · supplier, gross, status, due date and the booked share. */
  protected readonly inv = computed(() => {
    const e = this.expense();
    const i = this.invoice();
    if (!e.invoiceId) return null;
    if (!i || i.id !== e.invoiceId) {
      return { loaded: null, title: e.invoiceNumber ?? '', booked: null };
    }
    return {
      loaded: i,
      title: [i.number, i.supplier].filter((p) => !!p).join(' · '),
      booked: bookedOn(i),
    };
  });

  /** The figures of the cost centre in the fiscal year of the booking. */
  protected readonly figures = computed(() => {
    const e = this.expense();
    const node = findBudgetNode(this.tree(), e.budgetId);
    const f = costCentreFigures(node, e.fiscalYearId);
    if (!f) return null;
    const total = f.available + f.expended + f.bound;
    return {
      ...f,
      total: total > 0 ? total : null,
      segments: [
        { value: f.expended, tone: f.available < 0 ? ('error' as const) : ('filled' as const) },
        { value: f.bound, tone: f.available < 0 ? ('error' as const) : ('second' as const) },
      ],
    };
  });

  /** The Budget page drilled into this cost centre and year. */
  protected readonly budgetLink = computed(() => {
    const e = this.expense();
    const top = findTopBudgetNode(this.tree(), e.budgetId);
    return { budget: top?.id ?? null, ks: e.budgetId, fy: e.fiscalYearId };
  });

  protected readonly path = computed(() => {
    const p = this.expense().pathKey;
    return p ? simplifyPathKey(p) : this.cc().path;
  });

  protected readonly subSum = computed(() => {
    const e = this.expense();
    return signedEur(e.kind, e.amount, this.i18n.locale());
  });

  protected readonly menu = computed<RowMenuSection[]>(() => {
    const e = this.expense();
    const items: RowMenuItem[] = [];
    if (this.canManage() && !e.parentExpenseId) {
      items.push({ id: 'sub', label: this.i18n.translate('expenses.sub.add'), icon: 'add' });
    }
    const inv = this.invoice();
    if (inv && inv.id === e.invoiceId && inv.hasFile) {
      items.push({ id: 'file', label: this.i18n.translate('invoices.openFile'), icon: 'file' });
    }
    const sections: RowMenuSection[] = items.length ? [{ items }] : [];
    if (this.canManage()) {
      sections.push({
        items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }],
      });
    }
    return sections;
  });

  onMenu(item: RowMenuItem): void {
    const e = this.expense();
    if (item.id === 'sub') this.addSub.emit();
    else if (item.id === 'delete') this.remove.emit(e);
    else if (item.id === 'file') {
      const inv = this.invoice();
      if (inv) this.openFile.emit(inv);
    }
  }

  /** The menu of a sub-booking row. */
  protected readonly subMenu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' }] },
    {
      items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }],
    },
  ]);

  onSubMenu(item: RowMenuItem, s: Expense): void {
    if (item.id === 'edit') this.edit.emit(s);
    else if (item.id === 'delete') this.remove.emit(s);
  }

  money(value: number | string): string {
    return formatEur(Number(value), this.i18n.locale());
  }

  signed(e: Expense): string {
    return signedEur(e.kind, e.amount, this.i18n.locale());
  }

  day(iso: string | null): string {
    return shortDate(iso, this.i18n.locale());
  }

  /** "900,00 € von 2.890,00 € verbucht", the name of the bar. */
  bookedLabel(booked: number, gross: number): string {
    return this.i18n.translate('invoices.bookedLabel', {
      booked: this.money(booked),
      gross: this.money(gross),
    });
  }

  usageLabel(f: { expended: number; bound: number; available: number }): string {
    return this.i18n.translate('expenses.detail.usageLabel', {
      expended: this.money(f.expended),
      bound: this.money(f.bound),
      available: this.money(f.available),
    });
  }
}
