import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ButtonLinkComponent, IconComponent, type IconName, ButtonGroupComponent } from '@stupa-makers/ui-kit';

/**
 * The block of an error page (403, 404): the code, a heading with its icon, one
 * sentence and the way out. Centred in the page; the frame around it (rail or public
 * bar) comes from the shell.
 */
@Component({
  selector: 'app-error-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonGroupComponent, RouterLink, ButtonLinkComponent, IconComponent],
  templateUrl: './error-page.component.html',
  styleUrl: './error-page.component.scss',
})
export class ErrorPageComponent {
  readonly code = input.required<string>();
  readonly icon = input.required<IconName>();
  readonly heading = input.required<string>();
  readonly body = input.required<string>();
  readonly actionLabel = input.required<string>();
  readonly actionLink = input.required<string>();
}
