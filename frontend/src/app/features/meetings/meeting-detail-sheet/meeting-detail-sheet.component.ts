import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { Meeting } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { meetingStatus, type StatusView } from '@shared/status-kind.util';
import {
  ButtonComponent,
  IconComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SheetBarComponent,
  SheetBarTitleDirective,
  StatusTextComponent,
} from '@stupa-makers/ui-kit';
import { keeperNames } from '../keepers.util';
import { meetingTimeText } from '../meetings-display.util';
import { weekdayDate } from '@shared/date-format';

/**
 * The detail sheet of one meeting beside the list of the overview: the title, the status
 * line and one large "Details" tile that opens the meeting.
 *
 * The status line holds status · date · time · minute-taker (a warning while a planned
 * meeting has none). The agenda, the attendance, the votes and the protocol are on the
 * meeting page only, because a second summary of them here made people take the sheet
 * for the meeting itself. Edit sits beside the title (`canManage`, not on a phone); the
 * ⋮ menu holds the beamer and the delete (on a phone the edit as well).
 */
@Component({
  selector: 'app-meeting-detail-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    SheetBarComponent,
    SheetBarTitleDirective,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    RowMenuComponent,
    StatusTextComponent,
  ],
  templateUrl: './meeting-detail-sheet.component.html',
  styleUrl: './meeting-detail-sheet.component.scss',
})
export class MeetingDetailSheetComponent {
  private readonly i18n = inject(I18nService);

  readonly meeting = input.required<Meeting>();
  /** The sheet stands beside the list (surface 1). */
  readonly split = input(false);
  /** A phone viewport: the edit goes into the menu. */
  readonly phone = input(false);

  /** "Sitzung bearbeiten". */
  readonly edit = output<Meeting>();
  /** "Sitzung löschen". */
  readonly remove = output<Meeting>();
  /** "Beamer-Ansicht". */
  readonly beamer = output<Meeting>();

  readonly status = computed<StatusView>(() => meetingStatus(this.meeting().status));

  /** "Di., 20.10.2026", or '' without a date. */
  readonly dateText = computed(() => {
    const m = this.meeting();
    return m.date ? weekdayDate(m.date, this.i18n.formatLocale()) : '';
  });

  /** "seit 18:04", "18:00–20:00" or "18:04–21:40". */
  readonly timeText = computed(() => {
    const t = meetingTimeText(this.meeting(), this.i18n.locale());
    if (!t.text) return '';
    return t.since ? this.i18n.translate('meetings.list.since', { time: t.text }) : t.text;
  });

  /** Every keeper of the minutes ("Mara Keller"), or '' without one. */
  readonly keepers = computed(() => keeperNames(this.meeting()));
  /** A planned meeting without a minute-taker cannot start: the sheet warns. */
  readonly keeperMissing = computed(
    () => this.meeting().status === 'planned' && !this.meeting().protokollantId,
  );

  /** The beamer needs `session.manage` and a meeting that is not closed. */
  readonly canBeamer = computed(
    () => this.meeting().canManage && this.meeting().status !== 'closed',
  );

  /** The ⋮ menu of the header: the beamer and the delete; on a phone also the edit. */
  readonly menu = computed<RowMenuSection[]>(() => {
    const m = this.meeting();
    if (!m.canManage) return [];
    const items: RowMenuItem[] = [];
    if (this.phone()) {
      items.push({ id: 'edit', label: this.i18n.translate('meetings.settings.title'), icon: 'edit' });
    }
    if (this.canBeamer()) {
      items.push({ id: 'beamer', label: this.i18n.translate('meetings.beamer.enter'), icon: 'monitor' });
    }
    if (m.canDelete) {
      items.push({
        id: 'delete',
        label: this.i18n.translate('meetings.delete.title'),
        icon: 'trash',
        danger: true,
      });
    }
    return items.length ? [{ items }] : [];
  });

  onMenu(item: RowMenuItem): void {
    const m = this.meeting();
    if (item.id === 'edit') this.edit.emit(m);
    else if (item.id === 'beamer') this.beamer.emit(m);
    else this.remove.emit(m);
  }
}
