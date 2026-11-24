import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import type { Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { CalendarApiService } from '@core/api/calendar.service';
import type { Application, Uuid } from '@core/api/models';
import {
  type Order,
  type OrderList,
  OrdersApiService,
  type PendingApplication,
} from '@core/api/orders.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { formatMoney } from '@shared/format-money';
import {
  ChipComponent,
  ErrorTextComponent,
  type FieldDef,
  type FormDef,
  SectionComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { FormScreenComponent, type FormValue } from '@stupa-makers/ui-kit/screens';
import {
  GremiumPersonPickerComponent,
  type PickerHit,
  type PickerPerson,
} from '../../features/gremien/gremium-person-picker/gremium-person-picker.component';
import { applicationTitle } from '../applications/applications.util';
import { OrdersRefresh } from './orders-refresh';
import {
  orderBody,
  orderFormValue,
  orderPositions,
  positionPrefill,
  takenPositions,
} from './orders.util';

/** The refusals of the server that belong to one field of the form. */
const FIELD_ERROR: Readonly<Record<string, readonly [string, TranslationKey]>> = {
  order_url_invalid: ['url', 'orders.error.url'],
  order_title_required: ['title', 'orders.error.title'],
  order_position_taken: ['positionIds', 'orders.error.positionTaken'],
  order_position_unknown: ['positionIds', 'orders.error.positionUnknown'],
};

/** The refusals of the server that the form shows as a toast. */
const TOAST_ERROR: Readonly<Record<string, TranslationKey>> = {
  order_version_conflict: 'orders.error.version',
  application_not_approved: 'orders.error.notApproved',
  application_type_without_budget: 'orders.error.noBudget',
};

/** What the form filled by itself; a field with another value was typed by the person. */
interface Auto {
  readonly plannedAmount: number | null;
  readonly url: string;
}

const NO_AUTO: Auto = { plannedAmount: null, url: '' };

/** How many Anträge the choice of the empty form offers. */
const OFFERED_APPLICATIONS = 200;

const sameIds = (a: unknown, b: unknown): boolean =>
  Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((id) => b.includes(id));

/**
 * "Bestellung anlegen" and "Bestellung bearbeiten" in the pane of the page "Bestellungen".
 *
 * A new Bestellung belongs to an approved Antrag of a type with money: the address names
 * it (`?application=<id>`), or the person picks it in the first field. When the person
 * picks positions of the Kostenaufstellung, the form sets the planned price to the sum of
 * their preferred offers and, with exactly one position, the link to the first address in
 * the text of its preferred offer. A value that the person typed stays. A position that
 * another Bestellung holds is not offered. The form shows the sum of the Bestellungen of
 * the Antrag and its approved amount; a sum above it warns and blocks nothing.
 *
 * The buyer is an account (the search below the form) or a typed name. In the form of an
 * existing Bestellung the pick of an account saves at once, because the save button of
 * the form shows only for a change of a field.
 */
@Component({
  selector: 'app-order-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ChipComponent,
    ErrorTextComponent,
    FormScreenComponent,
    GremiumPersonPickerComponent,
    SectionComponent,
  ],
  templateUrl: './order-form.component.html',
})
export class OrderFormComponent {
  private readonly api = inject(OrdersApiService);
  private readonly client = inject(ApiClient);
  private readonly calendar = inject(CalendarApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly refresh = inject(OrdersRefresh);

  /** The Bestellung to change, or null for a new one. */
  protected readonly order = signal<Order | null>(null);
  /** The Antrag that the address names; the form then has no choice of an Antrag. */
  private readonly fixedApplication = signal<Uuid | null>(null);
  private readonly applications = signal<readonly PendingApplication[]>([]);
  private readonly application = signal<Application | null>(null);
  private readonly list = signal<OrderList | null>(null);
  protected readonly value = signal<FormValue>(orderFormValue(null));
  protected readonly buyer = signal<PickerPerson | null>(null);
  protected readonly saving = signal(false);
  protected readonly errors = signal<Readonly<Record<string, string>>>({});
  protected readonly buyerError = signal('');
  private readonly auto = signal<Auto>(NO_AUTO);
  private loadedFor: string | null = null;

  protected readonly findPeople = (q: string): Observable<readonly PickerPerson[]> =>
    this.calendar.people(q);

  protected readonly editing = computed(() => this.order() !== null);
  protected readonly title = computed(() =>
    this.i18n.translate(this.editing() ? 'orders.dialog.edit' : 'orders.dialog.create'),
  );

  private readonly applicationId = computed<Uuid | null>(
    () =>
      this.order()?.applicationId ??
      this.fixedApplication() ??
      (String(this.value()['applicationId'] ?? '') || null),
  );

  private readonly positions = computed(() => orderPositions(this.application()?.data));

  /** The sum of the Bestellungen of the Antrag against its approved amount, or a warning. */
  private readonly sumText = computed(() => {
    const list = this.list();
    if (!list || list.total === null) return '';
    const money = (amount: unknown): string =>
      formatMoney(amount, this.i18n.formatLocale(), { currency: this.application()?.currency });
    const approved = money(list.approvedAmount);
    const sum = approved
      ? this.i18n.translate('orders.section.sumOfApproved', { total: money(list.total), approved })
      : money(list.total);
    const over = money(list.overBy);
    return over ? `${sum}. ${this.i18n.translate('orders.section.over', { amount: over })}` : sum;
  });

  protected readonly form = computed<FormDef>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const known = new Set(this.positions().map((p) => p.id));
    const taken = takenPositions(this.list()?.items ?? [], this.order()?.id ?? null);
    const gone = ((this.value()['positionIds'] as readonly string[] | undefined) ?? [])
      .filter((id) => !known.has(id))
      .map((id) => ({ value: id, label: t('orders.position.removed') }));
    const options = [
      ...this.positions()
        .filter((p) => !taken.has(p.id))
        .map((p) => ({ value: p.id, label: p.label })),
      ...gone,
    ];
    const antrag: readonly FieldDef[] = this.editing()
      ? []
      : this.fixedApplication()
        ? [
            {
              key: 'applicationName',
              kind: 'display',
              label: t('orders.field.application'),
              text: this.applicationTitle(),
            },
          ]
        : [
            {
              key: 'applicationId',
              kind: 'select',
              label: t('orders.field.application'),
              required: true,
              search: true,
              options: this.applications().map((a) => ({
                value: a.id,
                label: [a.title || t('applications.list.untitled'), a.gremiumName].filter(Boolean).join(' · '),
              })),
            },
          ];
    return {
      sections: [
        {
          key: 'order',
          fields: [
            ...antrag,
            { key: 'title', kind: 'text', label: t('orders.field.title'), required: true, maxLength: 200 },
            {
              key: 'kind',
              kind: 'select',
              label: t('orders.field.kind'),
              required: true,
              width: 'half',
              options: [
                { value: 'order', label: t('orders.kind.order') },
                { value: 'outlay', label: t('orders.kind.outlay') },
              ],
            },
            { key: 'supplier', kind: 'text', label: t('orders.field.supplier'), maxLength: 200, width: 'half' },
            {
              key: 'positionIds',
              kind: 'multi-select',
              label: t('orders.field.positions'),
              options,
              visible: options.length > 0,
            },
            { key: 'url', kind: 'url', label: t('orders.field.url'), maxLength: 2000 },
            { key: 'plannedAmount', kind: 'money', label: t('orders.field.planned'), min: 0, width: 'half' },
            { key: 'actualAmount', kind: 'money', label: t('orders.field.actual'), min: 0, width: 'half' },
            {
              key: 'sum',
              kind: 'display',
              label: t('orders.detail.sumTitle'),
              text: this.sumText(),
              visible: this.sumText() !== '',
            },
            { key: 'orderNumber', kind: 'text', label: t('orders.field.orderNumber'), maxLength: 100 },
            { key: 'orderedOn', kind: 'date', label: t('orders.field.orderedOn'), width: 'half' },
            { key: 'deliveredOn', kind: 'date', label: t('orders.field.deliveredOn'), width: 'half' },
            { key: 'note', kind: 'textarea', label: t('orders.field.note'), maxLength: 2000 },
            {
              key: 'buyerName',
              kind: 'text',
              label: t('orders.field.buyerName'),
              maxLength: 200,
              visible: !this.buyer(),
            },
          ],
        },
      ],
    };
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      const id = params.get('id');
      const preset = this.route.snapshot.queryParamMap.get('application');
      this.order.set(null);
      this.application.set(null);
      this.list.set(null);
      this.loadedFor = null;
      this.buyer.set(null);
      this.auto.set(NO_AUTO);
      this.errors.set({});
      this.value.set(orderFormValue(null));
      this.fixedApplication.set(id ? null : preset);
      if (id) this.loadOrder(id);
      else if (preset) this.loadApplication(preset);
      else this.loadChoice();
    });
  }

  private applicationTitle(): string {
    return applicationTitle(this.application()?.data, this.i18n.translate('applications.list.untitled'));
  }

  private loadOrder(id: string): void {
    this.api.get(id).subscribe({
      next: (order) => {
        this.order.set(order);
        this.value.set(orderFormValue(order));
        this.buyer.set(order.buyerId ? { id: order.buyerId, name: order.buyerLabel ?? '' } : null);
        if (order.applicationId) this.loadApplication(order.applicationId);
      },
      error: () => {
        this.toast.show(this.i18n.translate('orders.error.load'), 'error');
        this.close();
      },
    });
  }

  /** The Anträge that can take a Bestellung, for the choice of the empty form. */
  private loadChoice(): void {
    this.api.pending({ limit: OFFERED_APPLICATIONS }, true).subscribe({
      next: (page) => this.applications.set(page.items),
      error: () => undefined,
    });
  }

  /** The positions and the other Bestellungen of the Antrag. A failed read leaves them out. */
  private loadApplication(id: Uuid): void {
    if (this.loadedFor === id) return;
    this.loadedFor = id;
    this.application.set(null);
    this.list.set(null);
    this.client.getApplication(id, { quiet: true }).subscribe({
      next: (application) => this.loadedFor === id && this.application.set(application),
      error: () => undefined,
    });
    this.api.list(id).subscribe({
      next: (list) => this.loadedFor === id && this.list.set(list),
      error: () => undefined,
    });
  }

  /** A change of the picked positions fills the planned price and the link (see the class). */
  protected onValue(next: FormValue): void {
    this.buyerError.set('');
    this.errors.set({});
    const picked = String(next['applicationId'] ?? '');
    if (picked && picked !== this.loadedFor && !this.editing()) this.loadApplication(picked);
    if (sameIds(next['positionIds'], this.value()['positionIds'])) {
      this.value.set(next);
      return;
    }
    const ids = (next['positionIds'] as readonly string[] | undefined) ?? [];
    const fill = positionPrefill(this.positions().filter((p) => ids.includes(p.id)));
    const auto = this.auto();
    const price = next['plannedAmount'];
    const priceOpen = price === null || price === undefined || price === '' || Number(price) === auto.plannedAmount;
    const urlOpen = !next['url'] || next['url'] === auto.url;
    this.auto.set(fill);
    this.value.set({
      ...next,
      ...(priceOpen ? { plannedAmount: fill.plannedAmount } : {}),
      ...(urlOpen ? { url: fill.url } : {}),
    });
  }

  protected onPicked(hit: PickerHit): void {
    if (hit.kind === 'person') this.setBuyer({ id: hit.id, name: hit.name });
  }

  /** Set or remove the account of the buyer; an existing Bestellung saves it at once. */
  protected setBuyer(person: PickerPerson | null): void {
    const before = this.buyer();
    const order = this.order();
    this.buyerError.set('');
    this.buyer.set(person);
    if (!order) return;
    this.api.update(order.id, order.version ?? 1, { buyerId: person?.id ?? null }).subscribe({
      next: (saved) => {
        this.order.set(saved);
        this.refresh.touch();
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.buyer.set(before);
        this.refused(err.error?.code ?? '');
      },
    });
  }

  protected save(value: FormValue): void {
    const applicationId = this.applicationId();
    if (this.saving() || !applicationId) return;
    const order = this.order();
    const body = orderBody(value, this.buyer()?.id ?? null);
    this.saving.set(true);
    const request = order
      ? this.api.update(order.id, order.version ?? 1, body)
      : this.api.create(applicationId, body);
    request.subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.refresh.touch();
        void this.router.navigate(['/orders', saved.id], { queryParams: { application: null }, queryParamsHandling: 'merge' });
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.saving.set(false);
        this.refused(err.error?.code ?? '');
      },
    });
  }

  /** "Abbrechen": back to the Bestellung, or to the list from a new one. */
  protected close(): void {
    const order = this.order();
    void this.router.navigate(order ? ['/orders', order.id] : ['/orders'], {
      queryParams: { application: null },
      queryParamsHandling: 'merge',
    });
  }

  private refused(code: string): void {
    const field = FIELD_ERROR[code];
    if (field) {
      this.errors.set({ [field[0]]: this.i18n.translate(field[1]) });
      return;
    }
    if (code === 'order_buyer_required' || code === 'order_buyer_unknown') {
      this.buyerError.set(this.i18n.translate('orders.error.buyer'));
      this.errors.set({ buyerName: this.i18n.translate('orders.error.buyer') });
      return;
    }
    this.toast.show(this.i18n.translate(TOAST_ERROR[code] ?? 'orders.error.save'), 'error');
    if (code === 'order_version_conflict') this.close();
  }
}
