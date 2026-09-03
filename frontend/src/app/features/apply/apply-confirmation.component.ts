import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';

/**
 * Confirmation page after a submission.
 *
 * The page has two states, because the backend treats the two submitters
 * differently:
 *
 * - Anonymous: the address is not confirmed yet. The page points the applicant to
 *   the magic-link email. That link opens the edit and status view without a
 *   login, and the application is discarded if nobody confirms.
 * - Signed in: the backend confirms the address at creation time, from the
 *   session. The application is already submitted, so the page says so and links
 *   to the record instead of asking for a confirmation that is done.
 */
@Component({
  selector: 'app-apply-confirmation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, BadgeComponent, CardComponent, TranslatePipe],
  templateUrl: './apply-confirmation.component.html',
  styleUrl: './apply-confirmation.component.scss',
})
export class ApplyConfirmationComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);

  /**
   * True when a principal is logged in. The wizard reads the same signal to skip the
   * contact step and Altcha, and the backend confirms such a submitter immediately.
   */
  protected readonly loggedIn = this.auth.isAuthenticated;

  readonly applicationId = toSignal(
    this.route.queryParamMap.pipe(map((p) => p.get('id'))),
    { initialValue: null },
  );

  /**
   * The reference number the page shows: the first 8 characters of the record id, in
   * upper case. A 36-character UUID is not a number a person can read out on the phone
   * or copy off a printout, and house rule `no-uuids-in-ui` forbids a raw id on screen.
   *
   * This shortens the DISPLAY only. The full id stays in the URL, in the link to the
   * record and in the magic-link email, thus every other path is unchanged. An id
   * shorter than 8 characters gives all of its characters, and no id gives an empty
   * string — the template hides the line in that case.
   */
  protected readonly shortRef = computed(() =>
    (this.applicationId() ?? '').slice(0, 8).toUpperCase(),
  );
}
