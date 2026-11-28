import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { type MollieConnection, type MollieConnectionIn, SalesApiService } from '@core/api/sales.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { formatMoment } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import { causeKey } from '@shared/sales-sync';
import { InputComponent } from '@stupa-makers/ui-kit';
import {
  ScreenGroupDirective,
  SettingsScreenComponent,
  type SettingsGroup,
  type SettingsNotice,
  type SettingsState,
} from '@stupa-makers/ui-kit/screens';
import { BudgetTreeApi, type BudgetTreeNode } from '../../budget/budget-tree.api';
import { CostCentreSelectComponent } from '../../budget/cost-centre-select/cost-centre-select.component';
import { salesAdmin } from '../sales-admin';

/** What the form edits; an empty token keeps the stored one. */
export interface MollieDraft {
  readonly token: string;
  readonly feeBudgetId: string;
  readonly unassignedBudgetId: string;
}

/**
 * "Mollie" (permission `admin.mollie`, spec 003092): the read-only access token of one
 * Mollie organization, the Kostenstelle of the fees (003097) and the Kostenstelle of the
 * payments without an Event (003103). The server never returns the token. "Verbindung
 * testen" shows the name of the organization. The group "Status" shows the time of the last
 * read that worked and the cause of the last read that failed (003094). "Fehlgeschlagene
 * Buchungen" lists each booking the platform could not make, with its cause.
 */
@Component({
  selector: 'app-admin-mollie',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    SettingsScreenComponent,
    ScreenGroupDirective,
    InputComponent,
    CostCentreSelectComponent,
  ],
  templateUrl: './mollie.component.html',
})
export class MollieComponent {
  private readonly api = inject(SalesApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly budgets = inject(BudgetTreeApi);
  private readonly shared = salesAdmin({
    forbidden: 'admin.mollie.forbidden',
    loadError: 'admin.mollie.loadError',
    test: 'admin.mollie.test',
    testOk: 'admin.mollie.testOk',
    failed: 'admin.mollie.failed',
  });

  protected readonly tree = signal<readonly BudgetTreeNode[]>([]);

  protected readonly form: SettingsForm<MollieConnection, MollieDraft> = settingsForm<
    MollieConnection,
    MollieDraft,
    MollieConnectionIn
  >({
    allowed: () => this.auth.can('admin.mollie'),
    load: () => this.api.getMollie(),
    put: (body) => this.api.putMollie(body),
    draftOf: (s) => ({ token: '', feeBudgetId: s.feeBudgetId ?? '', unassignedBudgetId: s.unassignedBudgetId ?? '' }),
    initial: { token: '', feeBudgetId: '', unassignedBudgetId: '' },
    body: () => {
      const d = this.draft();
      return {
        ...(d.token ? { token: d.token } : {}),
        feeBudgetId: d.feeBudgetId || null,
        unassignedBudgetId: d.unassignedBudgetId || null,
      };
    },
    dirty: (s) => {
      const d = this.draft();
      return (
        d.token !== '' ||
        d.feeBudgetId !== (s.feeBudgetId ?? '') ||
        d.unassignedBudgetId !== (s.unassignedBudgetId ?? '')
      );
    },
  });
  protected readonly draft = this.form.draft;
  protected readonly saving = this.form.saving;
  protected readonly dirty = this.form.dirty;
  protected readonly tokenSet = computed(() => !!this.form.saved()?.tokenSet);

  protected readonly screenState = computed<SettingsState>(() =>
    this.shared.screenState(this.form.state(), () => this.form.reload()),
  );

  protected readonly notice = computed<SettingsNotice | null>(() =>
    this.shared.failedError() ? { kind: 'error', text: this.i18n.translate('admin.mollie.failedLoadError') } : null,
  );

  protected readonly groups = computed<SettingsGroup[]>(() => {
    const s = this.form.saved();
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    return [
      { key: 'connection', label: t('admin.mollie.connection'), rows: [] },
      { key: 'budgets', label: t('admin.mollie.budgets'), rows: [] },
      {
        key: 'status',
        label: t('admin.mollie.status'),
        rows: [
          { key: 'organization', label: t('admin.mollie.organization'), control: 'value' as const, value: s?.organization ?? '–' },
          {
            key: 'readOk',
            label: t('admin.mollie.readOk'),
            control: 'value' as const,
            value: s?.readOkAt ? formatMoment(s.readOkAt, this.i18n.formatLocale()) : '–',
          },
          ...(s?.readError
            ? [{ key: 'readError', label: t('admin.mollie.readError'), control: 'value' as const, value: t(causeKey(s.readError)) }]
            : []),
        ],
      },
      { key: 'actions', rows: [this.shared.testRow(!s?.tokenSet || this.dirty())] },
      ...this.shared.failedGroups(),
    ];
  });

  constructor() {
    if (!this.auth.can('admin.mollie')) return;
    this.shared.loadFailed(this.api.mollieFailed());
    this.budgets.tree().subscribe({ next: (tree) => this.tree.set(tree), error: () => undefined });
  }

  protected patch(change: Partial<MollieDraft>): void {
    this.form.patch(change);
  }

  protected act(key: string): void {
    if (key === 'test') this.shared.test(this.api.testMollie());
  }

  protected discard(): void {
    this.form.reset();
  }

  protected save(): void {
    this.form.save();
  }
}
