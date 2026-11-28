/**
 * API of the pretix and Mollie integrations (specs 003080-003104).
 *
 * - `/admin/pretix` and `/admin/mollie`: the connections, the tests and the bookings that
 *   failed (permissions `admin.pretix`, `admin.mollie`).
 * - `/pretix/events` and `/pretix/links/{eventId}`: the picker and the link of an Event to a
 *   pretix event (`pretix.use`), and its field "Einnahmen-Kostenstelle" (`budget.book`).
 * - `/events/{id}/sales`: the section "Verkauf" of an Event and its action "Aktualisieren".
 * - `/sales-sync`: which integrations the action "Daten abrufen" reads, and the run itself.
 *
 * The server never returns a token. The client only binds the data; the server stays
 * authoritative for every right.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { IsoDateTime, Uuid } from '@core/api/models';
import { skipLoading } from '@stupa-makers/ui-kit';

/** The pretix connection without its token. */
export interface PretixConnection {
  readonly baseUrl: string | null;
  readonly organizer: string | null;
  readonly tokenSet: boolean;
  readonly showSales: boolean;
  readonly bookIncome: boolean;
  /** The hosts of the deploy setting `PRETIX_HOST_ALLOWLIST`. */
  readonly allowedHosts: readonly string[];
}

/** The body of `PUT /admin/pretix`. Without `token` the stored token stays. */
export interface PretixConnectionIn {
  readonly baseUrl: string | null;
  readonly organizer: string | null;
  readonly token?: string;
  readonly showSales: boolean;
  readonly bookIncome: boolean;
}

/** The Mollie connection without its token. */
export interface MollieConnection {
  readonly tokenSet: boolean;
  readonly organization: string | null;
  readonly feeBudgetId: Uuid | null;
  readonly unassignedBudgetId: Uuid | null;
  readonly readOkAt: IsoDateTime | null;
  readonly readError: string | null;
}

/** The body of `PUT /admin/mollie`. Without `token` the stored token stays. */
export interface MollieConnectionIn {
  readonly token?: string;
  readonly feeBudgetId: Uuid | null;
  readonly unassignedBudgetId: Uuid | null;
}

/** The result of a connection test. `error` is the cause code of a failure. */
export interface ConnectionTest {
  readonly ok: boolean;
  readonly error: string | null;
  readonly name: string | null;
}

/** A booking that the platform could not make, with its cause. */
export interface FailedBooking {
  readonly source: string;
  readonly key: string;
  readonly error: string;
  readonly at: IsoDateTime;
}

/** One event of the pretix organizer; `taken`: another Event links it. */
export interface PretixEventOption {
  readonly slug: string;
  readonly name: string;
  readonly dateFrom: string | null;
  readonly taken: boolean;
}

/** The pretix event of an Event and its field "Einnahmen-Kostenstelle". */
export interface PretixLink {
  readonly slug: string;
  readonly name: string;
  readonly dateFrom: string | null;
  readonly incomeBudgetId: Uuid | null;
  readonly incomeBudgetName: string | null;
}

export interface ProductSales {
  readonly name: string;
  readonly paid: number;
  readonly pending: number;
  readonly cancelled: number;
}

export interface QuotaFree {
  readonly name: string;
  readonly available: number | null;
}

/** The sales of the linked pretix event (003084). Amounts are decimal strings. */
export interface PretixSales {
  readonly products: readonly ProductSales[];
  readonly paidSum: string;
  readonly refundSum: string;
  readonly quotas: readonly QuotaFree[];
  readonly readAt: IsoDateTime | null;
}

export interface SettlementShare {
  readonly reference: string;
  readonly settledAt: IsoDateTime | null;
  readonly amount: string;
}

/** The Mollie money of the payments of an Event (003096). */
export interface MollieMoney {
  readonly paid: string;
  readonly refunds: string;
  readonly chargebacks: string;
  readonly fees: string;
  readonly paidOut: string;
  readonly settlements: readonly SettlementShare[];
  readonly readAt: IsoDateTime | null;
}

/** The section "Verkauf" of an Event and what the reader may do with it. */
export interface EventSales {
  readonly connected: boolean;
  readonly link: PretixLink | null;
  readonly pretix: PretixSales | null;
  readonly mollie: MollieMoney | null;
  readonly linkable: boolean;
  readonly incomeEditable: boolean;
  readonly incomeOn: boolean;
  readonly refreshable: boolean;
}

export interface SyncFailure {
  readonly integration: 'pretix' | 'mollie';
  readonly source: string;
  readonly key: string;
  readonly cause: string;
}

/** The result of a run: the new bookings and each failure (003104). */
export interface SyncResult {
  readonly booked: number;
  readonly failures: readonly SyncFailure[];
}

/** Which integrations the action "Daten abrufen" reads now. */
export interface SyncState {
  readonly pretix: boolean;
  readonly mollie: boolean;
}

@Injectable({ providedIn: 'root' })
export class SalesApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  getPretix(): Observable<PretixConnection> {
    return this.http.get<PretixConnection>(`${this.base}/admin/pretix`, { context: skipLoading() });
  }

  /** 422 `pretix_host_not_allowed` for a host the deploy does not allow. */
  putPretix(body: PretixConnectionIn): Observable<PretixConnection> {
    return this.http.put<PretixConnection>(`${this.base}/admin/pretix`, body);
  }

  testPretix(): Observable<ConnectionTest> {
    return this.http.post<ConnectionTest>(`${this.base}/admin/pretix/test`, {});
  }

  pretixFailed(): Observable<{ readonly items: readonly FailedBooking[] }> {
    return this.http.get<{ readonly items: readonly FailedBooking[] }>(
      `${this.base}/admin/pretix/failed-bookings`,
      { context: skipLoading() },
    );
  }

  getMollie(): Observable<MollieConnection> {
    return this.http.get<MollieConnection>(`${this.base}/admin/mollie`, { context: skipLoading() });
  }

  putMollie(body: MollieConnectionIn): Observable<MollieConnection> {
    return this.http.put<MollieConnection>(`${this.base}/admin/mollie`, body);
  }

  testMollie(): Observable<ConnectionTest> {
    return this.http.post<ConnectionTest>(`${this.base}/admin/mollie/test`, {});
  }

  mollieFailed(): Observable<{ readonly items: readonly FailedBooking[] }> {
    return this.http.get<{ readonly items: readonly FailedBooking[] }>(
      `${this.base}/admin/mollie/failed-bookings`,
      { context: skipLoading() },
    );
  }

  /** The events of the organizer for the picker "Pretix-Veranstaltung"; needs `pretix.use`. */
  pretixEvents(): Observable<readonly PretixEventOption[]> {
    return this.http.get<readonly PretixEventOption[]>(`${this.base}/pretix/events`, {
      context: skipLoading(),
    });
  }

  /** 409 `pretix_event_taken` when another Event links the pretix event. */
  link(eventId: Uuid, slug: string): Observable<PretixLink> {
    return this.http.put<PretixLink>(`${this.base}/pretix/links/${eventId}`, { slug });
  }

  unlink(eventId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/pretix/links/${eventId}`);
  }

  setIncomeBudget(eventId: Uuid, budgetId: Uuid | null): Observable<PretixLink> {
    return this.http.put<PretixLink>(`${this.base}/pretix/links/${eventId}/income-budget`, {
      budgetId,
    });
  }

  eventSales(eventId: Uuid): Observable<EventSales> {
    return this.http.get<EventSales>(`${this.base}/events/${eventId}/sales`, {
      context: skipLoading(),
    });
  }

  /** 429 `refresh_too_soon` within a minute of the last read, 409 `sync_running`. */
  refreshEvent(eventId: Uuid): Observable<SyncResult> {
    return this.http.post<SyncResult>(`${this.base}/events/${eventId}/sales/refresh`, {});
  }

  syncState(): Observable<SyncState> {
    return this.http.get<SyncState>(`${this.base}/sales-sync`, { context: skipLoading() });
  }

  /** The action "Daten abrufen" of the page `bookings` or `events`; 409 `sync_running`. */
  sync(page: 'bookings' | 'events'): Observable<SyncResult> {
    return this.http.post<SyncResult>(`${this.base}/sales-sync`, {}, { params: { page } });
  }
}
