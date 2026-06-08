import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, type ActivatedRouteSnapshot } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';

interface Crumb {
  label: string;
  url: string;
}

/**
 * Route-getriebene Breadcrumbs (#63). Läuft die aktive Route-Kette ab und sammelt
 * je Ebene mit ``data.title`` (i18n-Key) eine Krume + den kumulierten Pfad. Beginnt
 * immer mit »Start« (Dashboard). Auf der Startseite selbst werden keine angezeigt.
 */
@Component({
  selector: 'app-breadcrumbs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    @if (crumbs().length > 1) {
      <nav class="bc container" aria-label="Breadcrumb">
        <ol class="bc__list">
          @for (c of crumbs(); track c.url; let last = $last) {
            <li class="bc__item">
              @if (last) {
                <span aria-current="page">{{ c.label }}</span>
              } @else {
                <a [routerLink]="c.url">{{ c.label }}</a>
                <span class="bc__sep" aria-hidden="true">/</span>
              }
            </li>
          }
        </ol>
      </nav>
    }
  `,
  styles: [
    `
      .bc {
        padding-block: var(--space-2);
        font-size: var(--fs-sm);
      }
      .bc__list {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-2);
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .bc__item {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
        color: var(--color-text-muted);
      }
      .bc__item a {
        color: var(--color-text-muted);
        text-decoration: none;
      }
      .bc__item a:hover {
        color: var(--color-primary);
        text-decoration: underline;
      }
      .bc__sep {
        color: var(--color-border-strong);
      }
    `,
  ],
})
export class BreadcrumbsComponent {
  private readonly router = inject(Router);
  private readonly i18n = inject(I18nService);

  readonly crumbs = signal<Crumb[]>([]);

  constructor() {
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.crumbs.set(this.build()));
    this.crumbs.set(this.build());
  }

  private build(): Crumb[] {
    const home: Crumb = { label: this.tr('nav.dashboard'), url: '/dashboard' };
    const out: Crumb[] = [home];
    let node: ActivatedRouteSnapshot | null = this.router.routerState.snapshot.root;
    let url = '';
    while (node) {
      const seg = node.url.map((s) => s.path).join('/');
      if (seg) url += `/${seg}`;
      const title = node.data?.['title'] as TranslationKey | undefined;
      if (title && url && url !== home.url) {
        out.push({ label: this.tr(title), url });
      }
      node = node.firstChild;
    }
    return out;
  }

  private tr(key: TranslationKey): string {
    return this.i18n.translate(key);
  }
}
