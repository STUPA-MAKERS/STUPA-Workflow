import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  model,
  output,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { AgendaItem, Attendance, Meeting, Uuid } from '@core/api/models';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { mediaQuerySignal } from '../../../layout/media-query';
import { KeeperMenuComponent } from '../keeper-menu/keeper-menu.component';
import { keeperNames } from '../keepers.util';
import { clockTime } from '../meetings-display.util';

/**
 * The panel that is open. The minute-taker menu is a popover above the dock (a bottom
 * sheet on a phone); the attendance is a side sheet of the page.
 */
export type DockPanel = 'none' | 'attendance' | 'protokollant';

/**
 * The dock at the foot of the session page.
 *
 * Planned: "Noch nicht eröffnet · n TOPs vorbereitet", the minute-taker (marked while it
 * is missing; the meeting lead picks one here) and the attendance.
 *
 * Live: the step through the agenda ("TOP 3 von 8"), the own ballot of the open vote, or
 * the way back to the item that runs now; the attendance, the minute-taker ("Protokoll:
 * Mara Keller", the handover for the lead and the minute-taker, Z3) and the word count of
 * the open item.
 *
 * Closed: "Geschlossen um 21:12 · 8 TOPs", every minute-taker of the meeting (locked: a
 * closed meeting changes no keeper) and the attendance.
 *
 * The minute-taker menu opens as a popover above the dock, on a phone as a bottom sheet;
 * the dock then sits on the viewport above the navigation bar. A pick in a live meeting
 * goes to the handover dialog of the page. The attendance chip opens the attendance sheet
 * of the page.
 */
@Component({
  selector: 'app-session-dock',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    KeeperMenuComponent,
    SideSheetComponent,
  ],
  templateUrl: './session-dock.component.html',
  styleUrl: './session-dock.component.scss',
  host: {
    '(document:keydown.escape)': 'closePanel()',
    // On a phone the dock is a fixed layer above the page. The bottom sheet lives in it,
    // so the layer moves up to the dialog level while the sheet is open; else the
    // navigation bar covers the sheet and its scrim.
    '[style.z-index]': "phone() && shownPanel() === 'protokollant' ? 'var(--z-dialog)' : null",
  },
})
export class SessionDockComponent {
  private readonly i18n = inject(I18nService);

  /** A phone opens the panels as a bottom sheet instead of a popover. */
  protected readonly phone = mediaQuerySignal(MEDIA.phone);

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  /** The 0-based index of the item open in the sheet, or -1. */
  readonly topIndex = input.required<number>();
  readonly attendance = input.required<Attendance[]>();
  readonly wordCount = input(0);
  /** The own ballot of the open vote ("Ja", "abgegeben"), or `null`. */
  readonly myVote = input<string | null>(null);
  readonly panel = model<DockPanel>('none');

  /** Move to the previous (-1) or the next (+1) agenda item. */
  readonly step = output<-1 | 1>();
  /** Open the item that the room handles now. */
  readonly jumpNow = output<Uuid>();
  /** Name the minute-taker of a planned meeting. */
  readonly setProtokollant = output<Uuid>();
  /** A member was picked to take the minutes of a live meeting: the handover dialog asks when. */
  readonly pickHandover = output<Uuid>();
  /** Discard the planned handover. */
  readonly cancelHandover = output<void>();

  protected readonly presentCount = computed(
    () => this.attendance().filter((a) => a.status === 'present').length,
  );
  protected readonly hasPrev = computed(() => this.topIndex() > 0);
  protected readonly hasNext = computed(
    () => this.topIndex() >= 0 && this.topIndex() < this.agenda().length - 1,
  );

  /** The index of the item that the room handles now, or -1. A planned meeting has none. */
  private readonly nowIndex = computed(() => {
    const m = this.meeting();
    if (m.status === 'planned' || !m.currentAgendaItemId) return -1;
    return this.agenda().findIndex((a) => a.id === m.currentAgendaItemId);
  });
  /** The item the room handles now with its label, when it is not the open one. */
  protected readonly nowElsewhere = computed<{ item: AgendaItem; label: string } | null>(() => {
    const now = this.nowIndex();
    if (now < 0 || this.topIndex() < 0 || now === this.topIndex()) return null;
    const item = this.agenda()[now];
    const title = item.title || this.i18n.translate('meetings.agenda.untitled');
    return { item, label: `${this.i18n.translate('meetings.agenda.top', { n: now + 1 })} · ${title}` };
  });

  /** The meeting lead names the minute-taker of a planned meeting. */
  protected readonly canPickKeeper = computed(() => {
    const m = this.meeting();
    return m.status === 'planned' && m.canManage;
  });
  /** The meeting lead and the minute-taker hand the minutes of a live meeting over. */
  protected readonly canHandOver = computed(() => {
    const m = this.meeting();
    return m.status === 'live' && (m.canManage || m.isProtokollant);
  });
  /** The panel on screen: the minute-taker only for the people who may change it. */
  protected readonly shownPanel = computed<DockPanel>(() => {
    const panel = this.panel();
    if (panel === 'protokollant' && !this.canPickKeeper() && !this.canHandOver()) return 'none';
    return panel;
  });
  protected readonly panelHeading = computed<TranslationKey>(() =>
    this.canHandOver() ? 'meetings.handover.title' : 'meetings.dock.pickProtokollant',
  );

  /** The closed dock: "Geschlossen um 21:12", or "Geschlossen" without a known time. */
  protected readonly closedLine = computed(() => {
    const time = clockTime(this.meeting().closedAt, this.i18n.locale());
    return time
      ? this.i18n.translate('meetings.dock.closedAt', { time })
      : this.i18n.translate('meetings.status.closed');
  });
  /** Every minute-taker of the meeting once: "Mara Keller, Lea Hoffmann". */
  protected readonly keepers = computed(() => keeperNames(this.meeting()));

  togglePanel(panel: Exclude<DockPanel, 'none'>): void {
    this.panel.set(this.panel() === panel ? 'none' : panel);
  }

  closePanel(): void {
    this.panel.set('none');
  }

  /**
   * Name a member as the minute-taker and close the picker. A planned meeting assigns
   * the person; a live meeting goes on to the handover dialog, which asks when.
   */
  pickKeeper(principalId: Uuid): void {
    this.panel.set('none');
    const m = this.meeting();
    if (principalId === m.protokollantId) return;
    if (m.status === 'live') this.pickHandover.emit(principalId);
    else this.setProtokollant.emit(principalId);
  }

  /** Discard the planned handover and close the menu. */
  discardHandover(): void {
    this.panel.set('none');
    this.cancelHandover.emit();
  }
}
