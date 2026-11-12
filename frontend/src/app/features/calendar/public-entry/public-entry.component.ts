import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { Router } from '@angular/router';
import type { PublicAppointment, PublicMeeting } from '@core/api/calendar.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, DialogComponent, IconComponent } from '@stupa-makers/ui-kit';
import { spanText } from '../calendar.util';

/** An entry of the public calendar with its public fields: a Termin or a meeting. */
export type PublicEntry =
  | { readonly kind: 'appointment'; readonly data: PublicAppointment }
  | { readonly kind: 'meeting'; readonly data: PublicMeeting };

/**
 * The dialog of one entry of the public calendar (§ 000730-000732). A public Termin
 * shows its time, its place and its description. A public meeting shows its time, its
 * Gremium, the titles of its TOPs that are not internal and, when its public protocol
 * exists, a link to it. The dialog never shows a person. On a phone the kit shows the
 * dialog as a bottom sheet.
 */
@Component({
  selector: 'app-public-entry',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, DialogComponent, IconComponent, TranslatePipe],
  templateUrl: './public-entry.component.html',
  styleUrls: ['../appointment-detail/appointment-detail.component.scss', './public-entry.component.scss'],
})
export class PublicEntryComponent {
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);

  readonly open = input(false);
  readonly entry = input<PublicEntry | null>(null);
  readonly closed = output<void>();

  readonly title = computed(() => this.entry()?.data.title ?? '');
  readonly when = computed(() => {
    const e = this.entry();
    if (!e) return '';
    const span =
      e.kind === 'meeting'
        ? { startsOn: e.data.day, endsOn: e.data.day, startTime: e.data.startTime, endTime: e.data.endTime }
        : e.data;
    return spanText(span, this.i18n.formatLocale());
  });

  /** Open the public protocol of the meeting. */
  openProtocol(id: string): void {
    this.closed.emit();
    void this.router.navigate(['/protocols', id]);
  }
}
