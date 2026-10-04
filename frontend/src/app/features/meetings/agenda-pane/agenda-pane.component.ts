import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  inject,
  input,
  model,
  output,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { AgendaItem, Meeting, MeetingVote, Uuid } from '@core/api/models';
import { BadgeComponent, IconComponent } from '@stupa-makers/ui-kit';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import {
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
} from '@shared/ui/row-menu/row-menu.component';

/** The ids of the row menu items of an agenda item. */
type AgendaAction = 'rename' | 'up' | 'down' | 'nonPublic' | 'remove';

/**
 * Add, rename, reorder and remove agenda items: the meeting lead with write access, while
 * the meeting is planned or live and the protocol is not locked (O22, O25).
 */
export function canChangeAgenda(meeting: Meeting, locked: boolean): boolean {
  return meeting.canWrite && !locked && meeting.status !== 'closed';
}

/** A move of an agenda item from one position to another (0-based). */
export interface AgendaMove {
  from: number;
  to: number;
}

/**
 * The agenda of the session page ("Tagesordnung · n TOPs").
 *
 * A row shows the number, the title, the kind ("Antrag" or "Freitext"), an open vote
 * and the tag NÖ. The number is filled for the item that the room handles now, and an
 * item before it shows a check: it counts as handled (O19). A click opens the item in
 * the sheet.
 *
 * The row menu holds every agenda change (N21): rename (free text only), move up and
 * down, the non-public switch and the remove. Drag and drop also reorders. Only a
 * planned or live meeting changes its agenda (O25); a closed meeting keeps the
 * non-public switch while the protocol is a draft (O22). An item with an open or
 * closed vote stays on the agenda, so its remove is disabled with the reason.
 */
@Component({
  selector: 'app-agenda-pane',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    BadgeComponent,
    IconComponent,
    ListItemComponent,
    RowMenuComponent,
  ],
  templateUrl: './agenda-pane.component.html',
  styleUrl: './agenda-pane.component.scss',
})
export class AgendaPaneComponent {
  private readonly i18n = inject(I18nService);
  private readonly heading = viewChild.required<ElementRef<HTMLElement>>('heading');

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  /** The item open in the sheet. */
  readonly selectedId = input<Uuid | null>(null);
  /** The protocol is final or renders: nothing on the agenda changes. */
  readonly locked = input(false);
  readonly savingAgenda = input(false);
  readonly renamingTopId = input<Uuid | null>(null);
  readonly renameDraft = model<string>('');
  /**
   * Inside the agenda sheet, whose header names the agenda and holds the add: the heading
   * is for screen readers only, and the pane shows no add of its own.
   */
  readonly inSheet = input(false);

  /**
   * Open an item in the sheet. No output of the pane has the name of a DOM event: a
   * native event that bubbles out of the pane (`select` from the rename field, `drop`
   * from a row) would else reach the same binding with an Event in place of the value.
   */
  readonly pick = output<Uuid>();
  /** Open "TOP hinzufügen". */
  readonly add = output<void>();
  readonly startRename = output<AgendaItem>();
  readonly cancelRename = output<void>();
  readonly renameTop = output<AgendaItem>();
  readonly setNonPublic = output<{ item: AgendaItem; nonPublic: boolean }>();
  readonly move = output<AgendaMove>();
  readonly remove = output<Uuid>();
  readonly dragStart = output<number>();
  readonly dragOver = output<DragEvent>();
  readonly dropAt = output<number>();

  /** Set the non-public flag: the meeting lead with write access, protocol not locked. */
  protected readonly canEditAgenda = computed(() => this.meeting().canWrite && !this.locked());
  /** Add, rename, reorder and remove: also only while the meeting is planned or live. */
  protected readonly canChangeAgenda = computed(() =>
    canChangeAgenda(this.meeting(), this.locked()),
  );

  protected readonly headingText = computed(() => {
    const n = this.agenda().length;
    return this.i18n.translate(n === 1 ? 'meetings.agenda.headingOne' : 'meetings.agenda.heading', {
      n,
    });
  });

  /** The index of the item that the room handles now, or -1. */
  private readonly nowIndex = computed(() =>
    this.agenda().findIndex((a) => a.id === this.meeting().currentAgendaItemId),
  );

  /** Put the focus on the heading of the pane, for "Tagesordnung bearbeiten". */
  focus(): void {
    this.heading().nativeElement.focus();
  }

  protected title(item: AgendaItem): string {
    return item.title || this.i18n.translate('meetings.agenda.untitled');
  }

  /** "TOP 3 · Antrag · Abstimmung offen". */
  protected sub(item: AgendaItem, index: number): string {
    const parts = [
      this.i18n.translate('meetings.agenda.top', { n: index + 1 }),
      this.i18n.translate(
        item.applicationId ? 'meetings.agenda.kindApplication' : 'meetings.agenda.kindFreetext',
      ),
    ];
    if (this.votesFor(item.id).some((v) => v.status === 'open')) {
      parts.push(this.i18n.translate('meetings.agenda.voteOpen'));
    }
    return parts.join(' · ');
  }

  /** The item the room handles now. */
  protected isNow(item: AgendaItem): boolean {
    return item.id === this.meeting().currentAgendaItemId;
  }

  /** An item before "now" in the agenda order counts as handled (O19). */
  protected isDone(index: number): boolean {
    const now = this.nowIndex();
    return now > -1 && index < now;
  }

  protected votesFor(itemId: Uuid): MeetingVote[] {
    return this.meeting().votes.filter((v) => v.agendaItemId === itemId);
  }

  /**
   * The reason why the item cannot be removed, or `null`.
   *
   * An open or closed vote keeps the item (409 `agenda_item_has_vote`, O25). A draft or
   * cancelled vote goes with the item, but only for a person with the vote right
   * (`canManageVotes`); the agenda right alone gets 403.
   */
  protected removeBlockedReason(itemId: Uuid): TranslationKey | null {
    const votes = this.votesFor(itemId);
    if (votes.some((v) => v.status === 'open' || v.status === 'closed')) {
      return 'meetings.agenda.removeBlocked';
    }
    if (!this.meeting().canManageVotes && votes.length > 0) {
      return 'meetings.agenda.removeNeedsVoteRight';
    }
    return null;
  }

  /** The row menus in agenda order, built once per change of their inputs. */
  protected readonly menus = computed(() => this.agenda().map((item, i) => this.menu(item, i)));

  /** The row menu of an item. Empty when nothing on the agenda may change. */
  private menu(item: AgendaItem, index: number): RowMenuSection[] {
    if (!this.canEditAgenda()) return [];
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const nonPublic: RowMenuItem = {
      id: 'nonPublic',
      label: t('meetings.agenda.nonPublicLabel'),
      icon: 'lock',
      checked: item.nonPublic === true,
    };
    if (!this.canChangeAgenda()) return [{ items: [nonPublic] }];

    const edit: RowMenuItem[] = [];
    // An application item carries the title of the application.
    if (!item.applicationId) {
      edit.push({ id: 'rename', label: t('meetings.agenda.rename'), icon: 'edit' });
    }
    if (index > 0) edit.push({ id: 'up', label: t('meetings.agenda.moveUp'), icon: 'up' });
    if (index < this.agenda().length - 1) {
      edit.push({ id: 'down', label: t('meetings.agenda.moveDown'), icon: 'down' });
    }
    const blocked = this.removeBlockedReason(item.id);
    return [
      { items: edit },
      { items: [nonPublic] },
      {
        items: [
          {
            id: 'remove',
            label: t('meetings.agenda.remove'),
            icon: 'delete',
            danger: true,
            disabledReason: blocked ? t(blocked) : null,
          },
        ],
      },
    ];
  }

  protected menuLabel(item: AgendaItem): string {
    return this.i18n.translate('meetings.agenda.rowMenu', { title: this.title(item) });
  }

  protected onAction(item: AgendaItem, index: number, action: RowMenuItem): void {
    if (this.savingAgenda()) return;
    switch (action.id as AgendaAction) {
      case 'rename':
        this.startRename.emit(item);
        break;
      case 'up':
        this.move.emit({ from: index, to: index - 1 });
        break;
      case 'down':
        this.move.emit({ from: index, to: index + 1 });
        break;
      case 'nonPublic':
        this.setNonPublic.emit({ item, nonPublic: !item.nonPublic });
        break;
      case 'remove':
        this.remove.emit(item.id);
        break;
    }
  }
}
