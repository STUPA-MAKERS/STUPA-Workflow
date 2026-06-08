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
 * Route-getriebene Breadcrumbs (#63). Ermittelt die aktuelle Seite (tiefster
 * Route-Knoten mit ``data.title``) und stellt ihr — wo eine Route flache
 * Geschwister statt echter Kind-Routen hat — die per ``data.parent`` (Liste von
 * Pfaden) deklarierten Eltern voran. **Kein** »Start«/Dashboard-Präfix mehr.
 * Angezeigt nur, wenn es eine Eltern-Ebene gibt (sonst genügt die H1).
 * Optik wie die Budget-Krumen: Pill-Links, ``›``-Trenner.
 */
@Component({
  selector: 'app-breadcrumbs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    @if (crumbs().length > 1) {
      <nav class="bc container" aria-label="Breadcrumb">
        @for (c of crumbs(); track c.url; let last = $last) {
          @if (last) {
            <span class="bc__crumb bc__crumb--current" aria-current="page">{{ c.label }}</span>
          } @else {
            <a class="bc__crumb" [routerLink]="c.url">{{ c.label }}</a>
            <span class="bc__sep" aria-hidden="true">›</span>
          }
        }
      </nav>
    }
  `,
  styles: [
    `
      .bc {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-2);
        padding-block: var(--space-2);
        font-size: var(--fs-sm);
      }
      .bc__crumb {
        color: var(--color-primary);
        font-weight: var(--fw-medium);
        text-decoration: none;
        padding: var(--space-1) var(--space-2);
        border-radius: var(--radius-sm);
      }
      a.bc__crumb:hover {
        background: var(--color-surface-sunken);
      }
      .bc__crumb--current {
        color: var(--color-text);
        font-weight: var(--fw-normal);
      }
      .bc__sep {
        color: var(--color-text-muted);
      }
    `,
  ],
})
export class BreadcrumbsComponent {
  private readonly router = inject(Router);
  private readonly i18n = inject(I18nService);

  readonly crumbs = signal<Crumb[]>([]);

  /** Pfad → i18n-Titel-Key, aus der Route-Config (für Eltern-Auflösung). */
  private titleByPath: Map<string, TranslationKey> | null = null;

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
    let node: ActivatedRouteSnapshot | null = this.router.routerState.snapshot.root;
    let url = '';
    let current: Crumb | null = null;
    let parents: string[] = [];
    while (node) {
      const seg = node.url.map((s) => s.path).join('/');
      if (seg) url += `/${seg}`;
      const title = node.data?.['title'] as TranslationKey | undefined;
      if (title && url) current = { label: this.tr(title), url };
      const parent = node.data?.['parent'] as string[] | undefined;
      if (parent) parents = parent;
      node = node.firstChild;
    }
    if (!current) return [];
    const out: Crumb[] = [];
    for (const path of parents) {
      const key = this.titleForPath(path);
      if (key) out.push({ label: this.tr(key), url: `/${path}` });
    }
    out.push(current);
    return out;
  }

  /** Titel-Key einer (statischen) Route per vollständigem Pfad nachschlagen. */
  private titleForPath(path: string): TranslationKey | undefined {
    if (!this.titleByPath) {
      const map = new Map<string, TranslationKey>();
      const walk = (routes: typeof this.router.config, prefix: string): void => {
        for (const r of routes ?? []) {
          const full = [prefix, r.path].filter(Boolean).join('/');
          const title = r.data?.['title'] as TranslationKey | undefined;
          if (title) map.set(full, title);
          if (r.children) walk(r.children, full);
        }
      };
      walk(this.router.config, '');
      this.titleByPath = map;
    }
    return this.titleByPath.get(path);
  }

  private tr(key: TranslationKey): string {
    return this.i18n.translate(key);
  }
}
