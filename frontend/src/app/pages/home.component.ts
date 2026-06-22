import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { BrandingService } from '@core/branding/branding.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** Öffentliche Startseite — Applicant-fokussiert: ein Antrags-CTA, keine Konto-Hinweise. */
@Component({
  selector: 'app-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss',
})
export class HomeComponent {
  /** Konfigurierbarer App-Name für die Eyebrow-Zeile (Fallback: i18n `app.title`, #brand-name). */
  readonly branding = inject(BrandingService);
}
