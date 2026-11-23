import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { erasureStatus } from '@shared/ui';
import {
  AvatarComponent,
  ButtonComponent,
  ButtonLinkComponent,
  ButtonGroupComponent,
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
  FabComponent,
  PageHeaderComponent,
  SectionComponent,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, ErasureRequest, PaperlessDocument } from '../admin.models';
import { personLabel } from '@shared/person-label.util';

/** The picker shows this many hits. A longer list means: type more. */
const PERSON_HITS = 6;

/**
 * Privacy (permission `privacy.manage`) for GDPR administration.
 *
 * - Erasure requests (Art. 17): status as coloured text, subject, e-mail, date. An open
 *   request is rejected (with an optional reason) or executed; executing erases data and
 *   is the danger action. Both ask for a confirmation.
 * - Paperless (§F/administration/privacy/002532): after an erasure with filed documents a
 *   dialog lists them with number and link, because they stay in Paperless. An executed
 *   request with documents opens the same list from its ⋮ menu.
 * - Access export (Art. 15): every record of an e-mail address as XLSX.
 * - Account erasure (Art. 17): clears the personal data of one account (danger). The
 *   person comes from a picker (name or e-mail). `?person=<sub>` preselects it; the
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
    DialogBodyDirective,
    SectionComponent,
    FabComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    ButtonLinkComponent,
    ButtonGroupComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
    InputComponent,
    PageHeaderComponent,
    BreadcrumbsComponent,
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

  /** The Paperless documents that the open dialog lists; `null`: no dialog. */
  protected readonly paperlessDocuments = signal<readonly PaperlessDocument[] | null>(null);

  protected readonly paperlessColumns = computed<ColumnDef[]>(() => [
    { key: 'title', label: this.i18n.translate('admin.privacy.paperless.col.title'), card: 'title' },
    { key: 'documentId', label: this.i18n.translate('admin.privacy.paperless.col.number'), width: '6rem' },
    { key: 'filedAt', label: this.i18n.translate('admin.privacy.paperless.col.filed'), width: '8rem' },
    {
      key: 'open',
      label: this.i18n.translate('admin.common.actions'),
      align: 'end',
      width: '6rem',
      card: 'actions',
    },
  ]);

  /** The ⋮ menu of an open request. */
  private readonly openMenu = computed<RowMenuSection[]>(() => [
    {
      items: [
        { id: 'reject', label: this.i18n.translate('admin.privacy.reject') },
        { id: 'execute', label: this.i18n.translate('admin.privacy.execute'), danger: true },
      ],
    },
  ]);

  /** The ⋮ menu of an executed request with Paperless documents. */
  private readonly paperlessMenu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'paperless', label: this.i18n.translate('admin.privacy.paperless.menu') }] },
  ]);

  /** The ⋮ menu of a request; empty: the row has no menu. */
  protected rowMenu(row: ErasureRequest): RowMenuSection[] {
    if (row.status === 'open') return this.openMenu();
    return row.status === 'executed' && row.paperlessDocuments?.length ? this.paperlessMenu() : [];
  }

  protected onRowMenu(row: ErasureRequest, item: RowMenuItem): void {
    if (item.id === 'reject') this.openReject(row);
    else if (item.id === 'execute') this.askExecute(row);
    else if (item.id === 'paperless') this.showPaperless(row.paperlessDocuments);
  }

  /** Open the list of the Paperless documents; without a document there is no dialog. */
  private showPaperless(documents: readonly PaperlessDocument[] | undefined): void {
    this.paperlessDocuments.set(documents?.length ? documents : null);
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

  /** The name of an account; "Ohne Namen" when it has neither a name nor an e-mail. */
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
      next: (done) => {
        this.confirmExecute.set(null);
        this.toast.show(this.i18n.translate('admin.privacy.executed'), 'success');
        this.showPaperless(done.paperlessDocuments);
        this.reload();
      },
      error: () => this.toast.show(this.i18n.translate('admin.common.saveFailed'), 'error'),
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
        this.toast.show(this.i18n.translate('admin.privacy.rejected'), 'success');
        this.reload();
      },
      error: () => this.toast.show(this.i18n.translate('admin.common.saveFailed'), 'error'),
    });
  }

  protected exportAuskunft(): void {
    const email = this.auskunftEmail().trim();
    if (!email) return;
    this.api.downloadAuskunft(email).subscribe({
      next: (blob) => {
        downloadBlob(blob, 'auskunft.xlsx');
        this.toast.show(this.i18n.translate('admin.privacy.auskunftDone'), 'success');
      },
      error: () => this.toast.show(this.i18n.translate('admin.common.saveFailed'), 'error'),
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
      next: (done) => {
        this.confirmPrincipal.set(false);
        this.person.set(null);
        this.toast.show(this.i18n.translate('admin.privacy.principalErased'), 'success');
        this.showPaperless(done.paperlessDocuments);
      },
      error: () => {
        this.confirmPrincipal.set(false);
        this.toast.show(this.i18n.translate('admin.common.saveFailed'), 'error');
      },
    });
  }

  /** "Verwerfen": the retention goes back to the stored value (§ui-kit:000635). */
  protected discardRetention(): void {
    this.retentionMonths.set(this.savedRetention());
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
        this.toast.show(this.i18n.translate('admin.common.saved'), 'success');
      },
      error: () => {
        this.retentionSaving.set(false);
        this.toast.show(this.i18n.translate('admin.common.saveFailed'), 'error');
      },
    });
  }
}
