import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import type { GremiumInfo } from '@core/api/gremien.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { dayMonthYear } from '@shared/date-format';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import {
  ButtonComponent,
  EmptyStateComponent,
  IconComponent,
  SectionComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';
import { GremiumInfoDialogComponent } from '../gremium-info-dialog/gremium-info-dialog.component';
import { infoEmpty, infoUrlShown } from '../gremien.util';

/**
 * The sub-tab "Info" of a gremium (specs 000950-000955): the Markdown text and the
 * labelled links (wikis, chat groups), for everyone who sees the gremium.
 *
 * A holder of `info.write` gets "Info bearbeiten", which opens the editor. An empty Info
 * shows the empty state with that action; a reader never reaches an empty tab, because
 * the detail hides it (`infoTabShown`). The detail loads the Info, because the tab list
 * depends on it, and gets each saved Info back through `changed`.
 */
@Component({
  selector: 'app-gremium-info',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    EmptyStateComponent,
    IconComponent,
    SectionComponent,
    SkeletonComponent,
    LoadErrorComponent,
    MarkdownViewComponent,
    GremiumInfoDialogComponent,
  ],
  templateUrl: './gremium-info.component.html',
  styleUrl: './gremium-info.component.scss',
})
export class GremiumInfoComponent {
  private readonly i18n = inject(I18nService);

  readonly gremiumId = input.required<string>();
  readonly gremiumName = input('');
  /** `undefined` while it loads, `null` after a load error. */
  readonly info = input<GremiumInfo | null | undefined>(undefined);
  readonly changed = output<GremiumInfo>();
  /** Load the Info again: after a load error or a 409 of the editor. */
  readonly reload = output<void>();

  readonly editOpen = signal(false);

  readonly empty = computed(() => {
    const info = this.info();
    return !!info && infoEmpty(info);
  });
  /** "Zuletzt geändert von Mara Keller am 15.11.2026", without a name after an erasure. */
  readonly changedLine = computed(() => {
    const info = this.info();
    if (!info?.updatedAt) return '';
    const date = dayMonthYear(info.updatedAt, this.i18n.formatLocale());
    return info.updatedByName
      ? this.i18n.translate('gremien.info.changedBy', { name: info.updatedByName, date })
      : this.i18n.translate('gremien.info.changedAt', { date });
  });

  shownUrl(url: string): string {
    return infoUrlShown(url);
  }

  mail(url: string): boolean {
    return url.toLowerCase().startsWith('mailto:');
  }
}
