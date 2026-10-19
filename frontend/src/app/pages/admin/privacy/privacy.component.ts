import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  PageHeaderComponent,
  erasureStatus,
} from '@shared/ui';
import {
  AvatarComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  ConfirmDialogComponent,
  DataTableComponent,
  DialogComponent,
  downloadBlob,
  EmptyStateComponent,
  IconComponent,
  InputComponent,
  ListItemComponent,
  liveSearch,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SearchPillComponent,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, ErasureRequest } from '../admin.models';
import { FabComponent } from '@shared/ui/fab/fab.component';
import { personLabel } from '@shared/person-label.util';

/** The picker shows this many hits. A longer list means: type more. */
const PERSON_HITS = 6;

/**
 * Privacy (board Admin-Datenschutz, permission `privacy.manage`) for GDPR administration.
 *
 * - Erasure requests (Art. 17): status as coloured text, subject, e-mail, date. An open
 *   request is rejected (with an optional reason) or executed; executing erases data and
 *   is the danger action. Both ask for a confirmation.
 * - Access export (Art. 15): every record of an e-mail address as XLSX.
 * - Account erasure (Art. 17): clears the personal data of one account (danger). The
 *   person comes from a picker (name or e-mail, D1). `?person=<sub>` preselects it; the
 *   row action "Konto löschen (DSGVO)" in Verwaltung → Benutzer links here that way.
 * - Retention (Art. 5(1)(e)): months until a closed application is anonymized.
 *
 * The server audits every mutation.
 */
@Component({
  selector: 'app-admin-privacy',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FabComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
    InputComponent,
    PageHeaderComponent,
    SearchPillComponent,
    AvatarComponent,
    ListItemComponent,
    StatusTextComponent,
    RowMenuComponent,
  ],
  templateUrl: './privacy.component.html',
  styleUrl: './privacy.component.scss',
})
export class PrivacyComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  /**
   * True until the first answer. Without it the table shows its empty text while the
   * request is still out, which asserts there is nothing when nothing has arrived yet.
   */
  protected readonly loading = signal(true);

  protected readonly erasures = signal<ErasureRequest[]>([]);
  protected readonly rejecting = signal<ErasureRequest | null>(null);
  protected readonly rejectReason = signal('');
  protected readonly confirmExecute = signal<ErasureRequest | null>(null);

  protected readonly auskunftEmail = signal('');
  /** The account to erase, as picked. */
  protected readonly person = signal<AdminPrincipal | null>(null);
  protected readonly personHits = signal<AdminPrincipal[]>([]);
  protected readonly personSearch = liveSearch<AdminPrincipal[]>({
    run: (q) => this.api.listPrincipals(q),
    result: (list) => this.personHits.set(list.filter((p) => !p.mergedIntoId).slice(0, PERSON_HITS)),
    reset: () => this.personHits.set([]),
    error: () => this.personHits.set([]),
  });
  protected readonly confirmPrincipal = signal(false);

  protected readonly retentionMonths = signal<number | null>(null);
  /** The retention as the server has it; `retentionDirty` compares against it. */
  private readonly savedRetention = signal<number | null>(null);
  protected readonly retentionSaving = signal(false);
  /** The retention has a change that is not saved. Only then the page shows "Speichern". */
  protected readonly retentionDirty = computed(
    () => this.savedRetention() !== null && this.retentionMonths() !== this.savedRetention(),
  );

  /** The ⋮ menu of an open request. */
  protected readonly rowMenu = computed<RowMenuSection[]>(() => [
    {
      items: [
        { id: 'reject', label: this.i18n.translate('admin.privacy.reject') },
        { id: 'execute', label: this.i18n.translate('admin.privacy.execute'), danger: true },
      ],
    },
  ]);

  protected onRowMenu(row: ErasureRequest, item: RowMenuItem): void {
    if (item.id === 'reject') this.openReject(row);
    else if (item.id === 'execute') this.askExecute(row);
  }

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'status', label: this.i18n.translate('admin.privacy.col.status'), width: '8rem' },
    { key: 'subjectType', label: this.i18n.translate('admin.privacy.col.subject'), width: '7rem' },
    { key: 'email', label: this.i18n.translate('admin.privacy.col.email'), card: 'title' },
    { key: 'createdAt', label: this.i18n.translate('admin.privacy.col.created'), width: '8rem' },
    {
      key: 'actions',
      label: this.i18n.translate('admin.common.actions'),
      align: 'end',
      width: '3.5rem',
      card: 'actions',
    },
  ]);

  /** Status of a request as coloured text. */
  protected readonly erasureStatus = erasureStatus;

  constructor() {
    this.reload();
    this.api.getPrivacySettings().subscribe((s) => this.applyRetention(s.defaultRetentionMonths));
    // `?person=<sub>` comes from the row action in Verwaltung → Benutzer. The search
    // matches the `sub` too; only an exact match is taken.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((qp) => {
      const sub = qp.get('person');
      if (!sub) return;
      this.api.listPrincipals(sub).subscribe({
        next: (list) => {
          const hit = list.find((p) => p.sub === sub && !p.mergedIntoId);
          if (hit) this.person.set(hit);
        },
        error: () => undefined,
      });
    });
  }

  /** The name of an account; "Ohne Namen" when it has neither a name nor an e-mail (D7). */
  protected personName(p: AdminPrincipal): string {
    return personLabel(p, this.i18n);
  }

  protected pickPerson(p: AdminPrincipal): void {
    this.person.set(p);
    this.personSearch.clear();
  }

  protected clearPerson(): void {
    this.person.set(null);
  }

  protected reload(): void {
    this.api.listErasures().subscribe({
      next: (rows) => {
        this.erasures.set(rows);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
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
        downloadBlob(blob, 'auskunft.xlsx');
        this.toast.success(this.i18n.translate('admin.privacy.auskunftDone'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected askPrincipalErase(): void {
    if (!this.person()) return;
    this.confirmPrincipal.set(true);
  }

  protected doPrincipalErase(): void {
    const p = this.person();
    if (!p) return;
    this.api.erasePrincipal(p.id).subscribe({
      next: () => {
        this.confirmPrincipal.set(false);
        this.person.set(null);
        this.toast.success(this.i18n.translate('admin.privacy.principalErased'));
      },
      error: () => {
        this.confirmPrincipal.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  private applyRetention(months: number): void {
    this.savedRetention.set(months);
    this.retentionMonths.set(months);
  }

  /** "Speichern" and Enter in the field: send the retention. */
  protected saveRetention(): void {
    const months = this.retentionMonths();
    if (months == null || months < 1 || !this.retentionDirty() || this.retentionSaving()) return;
    this.retentionSaving.set(true);
    this.api.putPrivacySettings({ defaultRetentionMonths: months }).subscribe({
      next: (s) => {
        this.retentionSaving.set(false);
        this.applyRetention(s.defaultRetentionMonths);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => {
        this.retentionSaving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }
}
