import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  EmptyStateComponent,
  IconComponent,
  ListItemComponent,
  NoteComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';
import { dayMonthYear } from '@shared/date-format';
import type { PublicGremium } from './public-protocols.models';
import { PublicProtocolsService } from './public-protocols.service';
import { useNoindex } from './public-protocols.util';

/** The public page a Gremium overview leads to. */
export type PublicKind = 'protocols' | 'decisions';

/**
 * The Gremium overview of a public page (`/protocols`, `/decisions`, no login, specs 002400,
 * 002401): the public Gremien by name, each with the day of its newest public protocol. A row
 * opens the page of the Gremium (`/<kind>/<slug>`). The route data `kind` names the page.
 *
 * A link with the old Gremium filter (`?committee=<id>`) and exactly one public Gremium opens
 * the page of that Gremium and replaces the address (spec 002404). The page is `noindex`.
 */
@Component({
  selector: 'app-public-gremien',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    EmptyStateComponent,
    IconComponent,
    ListItemComponent,
    NoteComponent,
    SkeletonComponent,
  ],
  templateUrl: './public-gremien.component.html',
  styleUrl: './public-gremien.component.scss',
})
export class PublicGremienComponent {
  private readonly api = inject(PublicProtocolsService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly kind: PublicKind =
    this.route.snapshot.data['kind'] === 'decisions' ? 'decisions' : 'protocols';
  protected readonly gremien = signal<readonly PublicGremium[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal(false);

  /** The title of the page and of the crumb. */
  protected readonly titleKey = this.kind === 'decisions' ? 'publicDecisions.title' : 'publicProtocols.title';

  /** The rows: name, link and "Letztes Protokoll 29.09.2026". */
  protected readonly rows = computed(() =>
    this.gremien().map((g) => ({
      id: g.id,
      name: g.name,
      link: ['/', this.kind, g.slug],
      sub: this.i18n.translate('publicProtocols.gremien.latest', {
        date: dayMonthYear(g.latestDate, this.i18n.formatLocale()),
      }),
    })),
  );

  constructor() {
    useNoindex();
    const asked = this.route.snapshot.queryParamMap.getAll('committee');
    this.api.gremien().subscribe({
      next: (rows) => {
        const hits = rows.filter((g) => asked.includes(g.id));
        if (asked.length === 1 && hits.length === 1) {
          void this.router.navigate(['/', this.kind, hits[0].slug], { replaceUrl: true });
          return;
        }
        this.gremien.set(rows);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set(true);
      },
    });
  }
}
