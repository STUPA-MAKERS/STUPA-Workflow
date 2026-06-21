import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Attachment, ScanState, Uuid } from '@core/api/models';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';
import { CheckboxComponent } from '@stupa-makers/ui-kit';
import { IconComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { formatBytes, scanBadgeVariant } from './applications.util';

/**
 * Anhänge-Panel (T-31, gegen den T-13-files-Contract).
 *
 * Upload (`POST /applications/{id}/attachments`, ≤10 MB, async ClamAV-Scan) und
 * Download über kurzlebige signierte URLs (`GET /attachments/{id}`).
 *
 * **Bewusste Contract-Grenze:** T-13 bietet **keinen** List-Endpunkt und
 * `ApplicationOut` bettet keine Anhänge ein — daher zeigt das Panel die in
 * **dieser Sitzung** hochgeladenen Anhänge (Upload-Antworten). Bestehende
 * Anhänge eines Antrags sind ohne List-API nicht enumerierbar (Folge-Task).
 *
 * Scan-Status: `scanned=false` ⇒ „In Prüfung" (kein Download). `scanned=true`
 * heißt nur „Scan fertig" — sauber-vs-Befund verrät erst der Download: 200 ⇒
 * bereit, **409** ⇒ Quarantäne (Zeile wird auf `quarantined` gesetzt), **410** ⇒
 * Link abgelaufen.
 *
 * Upload-Wege: Datei-Picker (mehrfach) **und** Drag&Drop auf das Panel (Overlay-
 * Stil wie die Rechnungen-Seite). Mehrere Dateien werden sequentiell hochgeladen
 * (concatMap), damit das Rate-Limit (429) nicht durch parallele Requests kippt.
 * Anhänge sind mehrfach auswählbar (Checkbox je Zeile + „alle") für Sammel-Löschung.
 */
@Component({
  selector: 'app-attachments-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    CheckboxComponent,
    IconComponent,
  ],
  templateUrl: './attachments-panel.component.html',
  styleUrl: './attachments-panel.component.scss',
})
export class AttachmentsPanelComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input.required<Uuid>();
  readonly canUpload = input(false);

  readonly attachments = signal<Attachment[]>([]);
  readonly uploading = signal(false);
  readonly downloadingId = signal<Uuid | null>(null);
  readonly removingId = signal<Uuid | null>(null);

  /** Mehrfachauswahl (Sammel-Löschung) + laufende Sammel-Aktion. */
  readonly selected = signal<ReadonlySet<Uuid>>(new Set());
  readonly bulkDeleting = signal(false);
  readonly selectedCount = computed(() => this.selected().size);
  readonly allSelected = computed(() => {
    const list = this.attachments();
    return list.length > 0 && list.every((a) => this.selected().has(a.id));
  });

  /** Drag&Drop-Overlay (Stil wie Rechnungen-Seite). `dragDepth` zählt
   *  enter/leave verschachtelter Kinder, damit das Overlay nicht flackert. */
  readonly dragActive = signal(false);
  private dragDepth = 0;

  readonly scanVariant = scanBadgeVariant;

  constructor() {
    // Bestehende Anhänge laden, sobald die applicationId steht (Hydration nach Reload).
    effect(() => {
      const id = this.applicationId();
      if (!id) return;
      this.selected.set(new Set());
      this.api.listAttachments(id).subscribe({
        next: (list) => this.attachments.set(list),
        error: () => {
          /* kein List-Endpunkt/Fehler → leer lassen (Upload zeigt Session-Stand) */
        },
      });
    });
  }

  size(att: Attachment): string {
    return formatBytes(att.size);
  }

  scanLabel(state: ScanState): TranslationKey {
    return `applications.attachments.scan.${state}` as TranslationKey;
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.upload(Array.from(input.files ?? []));
    // Reset, damit dieselbe Datei erneut gewählt werden kann (change feuert sonst nicht).
    input.value = '';
  }

  /** Mehrere Dateien sequentiell hochladen (concatMap → kein 429 durch Parallel-
   *  Requests). Erfolg/Fehler werden je Datei verbucht, am Ende eine Sammel-Meldung. */
  private upload(files: File[]): void {
    if (this.uploading() || !files.length) return;
    this.uploading.set(true);
    let ok = 0;
    let failedStatus: number | undefined;
    from(files)
      .pipe(concatMap((file) => this.api.uploadAttachment(this.applicationId(), file)))
      .subscribe({
        next: (att) => {
          ok++;
          this.attachments.update((list) => [...list, att]);
        },
        error: (err: { status?: number }) => {
          failedStatus = err.status;
          this.uploading.set(false);
          if (ok > 0) this.toast.success(this.i18n.translate('applications.attachments.added'));
          this.toast.error(this.i18n.translate(this.uploadErrorKey(failedStatus)));
        },
        complete: () => {
          this.uploading.set(false);
          if (ok > 0) this.toast.success(this.i18n.translate('applications.attachments.added'));
        },
      });
  }

  // ----------------------------------------------------------- drag & drop
  onDragEnter(event: DragEvent): void {
    if (!this.canUpload() || !this.hasFiles(event)) return;
    event.preventDefault();
    this.dragDepth++;
    this.dragActive.set(true);
  }

  onDragOver(event: DragEvent): void {
    if (!this.canUpload() || !this.hasFiles(event)) return;
    event.preventDefault();
  }

  onDragLeave(event: DragEvent): void {
    if (!this.dragActive()) return;
    event.preventDefault();
    this.dragDepth = Math.max(0, this.dragDepth - 1);
    if (this.dragDepth === 0) this.dragActive.set(false);
  }

  onDrop(event: DragEvent): void {
    if (!this.canUpload()) return;
    event.preventDefault();
    this.dragDepth = 0;
    this.dragActive.set(false);
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) this.upload(files);
  }

  private hasFiles(event: DragEvent): boolean {
    return Array.from(event.dataTransfer?.types ?? []).includes('Files');
  }

  // ----------------------------------------------------------- bulk-select
  isSelected(id: Uuid): boolean {
    return this.selected().has(id);
  }

  toggleSelect(id: Uuid, checked: boolean): void {
    this.selected.update((cur) => {
      const next = new Set(cur);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  toggleSelectAll(checked: boolean): void {
    this.selected.set(checked ? new Set(this.attachments().map((a) => a.id)) : new Set());
  }

  /** Ausgewählte Anhänge sequentiell löschen (concatMap), dann Auswahl leeren. */
  bulkDelete(): void {
    const ids = [...this.selected()];
    if (!ids.length || this.bulkDeleting()) return;
    this.bulkDeleting.set(true);
    let failed = false;
    from(ids)
      .pipe(concatMap((id) => this.api.deleteAttachment(id)))
      .subscribe({
        next: () => {},
        error: () => {
          failed = true;
          this.bulkDeleting.set(false);
          this.refreshAfterBulk(ids);
          this.toast.error(this.i18n.translate('applications.attachments.deleteError'));
        },
        complete: () => {
          if (failed) return;
          this.bulkDeleting.set(false);
          this.refreshAfterBulk(ids);
          this.toast.success(this.i18n.translate('applications.attachments.deleted'));
        },
      });
  }

  /** Erfolgreich gelöschte (DELETE ist idempotent) aus Liste + Auswahl entfernen.
   *  Bei Teilausfall bleiben verbliebene markiert, damit ein Retry möglich ist. */
  private refreshAfterBulk(attempted: Uuid[]): void {
    const id = this.applicationId();
    this.api.listAttachments(id).subscribe({
      next: (list) => {
        const remaining = new Set(list.map((a) => a.id));
        this.attachments.set(list);
        this.selected.update((cur) => new Set([...cur].filter((x) => remaining.has(x))));
      },
      error: () => {
        // Ohne frische Liste: angefragte IDs lokal entfernen.
        const removed = new Set(attempted);
        this.attachments.update((list) => list.filter((a) => !removed.has(a.id)));
        this.selected.update((cur) => new Set([...cur].filter((x) => !removed.has(x))));
      },
    });
  }

  private uploadErrorKey(status?: number): TranslationKey {
    switch (status) {
      case 413:
        return 'applications.attachments.error.tooLarge';
      case 415:
        return 'applications.attachments.error.type';
      case 429:
        return 'applications.attachments.error.rate';
      case 503:
        return 'applications.attachments.error.storage';
      default:
        return 'applications.attachments.error.upload';
    }
  }

  download(att: Attachment): void {
    if (this.downloadingId()) return;
    this.downloadingId.set(att.id);
    this.api.attachmentUrl(att.id).subscribe({
      next: (signed) => {
        this.downloadingId.set(null);
        this.openUrl(signed.url);
      },
      error: (err: { status?: number }) => {
        this.downloadingId.set(null);
        if (err.status === 409) {
          // Befund/Quarantäne: Zeile dauerhaft als quarantined markieren.
          this.attachments.update((list) =>
            list.map((a) => (a.id === att.id ? { ...a, scanState: 'quarantined' as ScanState } : a)),
          );
          this.toast.error(this.i18n.translate('applications.attachments.download.conflict'));
        } else if (err.status === 410) {
          this.toast.error(this.i18n.translate('applications.attachments.download.gone'));
        } else {
          this.toast.error(this.i18n.translate('applications.attachments.download.error'));
        }
      },
    });
  }

  remove(att: Attachment): void {
    if (this.removingId()) return;
    this.removingId.set(att.id);
    this.api.deleteAttachment(att.id).subscribe({
      next: () => {
        this.attachments.update((list) => list.filter((a) => a.id !== att.id));
        this.removingId.set(null);
        this.toast.success(this.i18n.translate('applications.attachments.deleted'));
      },
      error: () => {
        this.removingId.set(null);
        this.toast.error(this.i18n.translate('applications.attachments.deleteError'));
      },
    });
  }

  /** Signierte URL öffnen (eigene Methode → in Tests stubbar). */
  protected openUrl(url: string): void {
    window.open(url, '_blank', 'noopener');
  }
}
