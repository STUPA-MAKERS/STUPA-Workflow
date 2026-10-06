import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * The phone header of a vote (board Telefon-Abstimmen): the way back, "Abstimmung" and
 * the meeting line "TOP 3 · 34. Sitzung". With `subtitleLink` the line is a link, for
 * example to the meeting or to the application of the vote. A menu goes into the
 * content at the end.
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
  /** The target of the line below the title, or `null` for plain text. */
  readonly subtitleLink = input<readonly string[] | null>(null);
  /** The way back keeps the query params (the filters of the list). */
  readonly keepQuery = input(false);
}
