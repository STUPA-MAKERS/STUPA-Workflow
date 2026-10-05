import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { IconComponent } from '@stupa-makers/ui-kit';
import { shortRef } from './apply.util';

/**
 * Confirmation page after a submission (boards Oeffentlich-Bestaetigen and
 * Oeffentlich-Eingereicht).
 *
 * The page has two states, because the backend treats the two submitters
 * differently:
 *
 * - Anonymous: the address is not confirmed yet. The page points the applicant to
 *   the magic-link email ("Bestätigung ausstehend"). That link opens the edit and
 *   status view without a login; the note names the time after which an unconfirmed
 *   application is discarded (`confirmTtlHours`) and the page names the lifetime of
 *   the link (`linkTtlDays`, "unbegrenzt" without one).
 * - Signed in: the backend confirms the address at creation time, from the session.
 *   The application is already submitted ("Eingereicht"), so the page links to the
 *   record instead of asking for a confirmation that is done.
 *
 * Both show the reference: the first 8 characters of the id (house rule
 * `no-uuids-in-ui` allows only this short form).
 */
@Component({
  selector: 'app-apply-confirmation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent, NoteComponent, StatusTextComponent],
  templateUrl: './apply-confirmation.component.html',
  styleUrl: './apply-confirmation.component.scss',
})
export class ApplyConfirmationComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  private readonly branding = inject(BrandingService);

  /**
   * True when a principal is logged in. The backend confirms such a submitter
   * immediately.
   */
  protected readonly loggedIn = this.auth.isAuthenticated;

  /** Hours until an unconfirmed application is discarded (`confirmTtlHours`, default 12). */
  protected readonly confirmTtlHours = this.branding.confirmTtlHours;
  /** Days a new magic link works; `null`: no expiry. */
  protected readonly linkTtlDays = this.branding.linkTtlDays;

  readonly applicationId = toSignal(
    this.route.queryParamMap.pipe(map((p) => p.get('id'))),
    { initialValue: null },
  );

  /**
   * The reference number the page shows: the first 8 characters of the record id, in
   * upper case. The full id stays in the URL, in the link to the record and in the
   * magic-link email; an id shorter than 8 characters gives all of them, and no id an
   * empty string, which hides the line.
   */
  protected readonly shortRef = computed(() => shortRef(this.applicationId()));
}
