import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * The phone header of a vote (board Telefon-Abstimmen): the way back, "Abstimmung" and
 * the meeting line "TOP 3 · 34. Sitzung". A menu goes into the content at the end.
 */
@Component({
  selector: 'app-vote-phone-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, RouterLink, TranslatePipe],
  templateUrl: './phone-header.component.html',
  styleUrl: './phone-header.component.scss',
})
export class VotePhoneHeaderComponent {
  readonly back = input.required<string | readonly string[]>();
  readonly subtitle = input<string | null>(null);
}
