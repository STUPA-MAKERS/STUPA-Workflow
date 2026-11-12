import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import type { ExternalEntry } from '@core/api/calendar.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DialogComponent } from '@stupa-makers/ui-kit';
import { spanText } from '../calendar.util';

/**
 * The dialog of one entry of an external calendar (§ 000714): the title, the time, the
 * place, the name of the calendar and the description. It is read-only, because the
 * entry belongs to another system (§ 000723). On a phone the kit shows the dialog as a
 * bottom sheet.
 */
@Component({
  selector: 'app-external-entry',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DialogComponent, TranslatePipe],
  templateUrl: './external-entry.component.html',
  styleUrl: '../appointment-detail/appointment-detail.component.scss',
})
export class ExternalEntryComponent {
  private readonly i18n = inject(I18nService);

  readonly open = input(false);
  readonly entry = input<ExternalEntry | null>(null);
  readonly closed = output<void>();

  readonly when = computed(() => {
    const e = this.entry();
    return e ? spanText(e, this.i18n.formatLocale()) : '';
  });
}
