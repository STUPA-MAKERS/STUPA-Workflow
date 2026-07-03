import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { BrandingService } from '@core/branding/branding.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** Public home page — applicant-focused: one application CTA, no account hints. */
@Component({
  selector: 'app-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss',
})
export class HomeComponent {
  /** Configurable app name for the eyebrow line (fallback: i18n `app.title`). */
  readonly branding = inject(BrandingService);
}
