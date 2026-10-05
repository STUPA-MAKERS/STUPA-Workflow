import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { scanStatus } from '@shared/status-kind.util';
import { FileDropZoneComponent } from '@shared/ui/file-drop-zone/file-drop-zone.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { BadgeComponent, CheckboxComponent, IconComponent, ToastService } from '@stupa-makers/ui-kit';
import { FormsModule } from '@angular/forms';
import { formatSize, UPLOAD_ACCEPT } from '../apply.util';
import { DraftAttachmentsService, type DraftFile } from '../draft-attachments.service';

/**
 * The draft files of one field of the wizard, or of the general block "Anhänge"
 * (`fieldKey` null), board Antrag-stellen.
 *
 * A row per file: name (it wraps, never cut), size and scan state as status text, the
 * tag "Vergleichsangebot", and a delete button. A file the server lost (422 on the
 * submit) shows "Nicht mehr vorhanden" in red; its button only takes it off the list.
 * Below the rows the drop zone with the limits. With `comparison`, a checkbox marks the
 * next uploads as comparison offers (the server takes the mark only with the upload).
 *
 * `changed` emits the ids of the field after each upload and delete; the formly field
 * keeps them as its value.
 */
@Component({
  selector: 'app-draft-files',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    BadgeComponent,
    CheckboxComponent,
    IconComponent,
    FileDropZoneComponent,
    StatusTextComponent,
  ],
  templateUrl: './draft-files.component.html',
  styleUrl: './draft-files.component.scss',
})
export class DraftFilesComponent {
  private readonly drafts = inject(DraftAttachmentsService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The field of the files; `null` for the general block. */
  readonly fieldKey = input<string | null>(null);
  /** The heading above the rows. */
  readonly heading = input.required<string>();
  /** Show the count and the bytes of the whole draft beside the heading. */
  readonly summary = input(false);
  /** Offer the checkbox "Als Vergleichsangebot hochladen". */
  readonly comparison = input(false);
  /** The field is required: the heading carries the mark. */
  readonly required = input(false);
  /** An error text of the field (for example "required"). */
  readonly error = input<string | null>(null);

  /** The ids of this field after a change. */
  readonly changed = output<string[]>();

  protected readonly accept = UPLOAD_ACCEPT;
  protected readonly asOffer = signal(false);

  protected readonly files = computed(() => this.drafts.filesOf(this.fieldKey()));
  protected readonly pending = computed(() =>
    this.drafts.pending().filter((p) => p.fieldKey === this.fieldKey()),
  );
  protected readonly busy = this.drafts.busy;

  /** "3 von 20 Dateien · 544 KB von 50 MB". */
  protected readonly summaryText = computed(() => {
    const limits = this.drafts.limits();
    const locale = this.i18n.formatLocale();
    return this.i18n.translate('apply.files.summary', {
      count: this.drafts.count(),
      max: limits.maxDraftFiles,
      size: formatSize(this.drafts.bytes(), locale),
      maxSize: formatSize(limits.maxDraftBytes, locale),
    });
  });

  /** "PDF, Bilder, Word, Excel, PowerPoint, OpenDocument · bis 10 MB je Datei". */
  protected readonly hint = computed(() =>
    this.i18n.translate('apply.files.hint', {
      size: formatSize(this.drafts.limits().maxFileBytes, this.i18n.formatLocale()),
    }),
  );

  protected size(bytes: number): string {
    return formatSize(bytes, this.i18n.formatLocale());
  }

  protected scan(file: DraftFile) {
    return scanStatus(file.scanState);
  }

  protected async onFiles(files: File[]): Promise<void> {
    const { failed } = await this.drafts.upload(files, {
      fieldKey: this.fieldKey(),
      isComparisonOffer: this.comparison() && this.asOffer(),
    });
    for (const f of failed) {
      this.toast.error(`${f.filename}: ${this.i18n.translate(f.reason)}`);
    }
    this.emit();
  }

  protected onRejected(files: File[]): void {
    for (const f of files) {
      this.toast.error(`${f.name}: ${this.i18n.translate('apply.files.error.type')}`);
    }
  }

  protected async remove(file: DraftFile): Promise<void> {
    const ok = await this.drafts.remove(file.id);
    if (!ok) this.toast.error(this.i18n.translate('apply.files.error.delete'));
    this.emit();
  }

  private emit(): void {
    this.changed.emit(this.drafts.filesOf(this.fieldKey()).filter((f) => !f.failed).map((f) => f.id));
  }
}
