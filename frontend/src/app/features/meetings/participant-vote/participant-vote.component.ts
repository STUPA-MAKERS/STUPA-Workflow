import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { VoteContext } from '../../voting/vote-panel/vote-context';
import { VotePanelComponent } from '../../voting/vote-panel/vote-panel.component';
import { ParticipantVoteService } from './participant-vote.service';

/**
 * The vote card of the participant view (board Teilnahme-Live): "Abstimmung offen", the
 * question, the rules, the two-step ballot (own row and, for a substitute, the row of
 * the represented member) and the turnout; after the close the result. The data comes
 * from `ParticipantVoteService`, which the participant view provides.
 *
 * `layout="strip"` is the card above the text on a narrow screen (board
 * Schmal-Teilnahme): "Abstimmung offen · TOP 3", the turnout and the rows side by side.
 */
@Component({
  selector: 'app-participant-vote',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [VotePanelComponent],
  templateUrl: './participant-vote.component.html',
  styleUrl: './participant-vote.component.scss',
})
export class ParticipantVoteComponent {
  protected readonly state = inject(ParticipantVoteService);

  readonly layout = input<'card' | 'strip'>('card');
  /** The 1-based number of the agenda item of the vote ("TOP 3"), or `null`. */
  readonly position = input<number | null>(null);

  protected readonly context = computed<VoteContext>(() => ({
    meeting: null,
    position: this.position(),
  }));
}
