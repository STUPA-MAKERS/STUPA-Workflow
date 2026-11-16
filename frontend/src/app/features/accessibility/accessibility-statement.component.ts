import { FeatureService } from '@core/features/feature.service';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent, SkeletonComponent } from '@stupa-makers/ui-kit';
import { resolveI18n } from '@shared/forms/i18n-text';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { HelpService } from '../help/help.service';

/**
 * The accessibility statement (`/accessibility`, no login; specs 000495 and 000497).
 *
 * The text is the free text `freetexts.accessibilityStatement` of the site config, Markdown
 * per language, which the admin edits on `/admin/texts`. The server answers a config
 * without it with its built-in draft. Its `##` headings render as `h2` below the `h1` of
 * the page.
 *
 * Below the text, "Barriere melden" opens the report dialog with the kind `barrier`. The
 * button shows for every visitor: the server takes a barrier report without a login even
 * while the reports of visitors are off, because the law requires the feedback route.
 * While `Tickets` is off the section does not show, because the report is a ticket (spec
 * 000758).
 */
@Component({
  selector: 'app-accessibility-statement',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, IconComponent, SkeletonComponent, MarkdownViewComponent],
  templateUrl: './accessibility-statement.component.html',
  styleUrl: './accessibility-statement.component.scss',
})
export class AccessibilityStatementComponent {
  private readonly branding = inject(BrandingService);
  private readonly i18n = inject(I18nService);
  private readonly help = inject(HelpService);
  private readonly features = inject(FeatureService);

  /** The public config loaded: before, the text is not known. */
  protected readonly loaded = this.branding.loaded;

  /** The statement in the language of the page, or the nearest language that has one. */
  protected readonly markdown = computed(() =>
    resolveI18n(this.branding.freetexts().accessibilityStatement, this.i18n.uiLocale()).trim(),
  );

  /** The report of a barrier is a ticket, so it does not show while `Tickets` is off. */
  protected readonly canReport = computed(() => this.features.isOn('tickets'));

  /** Open the report dialog with the kind "Barriere". */
  protected report(): void {
    this.help.openReport('barrier');
  }
}
