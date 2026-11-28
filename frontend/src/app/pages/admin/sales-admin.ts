import { inject, signal } from '@angular/core';
import type { Observable } from 'rxjs';
import type { ConnectionTest, FailedBooking } from '@core/api/sales.service';
import { I18nService } from '@core/i18n/i18n.service';
import { formatMoment } from '@core/i18n/localized-date.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { LoadState } from '@shared/forms/settings-form';
import { causeKey } from '@shared/sales-sync';
import { ToastService } from '@stupa-makers/ui-kit';
import type { SettingsGroup, SettingsRow, SettingsState } from '@stupa-makers/ui-kit/screens';

/** The texts of one admin page of a sales integration. */
export interface SalesAdminTexts {
  readonly forbidden: TranslationKey;
  readonly loadError: TranslationKey;
  readonly test: TranslationKey;
  readonly testOk: TranslationKey;
  readonly failed: TranslationKey;
}

/**
 * What the admin pages `Pretix` and `Mollie` share (specs 003080, 003092): the screen state,
 * the action "Verbindung testen" and the group of the bookings that failed with their cause.
 * Call it in an injection context.
 */
export function salesAdmin(texts: SalesAdminTexts) {
  const i18n = inject(I18nService);
  const toast = inject(ToastService);
  const testing = signal(false);
  const failed = signal<readonly FailedBooking[]>([]);
  const failedError = signal(false);

  const t = (key: TranslationKey, params?: Record<string, string>): string => i18n.translate(key, params);

  return {
    testing,
    failed,
    failedError,

    screenState(state: LoadState, retry: () => void): SettingsState {
      switch (state) {
        case 'loading':
          return { state: 'loading' };
        case 'forbidden':
          return { state: 'forbidden', message: t(texts.forbidden) };
        case 'error':
          return { state: 'error', message: t(texts.loadError), retry };
        default:
          return { state: 'ready' };
      }
    },

    testRow(disabled: boolean): SettingsRow {
      return {
        key: 'test',
        label: t(texts.test),
        control: 'action',
        disabled: disabled || testing(),
        action: { key: 'test', label: t(texts.test) },
      };
    },

    /** The group shows only while a booking failed. */
    failedGroups(): SettingsGroup[] {
      const list = failed();
      if (!list.length) return [];
      return [
        {
          key: 'failed',
          label: t(texts.failed),
          rows: list.map((f) => ({
            key: `${f.source}:${f.key}`,
            label: f.key,
            meta: [formatMoment(f.at, i18n.formatLocale()), t(causeKey(f.error))].join(' · '),
            control: 'value' as const,
            value: '',
          })),
        },
      ];
    },

    loadFailed(read: Observable<{ readonly items: readonly FailedBooking[] }>): void {
      read.subscribe({
        next: ({ items }) => failed.set(items),
        error: () => failedError.set(true),
      });
    },

    /** The result as a toast; `ok` names the organization when the test read it. */
    test(run: Observable<ConnectionTest>): void {
      if (testing()) return;
      testing.set(true);
      run.subscribe({
        next: (result) => {
          testing.set(false);
          if (result.ok) toast.show(t(texts.testOk, { name: result.name ?? '–' }), 'success');
          else toast.show(t(causeKey(result.error)), 'error');
        },
        error: () => {
          testing.set(false);
          toast.show(t('sales.cause.unknown'), 'error');
        },
      });
    },
  };
}
