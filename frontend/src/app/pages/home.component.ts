import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { resolveI18n } from '@shared/forms/i18n-text';
import { IconComponent } from '@stupa-makers/ui-kit';
import { NoteComponent } from '@shared/ui/note/note.component';
import { DateBlockComponent } from '@shared/ui/date-block/date-block.component';
import type { PublicProtocolSummary } from '../features/public-protocols/public-protocols.models';
import { PublicProtocolsService } from '../features/public-protocols/public-protocols.service';
import { meetingDate } from '../features/public-protocols/public-protocols.util';

/** The number of protocols in the strip "Zuletzt veröffentlicht". */
export const LATEST_COUNT = 3;

/**
 * Public home page (board Oeffentlich-Start, variant A of the public protocols).
 *
 * The body is equal choices: submit an application, read the public protocols, or sign
 * in as a Gremium member. The page cannot tell which kind of visitor it has, so it
 * weights all of them the same instead of guessing. Above them the heading and, when the
 * admin set one, the welcome text of the branding (Freitext "welcome"); below them the
 * hint about the status link and the strip "Zuletzt veröffentlicht" with the newest
 * public protocols.
 *
 * Without a public protocol (or when the list cannot load) the protocol card and the
 * strip stay away, and the page looks as before: two choices.
 */
@Component({
  selector: 'app-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent, NoteComponent, DateBlockComponent],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss',
})
export class HomeComponent {
  private readonly auth = inject(AuthService);
  private readonly branding = inject(BrandingService);
  private readonly i18n = inject(I18nService);
  private readonly protocols = inject(PublicProtocolsService);

  /** The newest public protocols. */
  protected readonly latest = signal<PublicProtocolSummary[]>([]);
  /** The number of all public protocols; 0 hides the card and the strip. */
  protected readonly protocolTotal = signal(0);

  private readonly route = inject(ActivatedRoute, { optional: true });

  /**
   * The reason why a login was refused, from `?loginError=` of the OIDC callback. Only
   * a known reason shows: `account_merged` (the sub of an account that an admin merged
   * into another one).
   */
  protected readonly loginError = computed(() =>
    this.route?.snapshot.queryParamMap.get('loginError') === 'account_merged'
      ? ('home.loginError.account_merged' as const)
      : null,
  );

  /** The configured welcome text in the active language, or empty. */
  protected readonly welcome = computed(() =>
    resolveI18n(this.branding.freetexts().welcome ?? null, this.i18n.locale()).trim(),
  );

  constructor() {
    this.protocols.list({ limit: LATEST_COUNT }).subscribe({
      next: (page) => {
        this.latest.set(page.items);
        this.protocolTotal.set(page.total);
      },
      // The landing works without the protocols: the card and the strip stay away.
      error: () => this.protocolTotal.set(0),
    });
  }

  protected dateOf(p: PublicProtocolSummary): Date {
    return meetingDate(p.date);
  }

  /** The number of public agenda items of a protocol. */
  protected publicTops(p: PublicProtocolSummary): number {
    return p.tops.filter((t) => !t.nonPublic).length;
  }

  /** Start the OIDC login. It leaves the SPA, so there is no route to navigate to. */
  login(): void {
    this.auth.login();
  }
}
