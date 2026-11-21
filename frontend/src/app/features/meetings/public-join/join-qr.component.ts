import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  model,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import type { Meeting } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { QrCodeComponent, formatJoinCode } from '@shared/ui/qr-code/qr-code.component';
import {
  ButtonComponent,
  ButtonGroupComponent,
  CopyButtonComponent,
  FocusDialogDirective,
  IconComponent,
  MEDIA,
  mediaQuery,
  SideSheetComponent,
  SheetBodyDirective,
} from '@stupa-makers/ui-kit';
import { MeetingGuestsService } from '../meeting-guests.service';
import { JOIN_COPIED_MS } from './join-link.component';

/**
 * "QR-Code" of the session page: a frosted popover with the large code, the link and
 * "Link kopieren". The beamer has its own button beside it. For a room without a beamer
 * the lead shows the laptop or the phone around. A phone shows the same content
 * as a bottom sheet; the page opens it from its menu and from the attendance sheet
 * ("Groß zeigen"). Only the lead of a public meeting that is not closed has it.
 */
@Component({
  selector: 'app-join-qr',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SheetBodyDirective,
    FocusDialogDirective,
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    CopyButtonComponent,
    IconComponent,
    QrCodeComponent,
    SideSheetComponent,
  ],
  host: {
    '(document:keydown.escape)': 'open.set(false)',
    '[class.btn-grp__seg]': 'segment()',
  },
  templateUrl: './join-qr.component.html',
  styleUrl: './join-qr.component.scss',
})
export class JoinQrComponent {
  private readonly i18n = inject(I18nService);
  protected readonly guests = inject(MeetingGuestsService, { optional: true });
  protected readonly phone = mediaQuery(MEDIA.phone);

  readonly meeting = input.required<Meeting>();
  /** The trigger button in the header (wide and medium screens). */
  readonly button = input(true);
  /**
   * The trigger is an icon button that opens the code above it, for the dock at the foot
   * of the page.
   */
  readonly iconOnly = input(false);
  readonly open = model(false);

  protected readonly copiedMs = JOIN_COPIED_MS;

  /**
   * The icon trigger in the dock is a segment of the button group of the dock (spec 001354):
   * the host carries `btn-grp__seg` and holds the button itself, so the code button and the
   * buttons beside it form one group. Without a link the host carries no class and leaves no
   * gap in the shape.
   */
  protected readonly segment = computed(
    () => this.iconOnly() && this.button() && this.link() !== null,
  );

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
}
