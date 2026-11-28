import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { type EventSales, SalesApiService } from '@core/api/sales.service';
import { I18nService } from '@core/i18n/i18n.service';
import { formatMoment } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { formatMoney } from '@shared/format-money';
import { SalesSyncAction } from '@shared/sales-sync';
import { ButtonComponent, ButtonGroupComponent, FieldGroupComponent, FieldRowComponent, IconComponent, SectionComponent, ToastService } from '@stupa-makers/ui-kit';

/** One row of the section: a label and its value. */
export interface SalesRow {
  readonly label: string;
  readonly value: string;
}

/**
 * The section "Verkauf" of an Event (specs 003084, 003096): the sales of the linked pretix
 * event and the money of its Mollie payments, with the time of the last read.
 *
 * Each person who reads the Event sees the sums. The action "Aktualisieren" reads them at
 * once (003085), at most once a minute; the server answers 429 `refresh_too_soon` before.
 * The section stays hidden while no part has data, because the integration shows no element
 * while it is off (003081, 003093).
 */
@Component({
  selector: 'app-event-sales',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, ButtonGroupComponent, FieldGroupComponent, FieldRowComponent, IconComponent, SectionComponent],
  host: { '[attr.hidden]': 'shown() ? null : ""' },
  templateUrl: './event-sales.component.html',
})
export class EventSalesComponent {
  private readonly api = inject(SalesApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly sync = inject(SalesSyncAction);

  readonly eventId = input.required<string>();

  protected readonly sales = signal<EventSales | null>(null);
  protected readonly refreshing = signal(false);

  protected readonly shown = computed(() => {
    const s = this.sales();
    return !!s && (!!s.link || !!s.mollie);
  });

  /** The pretix event and the field "Einnahmen-Kostenstelle". */
  protected readonly linkRows = computed<readonly SalesRow[]>(() => {
    const link = this.sales()?.link;
    if (!link) return [];
    return [
      { label: this.t('sales.field.pretixEvent'), value: link.name || link.slug },
      ...(link.incomeBudgetName ? [{ label: this.t('sales.field.incomeBudget'), value: link.incomeBudgetName }] : []),
    ];
  });

  /** One row per product, then the sums and the free places (003084). */
  protected readonly pretixRows = computed<readonly SalesRow[]>(() => {
    const p = this.sales()?.pretix;
    if (!p) return [];
    return [
      ...p.products.map((product) => ({
        label: product.name,
        value: this.t('sales.product.counts', {
          paid: product.paid,
          pending: product.pending,
          cancelled: product.cancelled,
        }),
      })),
      { label: this.t('sales.pretix.paidSum'), value: this.money(p.paidSum) },
      { label: this.t('sales.pretix.refundSum'), value: this.money(p.refundSum) },
      ...p.quotas.map((quota) => ({
        label: this.t('sales.pretix.quota', { name: quota.name }),
        value: quota.available === null ? this.t('sales.pretix.unlimited') : String(quota.available),
      })),
    ];
  });

  /** The Mollie sums and one row per settlement (003096). */
  protected readonly mollieRows = computed<readonly SalesRow[]>(() => {
    const m = this.sales()?.mollie;
    if (!m) return [];
    const sums: readonly [TranslationKey, string][] = [
      ['sales.mollie.paid', m.paid],
      ['sales.mollie.refunds', m.refunds],
      ['sales.mollie.chargebacks', m.chargebacks],
      ['sales.mollie.fees', m.fees],
      ['sales.mollie.paidOut', m.paidOut],
    ];
    return [
      ...sums.map(([key, amount]) => ({ label: this.t(key), value: this.money(amount) })),
      ...m.settlements.map((s) => ({
        label: this.t('sales.mollie.settlement', {
          reference: s.reference,
          date: s.settledAt ? formatMoment(s.settledAt, this.i18n.formatLocale()) : '–',
        }),
        value: this.money(s.amount),
      })),
    ];
  });

  /** "Stand: 28.11.2026, 07:15" of the newest read that worked. */
  protected readonly readAt = computed(() => {
    const s = this.sales();
    const at = s?.pretix?.readAt ?? s?.mollie?.readAt ?? null;
    return at ? this.t('sales.readAt', { at: formatMoment(at, this.i18n.formatLocale()) }) : '';
  });

  constructor() {
    effect(() => this.load(this.eventId()));
  }

  private load(id: string): void {
    this.api.eventSales(id).subscribe({
      next: (sales) => id === this.eventId() && this.sales.set(sales),
      error: () => this.sales.set(null),
    });
  }

  protected refresh(): void {
    const id = this.eventId();
    if (this.refreshing()) return;
    this.refreshing.set(true);
    this.api.refreshEvent(id).subscribe({
      next: (result) => {
        this.refreshing.set(false);
        this.sync.report(result);
        this.load(id);
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.refreshing.set(false);
        const code = err.error?.code;
        const key: TranslationKey =
          code === 'refresh_too_soon' ? 'sales.refresh.tooSoon' : code === 'sync_running' ? 'sales.sync.running' : 'sales.sync.failed';
        this.toast.show(this.t(key), 'error');
      },
    });
  }

  private money(value: string): string {
    return formatMoney(value, this.i18n.formatLocale());
  }

  private t(key: TranslationKey, params?: Record<string, string | number>): string {
    return this.i18n.translate(key, params);
  }
}
