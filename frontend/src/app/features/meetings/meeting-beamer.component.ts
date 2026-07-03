import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { MeetingVote } from '@core/api/models';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import {
  countEntries,
  voteOptionLabel,
  voteResultKey,
  voteResultVariant,
  voteStatusKey,
  voteStatusVariant,
} from './meetings-display.util';

/** Beamer view: only the current question + live result, no dialogs. */
@Component({
  selector: 'app-meeting-beamer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, BadgeComponent],
  templateUrl: './meeting-beamer.component.html',
  styleUrl: './meeting-beamer.component.scss',
})
export class MeetingBeamerComponent {
  private readonly i18n = inject(I18nService);

  /** Currently open vote, else the last closed one (picked by the parent). */
  readonly vote = input.required<MeetingVote | null>();

  protected readonly voteVariant = voteStatusVariant;
  protected readonly voteStatusKey = voteStatusKey;
  protected readonly voteResultKey = voteResultKey;
  protected readonly voteResultVariant = voteResultVariant;
  protected readonly countEntries = countEntries;

  protected optionLabel(opt: string): string {
    return voteOptionLabel(opt, (key) => this.i18n.translate(key));
  }
}
