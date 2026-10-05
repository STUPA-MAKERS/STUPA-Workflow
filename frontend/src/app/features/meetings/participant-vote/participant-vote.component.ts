import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { VotePanelComponent } from '../../voting/vote-panel/vote-panel.component';
import { ParticipantVoteService } from './participant-vote.service';

/**
 * The vote card of the participant view (board Teilnahme-Live): "Abstimmung offen", the
 * question, the rules, the two-step ballot (own row and, for a substitute, the row of
 * the represented member) and the turnout; after the close the result. The data comes
 * from `ParticipantVoteService`, which the participant view provides.
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
}
