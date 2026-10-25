import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { Meeting, MeetingGuest } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  AvatarComponent,
  ButtonComponent,
  IconComponent,
  MEDIA,
  mediaQuery,
  TruncatedDirective,
} from '@stupa-makers/ui-kit';
import { MeetingGuestsService, guestName } from '../meeting-guests.service';
import { clock } from '@shared/date-format';

/** A request younger than this reads "gerade eben" (ms). */
const JUST_NOW_MS = 60_000;

/**
 * "Beitrittsanfragen · 3" in the attendance sheet (variant A): "Alle zulassen" and
 * one row per request with "Ablehnen" and "Zulassen". On a phone "Ablehnen" is an ✕ icon,
 * so the name and both actions fit one line. No request, no block.
 */
@Component({
  selector: 'app-guest-requests',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TruncatedDirective, TranslatePipe, AvatarComponent, ButtonComponent, IconComponent],
  templateUrl: './guest-requests.component.html',
  styleUrl: './guests.scss',
})
export class GuestRequestsComponent {
  private readonly i18n = inject(I18nService);
  protected readonly guests = inject(MeetingGuestsService);
  protected readonly phone = mediaQuery(MEDIA.phone);

  readonly meeting = input.required<Meeting>();
  /** The time "now" for "gerade eben"; a spec fixes it. */
  readonly now = input<number | null>(null);

  protected readonly rows = computed(() =>
    this.guests.pending().map((g) => ({ g, name: this.nameOf(g), sub: this.waiting(g) })),
  );

  protected nameOf(g: MeetingGuest): string {
    return guestName(g, (k, p) => this.i18n.translate(k, p));
  }

  private waiting(g: MeetingGuest): string {
    const now = this.now() ?? Date.now();
    if (now - Date.parse(g.requestedAt) < JUST_NOW_MS) return this.i18n.translate('guests.request.justNow');
    return this.i18n.translate('guests.request.waitingSince', {
      time: clock(g.requestedAt, this.i18n.formatLocale()),
    });
  }
}
