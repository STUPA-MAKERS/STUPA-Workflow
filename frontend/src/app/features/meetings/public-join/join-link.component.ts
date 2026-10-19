import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import type { JoinLink } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { QrCodeComponent, formatJoinCode } from '@shared/ui/qr-code/qr-code.component';
import { ButtonComponent, CopyButtonComponent, IconComponent } from '@stupa-makers/ui-kit';

/** "Kopiert" shows this long after a copy (ms). */
export const JOIN_COPIED_MS = 2000;

/**
 * The join link of a public meeting: a small QR code, "Beitrittslink · Code 7KQ-4MP",
 * the full URL (never cut: it wraps and is selectable) and the actions.
 *
 * - `settings` (dialogs "Sitzung bearbeiten"): "Kopieren" and "Neuen Link erzeugen".
 *   The new link asks first, because the old code stops working and open requests lapse.
 * - `sheet` (attendance sheet): "Öffentliche Teilnahme an", the URL and "Groß zeigen".
 */
@Component({
  selector: 'app-join-link',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, CopyButtonComponent, IconComponent, QrCodeComponent],
  templateUrl: './join-link.component.html',
  styleUrl: './join-link.component.scss',
})
export class JoinLinkComponent {
  private readonly i18n = inject(I18nService);

  readonly link = input.required<JoinLink>();
  readonly variant = input<'settings' | 'sheet'>('settings');
  /** A rotation runs. */
  readonly rotating = input(false);
  /** "Neuen Link erzeugen" is offered (not on a closed meeting). */
  readonly canRotate = input(true);
  readonly rotate = output<void>();
  readonly showLarge = output<void>();

  protected readonly copiedMs = JOIN_COPIED_MS;
  protected readonly confirming = signal(false);

  protected readonly code = computed(() => formatJoinCode(this.link().joinCode));
  protected readonly qrLabel = computed(() =>
    this.i18n.translate('guests.qr.label', { url: this.link().joinUrl }),
  );

  confirmRotate(): void {
    this.confirming.set(false);
    this.rotate.emit();
  }
}
