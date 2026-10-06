import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  inject,
  input,
  model,
  output,
  signal,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import type { Meeting } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { QrCodeComponent, formatJoinCode } from '@shared/ui/qr-code/qr-code.component';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { MeetingGuestsService } from '../meeting-guests.service';
import { JOIN_COPIED_MS } from './join-link.component';

/**
 * "QR-Code" in the header of the session page (#17, variant A): a popover with the large
 * code, the link, "Link kopieren" and "Auf dem Beamer zeigen". For a room without a
 * beamer the lead shows the laptop or the phone around. A phone shows the same content
 * as a bottom sheet; the page opens it from its menu and from the attendance sheet
 * ("Groß zeigen"). Only the lead of a public meeting that is not closed has it.
 */
@Component({
  selector: 'app-join-qr',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe, ButtonComponent, IconComponent, QrCodeComponent, SideSheetComponent],
  host: { '(document:keydown.escape)': 'open.set(false)' },
  templateUrl: './join-qr.component.html',
  styleUrl: './join-qr.component.scss',
})
export class JoinQrComponent implements OnDestroy {
  private readonly i18n = inject(I18nService);
  protected readonly guests = inject(MeetingGuestsService, { optional: true });
  protected readonly phone = mediaQuerySignal(MEDIA.phone);

  readonly meeting = input.required<Meeting>();
  /** The trigger button in the header (wide and medium screens). */
  readonly button = input(true);
  readonly open = model(false);
  /** "Auf dem Beamer zeigen". */
  readonly beamer = output<void>();

  protected readonly copied = signal(false);
  private timer: ReturnType<typeof setTimeout> | null = null;

  /** The link of the open meeting, while the lead may show it. */
  protected readonly link = computed(() => {
    const m = this.meeting();
    if (!m.publicJoin || !m.canManage || m.status === 'closed') return null;
    return this.guests?.meetingId() === m.id ? this.guests.joinLink() : null;
  });
  protected readonly formatCode = formatJoinCode;

  protected qrLabel(url: string): string {
    return this.i18n.translate('guests.qr.label', { url });
  }

  copy(): void {
    const url = this.link()?.joinUrl;
    if (!url) return;
    void navigator.clipboard?.writeText(url)?.then(
      () => {
        this.copied.set(true);
        if (this.timer !== null) clearTimeout(this.timer);
        this.timer = setTimeout(() => {
          this.timer = null;
          this.copied.set(false);
        }, JOIN_COPIED_MS);
      },
      () => this.copied.set(false),
    );
  }

  showOnBeamer(): void {
    this.open.set(false);
    this.beamer.emit();
  }

  ngOnDestroy(): void {
    if (this.timer !== null) clearTimeout(this.timer);
  }
}
