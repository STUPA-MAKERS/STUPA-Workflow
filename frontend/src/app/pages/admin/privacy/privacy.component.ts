import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  CardComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { ErasureRequest } from '../admin.models';

/**
 * Admin → Datenschutz (#PII-Re-Add, P `privacy.manage`): DSGVO-Verwaltung.
 *
 * Vier Bereiche: Löschantrags-Queue (ausführen/ablehnen), Principal-Löschung
 * (Art. 17), Auskunft-Export (Art. 15, XLSX) und der globale Aufbewahrungs-Default
 * (Art. 5(1)(e)). Mutationen werden serverseitig auditiert.
 */
@Component({
  selector: 'app-admin-privacy',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    CardComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
    InputComponent,
  ],
  templateUrl: './privacy.component.html',
  styleUrl: './privacy.component.scss',
})
export class PrivacyComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  protected readonly erasures = signal<ErasureRequest[]>([]);
  protected readonly rejecting = signal<ErasureRequest | null>(null);
  protected readonly rejectReason = signal('');
  protected readonly confirmExecute = signal<ErasureRequest | null>(null);

  protected readonly auskunftEmail = signal('');
  protected readonly principalId = signal('');
  protected readonly confirmPrincipal = signal(false);

  protected readonly retentionMonths = signal<number | null>(null);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'status', label: this.i18n.translate('admin.privacy.col.status') },
    { key: 'subjectType', label: this.i18n.translate('admin.privacy.col.subject') },
    { key: 'email', label: this.i18n.translate('admin.privacy.col.email') },
    { key: 'createdAt', label: this.i18n.translate('admin.privacy.col.created') },
    { key: 'actions', label: this.i18n.translate('admin.common.actions'), align: 'end', width: '9rem' },
  ]);

  constructor() {
    this.reload();
    this.api.getPrivacySettings().subscribe((s) => this.retentionMonths.set(s.defaultRetentionMonths));
  }

  protected reload(): void {
    this.api.listErasures().subscribe((rows) => this.erasures.set(rows));
  }

  protected statusLabel(status: string): string {
    return this.i18n.translate(`admin.privacy.status.${status}` as TranslationKey);
  }

  protected subjectLabel(subject: string): string {
    return this.i18n.translate(`admin.privacy.subject.${subject}` as TranslationKey);
  }

  protected askExecute(r: ErasureRequest): void {
    this.confirmExecute.set(r);
  }

  protected doExecute(): void {
    const r = this.confirmExecute();
    if (!r) return;
    this.api.executeErasure(r.id).subscribe({
      next: () => {
        this.confirmExecute.set(null);
        this.toast.success(this.i18n.translate('admin.privacy.executed'));
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected openReject(r: ErasureRequest): void {
    this.rejectReason.set('');
    this.rejecting.set(r);
  }

  protected doReject(): void {
    const r = this.rejecting();
    if (!r) return;
    this.api.rejectErasure(r.id, this.rejectReason().trim() || null).subscribe({
      next: () => {
        this.rejecting.set(null);
        this.toast.success(this.i18n.translate('admin.privacy.rejected'));
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected exportAuskunft(): void {
    const email = this.auskunftEmail().trim();
    if (!email) return;
    this.api.downloadAuskunft(email).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'auskunft.xlsx';
        a.click();
        URL.revokeObjectURL(url);
        this.toast.success(this.i18n.translate('admin.privacy.auskunftDone'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected askPrincipalErase(): void {
    if (!this.principalId().trim()) return;
    this.confirmPrincipal.set(true);
  }

  protected doPrincipalErase(): void {
    const id = this.principalId().trim();
    if (!id) return;
    this.api.erasePrincipal(id).subscribe({
      next: () => {
        this.confirmPrincipal.set(false);
        this.principalId.set('');
        this.toast.success(this.i18n.translate('admin.privacy.principalErased'));
      },
      error: () => {
        this.confirmPrincipal.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  protected saveRetention(): void {
    const months = this.retentionMonths();
    if (months == null || months < 1) return;
    this.api.putPrivacySettings({ defaultRetentionMonths: months }).subscribe({
      next: (s) => {
        this.retentionMonths.set(s.defaultRetentionMonths);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
