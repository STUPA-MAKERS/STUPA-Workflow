import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { BrandingService } from '@core/branding/branding.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CardComponent } from '@stupa-makers/ui-kit';

/** Öffentliche Startseite (Skelett). */
@Component({
  selector: 'app-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, CardComponent],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss',
})
export class HomeComponent {
  /** Konfigurierbarer App-Name für die H1 (Fallback: i18n `home.heading`, #brand-name). */
  readonly branding = inject(BrandingService);
}
