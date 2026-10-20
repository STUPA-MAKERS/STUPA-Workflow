import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { resolveI18n } from '@shared/forms/i18n-text';

/**
 * The branded footer: the copyright line and the legal links, both from the admin
 * branding (public site config, no session needed).
 *
 * The public frame shows it at the foot of every page. The rail shell shows it at the
 * end of the main content (not in an installed app, see the shell styles).
 */
@Component({
  selector: 'app-site-footer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  templateUrl: './site-footer.component.html',
  styleUrl: './site-footer.component.scss',
})
export class SiteFooterComponent {
  private readonly branding = inject(BrandingService);
  private readonly i18n = inject(I18nService);

  /** Legal links for the active locale. A link without a label or a URL goes, so the
   *  line never shows a separator next to an empty part. */
  readonly legalLinks = computed(() =>
    this.branding
      .legalLinks()
      .map((l) => ({ url: l.url.trim(), label: resolveI18n(l.label, this.i18n.locale()).trim() }))
      .filter((l) => l.url && l.label),
  );

  /** Copyright line for the active locale. Empty or blank means the built-in
   *  co-branding text. */
  readonly copyright = computed(() =>
    resolveI18n(this.branding.copyright(), this.i18n.locale()).trim(),
  );
}
