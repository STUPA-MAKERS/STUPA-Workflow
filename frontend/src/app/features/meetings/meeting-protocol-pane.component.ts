import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { AgendaItem, Meeting, MeetingVote, Protocol, Uuid } from '@core/api/models';
import { BadgeComponent, ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { MarkdownEditorComponent } from '@stupa-makers/ui-kit/markdown-editor';
import {
  countEntries,
  voteOptionLabel,
  voteOptionsFor,
  voteResultKey,
  voteResultVariant,
  voteStatusKey,
  voteStatusVariant,
} from './meetings-display.util';

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/** Middle column: protocol meta + per-TOP editor + the TOP's vote questions. */
@Component({
  selector: 'app-meeting-protocol-pane',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    RouterLink,
    BadgeComponent,
    ButtonComponent,
    IconComponent,
    MarkdownEditorComponent,
  ],
  templateUrl: './meeting-protocol-pane.component.html',
  styleUrl: './meeting-protocol-pane.component.scss',
})
export class MeetingProtocolPaneComponent {
  private readonly i18n = inject(I18nService);

  readonly meeting = input.required<Meeting>();
  readonly protocol = input.required<Protocol | null>();
  /** TOP selected in the left pane (+ its 0-based index). */
  readonly top = input.required<AgendaItem | null>();
  readonly topIndex = input.required<number>();
  readonly saveState = input.required<SaveState>();
  readonly casting = input.required<Uuid | null>();
  readonly deletingVote = input.required<Uuid | null>();
  /** Own choice per vote id (highlights the picked option). */
  readonly choices = input.required<Record<string, string>>();

  readonly bodyChange = output<{ itemId: Uuid; body: string }>();
  readonly castVote = output<{ voteId: Uuid; choice: string }>();
  readonly voteClose = output<Uuid>();
  readonly voteCancel = output<Uuid>();
  readonly voteDelete = output<Uuid>();
  readonly voteDialog = output<AgendaItem>();

  protected readonly voteVariant = voteStatusVariant;
  protected readonly voteStatusKey = voteStatusKey;
  protected readonly voteResultKey = voteResultKey;
  protected readonly voteResultVariant = voteResultVariant;
  protected readonly countEntries = countEntries;
  protected readonly voteOptionsFor = voteOptionsFor;

  protected votesForTop(topId: Uuid): MeetingVote[] {
    return this.meeting().votes.filter((v) => v.agendaItemId === topId);
  }

  /** Application TOP: exactly one vote; freetext TOP: any number of questions. */
  protected canAddVote(item: AgendaItem): boolean {
    return !item.applicationId || this.votesForTop(item.id).length === 0;
  }

  protected myChoice(voteId: Uuid): string | null {
    return this.choices()[voteId] ?? null;
  }

  protected optionLabel(opt: string): string {
    return voteOptionLabel(opt, (key) => this.i18n.translate(key));
  }
}
