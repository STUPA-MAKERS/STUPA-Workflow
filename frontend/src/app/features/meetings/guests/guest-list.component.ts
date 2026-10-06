import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Meeting, MeetingGuest } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { RowMenuComponent, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import type { StatusKind } from '@shared/status-kind.util';
import { ButtonComponent, DialogComponent, InputComponent } from '@stupa-makers/ui-kit';
import { MeetingGuestsService, guestName } from '../meeting-guests.service';
import { clockTime } from '../meetings-display.util';

interface GuestRow {
  g: MeetingGuest;
  name: string;
  sub: string;
  status: { kind: StatusKind; key: TranslationKey };
  menu: RowMenuSection[];
}

/**
 * The tab "Gäste" of the attendance sheet (#17): the admitted guests with the tag "Gast",
 * "zugelassen 18:16 · Lea Hoffmann" and the status ("Anwesend", or "Schaut zu" when the
 * guests only follow), then the guests who left or were removed. The row menu renames a
 * guest or removes one; the remove explains the consequences first. Guests are no rows of
 * the member list: no status control, no reason, no delegation.
 */
@Component({
  selector: 'app-guest-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    AvatarComponent,
    ButtonComponent,
    DialogComponent,
    InputComponent,
    RowMenuComponent,
    StatusTextComponent,
  ],
  templateUrl: './guest-list.component.html',
  styleUrl: './guests.scss',
})
export class GuestListComponent {
  private readonly i18n = inject(I18nService);
  protected readonly guests = inject(MeetingGuestsService);

  readonly meeting = input.required<Meeting>();
  /** The search of the sheet. */
  readonly query = input('');

  /** The guest in the rename dialog and the guest in the remove confirmation. */
  protected readonly renaming = signal<MeetingGuest | null>(null);
  protected readonly renameDraft = signal('');
  protected readonly removing = signal<MeetingGuest | null>(null);

  protected readonly rows = computed<GuestRow[]>(() => {
    const q = this.query().trim().toLowerCase();
    return this.guests
      .listed()
      .map((g) => this.row(g))
      .filter((r) => !q || r.name.toLowerCase().includes(q));
  });

  private row(g: MeetingGuest): GuestRow {
    const t = (k: TranslationKey, p?: Record<string, string | number>) => this.i18n.translate(k, p);
    const name = guestName(g, t);
    const time = clockTime(g.admittedAt ?? g.decidedAt, this.i18n.locale());
    const sub = [t('guests.list.admittedAt', { time })];
    if (g.decidedByName && g.status === 'admitted') sub.push(g.decidedByName);
    const closed = this.meeting().status === 'closed';
    const menu: RowMenuSection[] =
      g.status === 'admitted' && !closed
        ? [
            {
              items: [
                ...(g.displayName ? [{ id: 'rename', label: t('guests.list.rename'), icon: 'edit' as const }] : []),
                { id: 'remove', label: t('guests.list.remove'), icon: 'logout' as const, danger: true },
              ],
            },
          ]
        : [];
    return { g, name, sub: sub.join(' · '), status: this.statusOf(g), menu };
  }

  private statusOf(g: MeetingGuest): GuestRow['status'] {
    if (g.status === 'left') return { kind: 'muted', key: 'guests.status.left' };
    if (g.status === 'removed') return { kind: 'muted', key: 'guests.status.removed' };
    if (this.meeting().guestsMode === 'watch') return { kind: 'neutral', key: 'guests.status.watching' };
    return { kind: 'accent', key: 'meetings.attendance.present' };
  }

  onMenu(row: GuestRow, id: string): void {
    if (id === 'rename') {
      this.renameDraft.set(row.g.displayName ?? '');
      this.renaming.set(row.g);
    } else if (id === 'remove') {
      this.removing.set(row.g);
    }
  }

  saveRename(): void {
    const g = this.renaming();
    if (!g || this.renameDraft().trim().length < 2) return;
    this.guests.rename(g, this.renameDraft());
    this.renaming.set(null);
  }

  confirmRemove(): void {
    const g = this.removing();
    if (g) this.guests.remove(g);
    this.removing.set(null);
  }

  protected nameOf(g: MeetingGuest): string {
    return guestName(g, (k, p) => this.i18n.translate(k, p));
  }
}
