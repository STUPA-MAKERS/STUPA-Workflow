import { Injectable, inject, signal } from '@angular/core';
import { type SyncFailure, type SyncResult, SalesApiService } from '@core/api/sales.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { ToastService } from '@stupa-makers/ui-kit';

/** The sentence of each cause code of a failed read or booking of pretix and Mollie. */
const CAUSE_TEXT: Readonly<Record<string, TranslationKey>> = {
  not_configured: 'sales.cause.notConfigured',
  blocked: 'sales.cause.blocked',
  timeout: 'sales.cause.timeout',
  unreachable: 'sales.cause.unreachable',
  redirect: 'sales.cause.redirect',
  unauthorized: 'sales.cause.unauthorized',
  not_found: 'sales.cause.notFound',
  status: 'sales.cause.status',
  format: 'sales.cause.format',
  no_actor: 'sales.cause.noActor',
  invalid: 'sales.cause.invalid',
  fiscal_year_closed: 'sales.cause.fiscalYearClosed',
  cost_centre_not_leaf: 'sales.cause.notLeaf',
};

/** The sentence of a cause code; an unknown code reads as an unknown failure. */
export function causeKey(code: string | null): TranslationKey {
  return CAUSE_TEXT[code ?? ''] ?? 'sales.cause.unknown';
}

/**
 * The action "Daten abrufen" of the pages "Buchungen" and "Veranstaltungen" (spec 003104).
 *
 * `load()` asks once which integrations are on and configured; the action shows only while
 * one is. `run()` starts the read and shows its result as a toast: the number of new
 * bookings and each failure with its cause. A second press during a run does nothing, and a
 * run of another person answers 409 `sync_running`.
 */
@Injectable({ providedIn: 'root' })
export class SalesSyncAction {
  private readonly api = inject(SalesApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** At least one integration is on and configured. */
  readonly available = signal(false);
  /** A run is in flight. */
  readonly running = signal(false);

  load(): void {
    this.api.syncState().subscribe({
      next: (state) => this.available.set(state.pretix || state.mollie),
      error: () => this.available.set(false),
    });
  }

  run(page: 'bookings' | 'events', done?: () => void): void {
    if (this.running()) return;
    this.running.set(true);
    this.api.sync(page).subscribe({
      next: (result) => {
        this.running.set(false);
        this.report(result);
        done?.();
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.running.set(false);
        const busy = err.error?.code === 'sync_running';
        this.toast.show(this.i18n.translate(busy ? 'sales.sync.running' : 'sales.sync.failed'), 'error');
      },
    });
  }

  /** "2 neue Buchungen" and one line per failure. */
  report(result: SyncResult): void {
    const booked = this.i18n.translate(result.booked === 1 ? 'sales.sync.booked.one' : 'sales.sync.booked.other', {
      count: result.booked,
    });
    const failures = result.failures.map((f) => this.failureText(f));
    this.toast.show([booked, ...failures].join(' · '), failures.length ? 'error' : 'success');
  }

  private failureText(f: SyncFailure): string {
    return this.i18n.translate('sales.sync.failure', {
      integration: this.i18n.translate(f.integration === 'pretix' ? 'sales.integration.pretix' : 'sales.integration.mollie'),
      key: f.key,
      cause: this.i18n.translate(causeKey(f.cause)),
    });
  }
}
