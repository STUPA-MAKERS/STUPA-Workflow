import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Attachment, ScanState, Uuid } from '@core/api/models';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { ToastService } from '@shared/ui/toast/toast.service';
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
 */
@Component({
  selector: 'app-attachments-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, BadgeComponent, ButtonComponent, CardComponent],
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

  readonly scanVariant = scanBadgeVariant;

  constructor() {
    // Bestehende Anhänge laden, sobald die applicationId steht (Hydration nach Reload).
    effect(() => {
      const id = this.applicationId();
      if (!id) return;
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
    const file = input.files?.[0];
    if (!file) return;
    this.upload(file);
    // Reset, damit dieselbe Datei erneut gewählt werden kann (change feuert sonst nicht).
    input.value = '';
  }

  private upload(file: File): void {
    if (this.uploading()) return;
    this.uploading.set(true);
    this.api.uploadAttachment(this.applicationId(), file).subscribe({
      next: (att) => {
        this.attachments.update((list) => [...list, att]);
        this.uploading.set(false);
        this.toast.success(this.i18n.translate('applications.attachments.added'));
      },
      error: (err: { status?: number }) => {
        this.uploading.set(false);
        this.toast.error(this.i18n.translate(this.uploadErrorKey(err.status)));
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
