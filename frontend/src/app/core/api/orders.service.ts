/**
 * API of the Bestellungen (`/api/applications/{id}/orders`, `/api/orders`).
 *
 * A Bestellung is one purchase at one supplier for an approved Antrag of a type with
 * money, or without an Antrag for a purchase from the time before the platform. Only a
 * person creates one. A person who reads the Antrag reads its Bestellungen;
 * the applicant reads the number, the Bezeichnung, the kind, the status and the two dates
 * only. Each write needs `order.manage`. The client only binds the data; the server
 * stays authoritative.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, map } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import { mapAttachment } from '@core/api/mappers';
import type { Attachment, AttachmentOutWire, IsoDateTime, Uuid } from '@core/api/models';
import { skipLoading } from '@stupa-makers/ui-kit';
import { httpParams } from './http-params';

/** The key of a status of the list of the Bestellungen (`StatusCatalog`, spec 003035). */
export type OrderStatus = string;
/** `order`: the Gremium buys. `outlay`: a person pays and gets the money back. */
export type OrderKind = 'order' | 'outlay';

/** One Bestellung. The applicant view holds only the fields without `?`. */
export interface Order {
  readonly id: Uuid;
  readonly number: string;
  readonly title: string;
  readonly kind: OrderKind;
  readonly status: OrderStatus;
  readonly orderedOn: string | null;
  readonly deliveredOn: string | null;
  readonly supplier?: string | null;
  readonly url?: string | null;
  readonly orderNumber?: string | null;
  readonly positionIds?: readonly string[];
  /** Decimal strings in euro. */
  readonly plannedAmount?: string | null;
  readonly actualAmount?: string | null;
  readonly buyerId?: Uuid | null;
  readonly buyerName?: string | null;
  /** The name of the account of the buyer, else the typed name. */
  readonly buyerLabel?: string | null;
  readonly note?: string | null;
  /** Null for a Bestellung without an Antrag. */
  readonly applicationId?: Uuid | null;
  readonly applicationTitle?: string | null;
  /** The invoice of the purchase; one invoice can belong to many Bestellungen. */
  readonly invoiceId?: Uuid | null;
  readonly invoiceNumber?: string | null;
  /** The status of the invoice, read from the invoice at each read. */
  readonly invoiceStatus?: 'open' | 'paid' | null;
  /** The sum of the bookings that name the Bestellung, as a decimal string. */
  readonly bookedAmount?: string;
  readonly version?: number;
  readonly createdAt?: IsoDateTime;
}

/** One Bestellung in the detail of its invoice. */
export interface InvoiceOrder {
  readonly id: Uuid;
  readonly number: string;
  readonly title: string;
  readonly applicationId: Uuid | null;
  readonly applicationTitle: string | null;
  readonly actualAmount: string | null;
}

/** The Bestellungen that name one invoice, with the sum of their real prices. */
export interface InvoiceOrders {
  readonly items: readonly InvoiceOrder[];
  readonly total: string;
}

/** The Bestellungen of one Antrag. The sums are null in the applicant view. */
export interface OrderList {
  readonly items: readonly Order[];
  readonly total: string | null;
  readonly approvedAmount: string | null;
  /** By how much the sum is above the approved amount, else null. */
  readonly overBy: string | null;
  readonly canManage: boolean;
  readonly canCreate: boolean;
}

/** The fields of a create or a change. A change sends only the fields it sets. */
export interface OrderInput {
  readonly title?: string;
  readonly kind?: OrderKind;
  readonly supplier?: string | null;
  readonly url?: string | null;
  readonly orderNumber?: string | null;
  readonly positionIds?: readonly string[];
  readonly plannedAmount?: string | null;
  readonly actualAmount?: string | null;
  readonly orderedOn?: string | null;
  readonly deliveredOn?: string | null;
  readonly buyerId?: Uuid | null;
  readonly buyerName?: string | null;
  readonly note?: string | null;
}

/** The segments of the page "Bestellungen"; `pending` lists Anträge without a Bestellung. */
export type OrderSegment = 'pending' | 'open' | 'delivered' | 'done';
export const ORDER_SEGMENTS: readonly OrderSegment[] = ['pending', 'open', 'delivered', 'done'];

/** The filter of the page "Bestellungen". An empty value is no filter. */
export interface OrderQuery {
  readonly segment?: Exclude<OrderSegment, 'pending'>;
  readonly fiscalYear?: string;
  readonly budget?: string;
  readonly gremium?: string;
  readonly kind?: string;
  readonly buyer?: string;
  readonly q?: string;
  /** Only the Bestellungen without an Antrag. */
  readonly withoutApplication?: boolean;
  readonly limit?: number;
  readonly offset?: number;
}

/** One page of Bestellungen, the newest change first. */
export interface OrderPage {
  readonly items: readonly Order[];
  readonly total: number;
}

/** An approved Antrag of a type with money, for the segment "Ohne Bestellung" and the form. */
export interface PendingApplication {
  readonly id: Uuid;
  readonly title: string | null;
  readonly gremiumId: Uuid | null;
  readonly gremiumName: string | null;
  readonly approvedAmount: string | null;
}

export interface PendingPage {
  readonly items: readonly PendingApplication[];
  readonly total: number;
}

/** One booking that names a Bestellung. */
export interface OrderBooking {
  readonly id: Uuid;
  readonly description: string | null;
  readonly amount: string;
}

@Injectable({ providedIn: 'root' })
export class OrdersApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  list(applicationId: Uuid): Observable<OrderList> {
    return this.http.get<OrderList>(`${this.base}/applications/${applicationId}/orders`, {
      context: skipLoading(),
    });
  }

  /** The Bestellungen that the person reads; `order.manage` or a read permission of the Haushalt. */
  page(query: OrderQuery = {}): Observable<OrderPage> {
    return this.http.get<OrderPage>(`${this.base}/orders`, {
      params: httpParams({ ...query }),
      context: skipLoading(),
    });
  }

  /**
   * The approved Anträge of a type with money without a Bestellung. `withOrders` gives
   * those with a Bestellung too, for the form of a new Bestellung.
   */
  pending(query: OrderQuery = {}, withOrders = false): Observable<PendingPage> {
    return this.http.get<PendingPage>(`${this.base}/orders/pending-applications`, {
      params: httpParams({ ...query, segment: undefined, ...(withOrders ? { withOrders: true } : {}) }),
      context: skipLoading(),
    });
  }

  /** The Bestellungen of a filter as an XLSX file; needs `finance.export`. */
  exportXlsx(query: OrderQuery = {}): Observable<Blob> {
    return this.http.get(`${this.base}/orders/export.xlsx`, {
      params: httpParams({ ...query, limit: undefined, offset: undefined }),
      responseType: 'blob',
    });
  }

  /** The bookings that name a Bestellung; needs a read right of the budget. */
  bookings(id: Uuid): Observable<readonly OrderBooking[]> {
    return this.http.get<readonly OrderBooking[]>(`${this.base}/orders/${id}/bookings`, {
      context: skipLoading(),
    });
  }

  /** One Bestellung; 404 without the read of its Antrag. */
  get(id: Uuid): Observable<Order> {
    return this.http.get<Order>(`${this.base}/orders/${id}`, { context: skipLoading() });
  }

  /**
   * Set the invoice of a Bestellung, or remove it with `null`. The gross amount of the
   * invoice fills an empty real price when no other Bestellung names the invoice.
   */
  setInvoice(id: Uuid, invoiceId: Uuid | null, version: number): Observable<Order> {
    return this.http.put<Order>(`${this.base}/orders/${id}/invoice`, { invoiceId, version });
  }

  /** The Bestellungen that name an invoice. */
  ofInvoice(invoiceId: Uuid): Observable<InvoiceOrders> {
    return this.http.get<InvoiceOrders>(`${this.base}/invoices/${invoiceId}/orders`, {
      context: skipLoading(),
    });
  }

  /**
   * 409 `application_not_approved`, 422 `application_type_without_budget`. Without an
   * Antrag the Bestellung has none, and 422 `positions_need_application` refuses positions.
   */
  create(applicationId: Uuid | null, body: OrderInput): Observable<Order> {
    const path = applicationId ? `/applications/${applicationId}/orders` : '/orders';
    return this.http.post<Order>(`${this.base}${path}`, body);
  }

  /** 409 `order_version_conflict` when `version` is not the stored one. */
  update(id: Uuid, version: number, body: OrderInput): Observable<Order> {
    return this.http.patch<Order>(`${this.base}/orders/${id}`, { ...body, version });
  }

  setStatus(id: Uuid, status: OrderStatus, version: number): Observable<Order> {
    return this.http.post<Order>(`${this.base}/orders/${id}/status`, { status, version });
  }

  remove(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/orders/${id}`);
  }

  /** The files of a Bestellung. They are no attachments of the Antrag. */
  files(id: Uuid): Observable<readonly Attachment[]> {
    return this.http
      .get<readonly AttachmentOutWire[]>(`${this.base}/orders/${id}/attachments`, {
        context: skipLoading(),
      })
      .pipe(map((rows) => rows.map(mapAttachment)));
  }

  uploadFile(id: Uuid, file: File): Observable<Attachment> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http
      .post<AttachmentOutWire>(`${this.base}/orders/${id}/attachments`, form)
      .pipe(map(mapAttachment));
  }

  removeFile(id: Uuid, attachmentId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/orders/${id}/attachments/${attachmentId}`);
  }
}
