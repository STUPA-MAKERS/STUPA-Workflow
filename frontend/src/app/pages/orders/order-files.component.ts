import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import type { Attachment, Uuid } from '@core/api/models';
import { OrdersApiService } from '@core/api/orders.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { scanStatus } from '@shared/status-kind.util';
import {
  ButtonComponent,
  ButtonGroupComponent,
  ConfirmDialogComponent,
  EmptyStateComponent,
  FieldGroupComponent,
  FilePickerComponent,
  IconComponent,
  ListItemComponent,
  MetaLineComponent,
  SectionComponent,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { formatBytes } from '../applications/applications.util';

/** The text of a refused upload, by the status of the answer. */
const UPLOAD_ERROR: Readonly<Record<number, TranslationKey>> = {
  413: 'applications.attachments.error.tooLarge',
  415: 'applications.attachments.error.type',
  429: 'applications.attachments.error.rate',
  503: 'applications.attachments.error.storage',
};

/**
 * The files of one Bestellung, for example the confirmation of the order.
 *
 * They are files of the Bestellung and no attachments of the Antrag, so the attachments
 * list of the Antrag does not show them. A person who reads the Bestellung reads and
 * downloads them with a click on the row; the upload and the delete need `order.manage` (`canManage`). A file
 * downloads only after a clean scan. Several files upload one after the other, because
 * parallel requests trip the rate limit.
 */
@Component({
  selector: 'app-order-files',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    FieldGroupComponent,
    FilePickerComponent,
    IconComponent,
    ListItemComponent,
    MetaLineComponent,
    SectionComponent,
    StatusTextComponent,
  ],
  templateUrl: './order-files.component.html',
})
export class OrderFilesComponent {
  private readonly orders = inject(OrdersApiService);
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly orderId = input.required<Uuid>();
  readonly canManage = input(false);

  protected readonly files = signal<readonly Attachment[]>([]);
  protected readonly uploading = signal(false);
  protected readonly busyId = signal<Uuid | null>(null);
  /** The file that the open confirmation deletes. */
  protected readonly confirming = signal<Attachment | null>(null);
  protected readonly scan = scanStatus;

  constructor() {
    effect(() => {
      const id = this.orderId();
      this.files.set([]);
      this.orders.files(id).subscribe({
        next: (list) => this.files.set(list),
        error: () => this.files.set([]),
      });
    });
  }

  protected size(file: Attachment): string {
    return formatBytes(file.size, this.i18n.locale());
  }

  /** Several files upload one after the other; the first refusal ends the row of uploads. */
  protected upload(picked: readonly File[]): void {
    if (!this.canManage() || this.uploading() || !picked.length) return;
    this.uploading.set(true);
    from(picked)
      .pipe(concatMap((file) => this.orders.uploadFile(this.orderId(), file)))
      .subscribe({
        next: (file) => this.files.update((list) => [...list, file]),
        error: (err: { status?: number }) => {
          this.uploading.set(false);
          this.toast.show(
            this.i18n.translate(
              UPLOAD_ERROR[err.status ?? 0] ?? 'applications.attachments.error.upload',
            ),
            'error',
          );
        },
        complete: () => this.uploading.set(false),
      });
  }

  /** A file downloads only after a clean scan. */
  protected download(file: Attachment): void {
    if (this.busyId() || file.scanState !== 'clean') return;
    this.busyId.set(file.id);
    this.api.attachmentUrl(file.id).subscribe({
      next: (signed) => {
        this.busyId.set(null);
        this.openUrl(signed.url);
      },
      error: () => {
        this.busyId.set(null);
        this.toast.show(this.i18n.translate('applications.attachments.download.error'), 'error');
      },
    });
  }

  protected remove(): void {
    const file = this.confirming();
    if (!file || this.busyId()) return;
    this.busyId.set(file.id);
    this.orders.removeFile(this.orderId(), file.id).subscribe({
      next: () => {
        this.files.update((list) => list.filter((f) => f.id !== file.id));
        this.busyId.set(null);
        this.confirming.set(null);
      },
      error: () => {
        this.busyId.set(null);
        this.confirming.set(null);
        this.toast.show(this.i18n.translate('applications.attachments.deleteError'), 'error');
      },
    });
  }

  /** A separate method, so a test can replace it. */
  protected openUrl(url: string): void {
    window.open(url, '_blank', 'noopener');
  }
}
