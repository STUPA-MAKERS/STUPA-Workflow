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
  template: `
    <app-card [heading]="'applications.attachments.title' | t">
      @if (canUpload()) {
        <div class="att__upload">
          <input
            #fileInput
            type="file"
            class="att__file"
            (change)="onFileSelected($event)"
            [attr.aria-label]="'applications.attachments.upload' | t"
          />
          <app-button
            type="button"
            size="sm"
            [loading]="uploading()"
            (click)="fileInput.click()"
          >
            {{ (uploading() ? 'applications.attachments.uploading' : 'applications.attachments.upload') | t }}
          </app-button>
          <p class="att__hint">{{ 'applications.attachments.hint' | t }}</p>
        </div>
      }

      @if (attachments().length) {
        <ul class="att__list">
          @for (att of attachments(); track att.id) {
            <li class="att__item">
              <div class="att__meta">
                <span class="att__name">{{ att.filename }}</span>
                <span class="att__size">{{ size(att) }}</span>
                @if (att.isComparisonOffer) {
                  <app-badge variant="info">
                    {{ 'applications.attachments.comparisonOffer' | t }}
                  </app-badge>
                }
                <app-badge [variant]="scanVariant(att.scanState)">
                  {{ scanLabel(att.scanState) | t }}
                </app-badge>
              </div>
              <div class="att__actions">
                <app-button
                  variant="secondary"
                  size="sm"
                  [disabled]="att.scanState !== 'clean' || downloadingId() === att.id"
                  [loading]="downloadingId() === att.id"
                  (click)="download(att)"
                >
                  {{ 'applications.attachments.download' | t }}
                </app-button>
                @if (canUpload()) {
                  <app-button
                    variant="ghost"
                    size="sm"
                    [iconOnly]="true"
                    [ariaLabel]="'applications.attachments.delete' | t"
                    [title]="'applications.attachments.delete' | t"
                    [disabled]="removingId() === att.id"
                    [loading]="removingId() === att.id"
                    (click)="remove(att)"
                  >
                    ✕
                  </app-button>
                }
              </div>
            </li>
          }
        </ul>
      } @else {
        <p class="att__muted">{{ 'applications.attachments.empty' | t }}</p>
      }
    </app-card>
  `,
  styles: [
    `
      .att__upload {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        margin-bottom: var(--space-4);
      }
      .att__file {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
      }
      .att__upload app-button {
        align-self: flex-start;
      }
      .att__hint {
        margin: 0;
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .att__list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .att__item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
        padding-bottom: var(--space-3);
        border-bottom: var(--border-width) solid var(--color-border);
        flex-wrap: wrap;
      }
      .att__meta {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        flex-wrap: wrap;
        min-width: 0;
      }
      .att__actions {
        display: flex;
        align-items: center;
        gap: var(--space-2);
      }
      .att__name {
        font-weight: var(--fw-medium);
        word-break: break-word;
      }
      .att__size {
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
        font-variant-numeric: tabular-nums;
      }
      .att__muted {
        color: var(--color-text-muted);
      }
      .att__sessionHint {
        margin-top: var(--space-4);
        font-size: var(--fs-sm);
        font-style: italic;
      }
    `,
  ],
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
