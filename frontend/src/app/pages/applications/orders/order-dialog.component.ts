import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import type { Observable } from 'rxjs';
import { CalendarApiService } from '@core/api/calendar.service';
import type { Uuid } from '@core/api/models';
import { type Order, OrdersApiService } from '@core/api/orders.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  type Action,
  ChipComponent,
  DialogBodyDirective,
  DialogComponent,
  ErrorTextComponent,
  FactsComponent,
  type FormDef,
  SectionComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { FormComponent, type FormValue } from '@stupa-makers/ui-kit/screens';
import {
  GremiumPersonPickerComponent,
  type PickerHit,
  type PickerPerson,
} from '../../../features/gremien/gremium-person-picker/gremium-person-picker.component';
import { OrderFilesComponent } from './order-files.component';
import {
  type OrderPosition,
  orderBody,
  orderFacts,
  orderFormValue,
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

/** The refusals of the server that the dialog shows as a toast. */
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

const sameIds = (a: unknown, b: unknown): boolean =>
  Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((id) => b.includes(id));

/**
 * "Bestellung anlegen" and "Bestellung bearbeiten": the form of one purchase of an Antrag.
 *
 * When the person picks positions of the Kostenaufstellung, the form sets the planned
 * price to the sum of their preferred offers and, with exactly one position, the link to
 * the first address in the text of its preferred offer. A value that the person typed
 * stays. A position that another Bestellung holds is not offered.
 *
 * The buyer is an account (the search) or a typed name. The files of the Bestellung show
 * below the form once the Bestellung exists.
 *
 * A person without `order.manage` (`canManage` false) reads the Bestellung: its values as
 * a list of facts and its files, without the form.
 */
@Component({
  selector: 'app-order-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ChipComponent,
    DialogBodyDirective,
    DialogComponent,
    ErrorTextComponent,
    FactsComponent,
    FormComponent,
    SectionComponent,
    GremiumPersonPickerComponent,
    OrderFilesComponent,
  ],
  templateUrl: './order-dialog.component.html',
})
export class OrderDialogComponent {
  private readonly api = inject(OrdersApiService);
  private readonly calendar = inject(CalendarApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly formRef = viewChild(FormComponent);

  readonly open = model(false);
  readonly applicationId = input<Uuid | null>(null);
  /** The Bestellung to change, or null for a new one. */
  readonly order = input<Order | null>(null);
  /** Every Bestellung of the Antrag: a position of another one is not offered. */
  readonly orders = input<readonly Order[]>([]);
  readonly positions = input<readonly OrderPosition[]>([]);
  /** False: the dialog shows the Bestellung and takes no change. */
  readonly canManage = input(true);
  readonly currency = input<string | null>(null);

  /** The Bestellung was saved: the caller loads again. */
  readonly saved = output<Order>();
  /** The server holds a newer version: the caller loads again. */
  readonly stale = output<void>();

  protected readonly value = signal<FormValue>(orderFormValue(null));
  protected readonly buyer = signal<PickerPerson | null>(null);
  protected readonly saving = signal(false);
  protected readonly errors = signal<Readonly<Record<string, string>>>({});
  protected readonly buyerError = signal('');
  private readonly auto = signal<Auto>(NO_AUTO);

  protected readonly findPeople = (q: string): Observable<readonly PickerPerson[]> =>
    this.calendar.people(q);

  /** The positions that the form offers: not those of another Bestellung. */
  protected readonly offered = computed(() => {
    const taken = takenPositions(this.orders(), this.order()?.id ?? null);
    return this.positions().filter((p) => !taken.has(p.id));
  });

  protected readonly form = computed<FormDef>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const known = new Set(this.positions().map((p) => p.id));
    const gone = ((this.value()['positionIds'] as readonly string[] | undefined) ?? [])
      .filter((id) => !known.has(id))
      .map((id) => ({ value: id, label: t('orders.position.removed') }));
    const options = [...this.offered().map((p) => ({ value: p.id, label: p.label })), ...gone];
    return {
      sections: [
        {
          key: 'order',
          fields: [
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

  protected readonly actions = computed<Action[]>(() =>
    this.canManage()
      ? [
          { key: 'cancel', label: this.i18n.translate('action.cancel') },
          {
            key: 'save',
            label: this.i18n.translate('action.save'),
            kind: 'main',
            busy: this.saving(),
          },
        ]
      : [{ key: 'cancel', label: this.i18n.translate('action.close') }],
  );

  protected readonly heading = computed(() => {
    const order = this.order();
    if (!order) return this.i18n.translate('orders.dialog.create');
    return this.canManage() ? this.i18n.translate('orders.dialog.edit') : order.title;
  });

  /** The values of the Bestellung for a person who only reads it. */
  protected readonly facts = computed(() => {
    const order = this.order();
    return order
      ? orderFacts(
          order,
          this.positions(),
          this.i18n.formatLocale(),
          this.currency(),
          (key) => this.i18n.translate(key),
        )
      : [];
  });

  constructor() {
    effect(() => {
      if (!this.open()) return;
      const order = this.order();
      untracked(() => {
        this.saving.set(false);
        this.errors.set({});
        this.buyerError.set('');
        this.auto.set(NO_AUTO);
        this.value.set(orderFormValue(order));
        this.buyer.set(
          order?.buyerId ? { id: order.buyerId, name: order.buyerLabel ?? '' } : null,
        );
      });
    });
  }

  /** A change of the picked positions fills the planned price and the link (see the class). */
  protected onValue(next: FormValue): void {
    this.buyerError.set('');
    this.errors.set({});
    if (sameIds(next['positionIds'], this.value()['positionIds'])) {
      this.value.set(next);
      return;
    }
    const ids = (next['positionIds'] as readonly string[] | undefined) ?? [];
    const fill = positionPrefill(this.positions().filter((p) => ids.includes(p.id)));
    const auto = this.auto();
    const price = next['plannedAmount'];
    const priceOpen = price === null || price === '' || Number(price) === auto.plannedAmount;
    const urlOpen = !next['url'] || next['url'] === auto.url;
    this.auto.set(fill);
    this.value.set({
      ...next,
      ...(priceOpen ? { plannedAmount: fill.plannedAmount } : {}),
      ...(urlOpen ? { url: fill.url } : {}),
    });
  }

  protected onPicked(hit: PickerHit): void {
    if (hit.kind === 'person') this.buyer.set({ id: hit.id, name: hit.name });
  }

  protected onAction(key: string): void {
    if (key === 'cancel') this.open.set(false);
    else this.save();
  }

  protected save(): void {
    const applicationId = this.applicationId();
    const formOk = this.formRef()?.showErrors() !== false;
    if (this.saving() || !formOk || !applicationId) return;
    const order = this.order();
    const body = orderBody(this.value(), this.buyer()?.id ?? null);
    this.saving.set(true);
    const request = order
      ? this.api.update(order.id, order.version ?? 1, body)
      : this.api.create(applicationId, body);
    request.subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.open.set(false);
        this.saved.emit(saved);
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.saving.set(false);
        this.refused(err.error?.code ?? '');
      },
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
      return;
    }
    this.toast.show(this.i18n.translate(TOAST_ERROR[code] ?? 'orders.error.save'), 'error');
    if (code === 'order_version_conflict') {
      this.open.set(false);
      this.stale.emit();
    }
  }
}
