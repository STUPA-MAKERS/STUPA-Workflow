import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type IconName, IconComponent } from '@shared/ui';

interface AdminTile {
  link: string;
  title: TranslationKey;
  desc: TranslationKey;
  icon: IconName;
}

/**
 * Admin-Landing (T-34). Einstieg in die Config-UIs. Jede Kachel ist eine eigene
 * (lazy) Route mit Icon-links-Layout und einzeiliger Beschreibung.
 */
@Component({
  selector: 'app-admin-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent],
  template: `
    <section class="admin-home">
      <header class="admin-home__head">
        <h1>{{ 'admin.home.title' | t }}</h1>
        <p class="admin-home__sub">{{ 'admin.home.subtitle' | t }}</p>
      </header>

      <div class="admin-home__grid">
        @for (tile of tiles; track tile.link) {
          <a class="admin-home__tile" [routerLink]="tile.link">
            <span class="admin-home__icon"><app-icon [name]="tile.icon" [size]="28" /></span>
            <span class="admin-home__text">
              <span class="admin-home__title">{{ tile.title | t }}</span>
              <span class="admin-home__desc">{{ tile.desc | t }}</span>
            </span>
          </a>
        }
      </div>
    </section>
  `,
  styles: [
    `
      .admin-home {
        display: flex;
        flex-direction: column;
        gap: var(--space-7);
      }
      .admin-home__sub {
        color: var(--color-text-muted);
      }
      .admin-home__grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
        /* Kacheln auf Inhalt schrumpfen (kein vertikales Strecken) — pro Zeile
           gleich hoch durch Grid-Default-Stretch. */
        grid-auto-rows: auto;
        align-content: start;
        gap: var(--space-4);
      }
      .admin-home__tile {
        display: flex;
        align-items: center;
        gap: var(--space-4);
        padding: var(--space-5);
        text-decoration: none;
        color: inherit;
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-sm);
        transition:
          box-shadow var(--motion-base) var(--ease-standard),
          border-color var(--motion-base) var(--ease-standard);
      }
      .admin-home__tile:hover {
        box-shadow: var(--shadow-md);
        border-color: var(--color-border-strong);
      }
      .admin-home__icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: none;
        width: 3rem;
        height: 3rem;
        border-radius: var(--radius-md);
        background: var(--color-primary-subtle, var(--color-surface-sunken));
        color: var(--color-primary);
      }
      .admin-home__text {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        min-width: 0;
      }
      .admin-home__title {
        font-size: var(--fs-lg);
        font-weight: var(--fw-semibold);
      }
      .admin-home__desc {
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
    `,
  ],
})
export class AdminHomeComponent {
  protected readonly tiles: AdminTile[] = [
    { link: 'users', title: 'admin.home.users', desc: 'admin.home.usersDesc', icon: 'members' },
    { link: 'roles', title: 'admin.home.roles', desc: 'admin.home.rolesDesc', icon: 'roles' },
    { link: 'gremien', title: 'admin.home.gremien', desc: 'admin.home.gremienDesc', icon: 'parliament' },
    { link: 'budget-pots', title: 'budget.tree.title', desc: 'admin.home.budgetPotsDesc', icon: 'euro' },
    { link: 'accounts', title: 'admin.accounts.title', desc: 'admin.accounts.desc', icon: 'building' },
    { link: 'forms', title: 'admin.home.formBuilder', desc: 'admin.home.formBuilderDesc', icon: 'form' },
    { link: 'flow', title: 'admin.home.flowEditor', desc: 'admin.home.flowEditorDesc', icon: 'flow' },
    { link: 'branding', title: 'admin.home.branding', desc: 'admin.home.brandingDesc', icon: 'palette' },
    { link: 'webhooks', title: 'admin.home.webhooks', desc: 'admin.home.webhooksDesc', icon: 'webhook' },
    { link: 'audit', title: 'admin.audit.title', desc: 'admin.audit.desc', icon: 'audit' },
    { link: 'deadlines', title: 'admin.deadlines.title', desc: 'admin.deadlines.subtitle', icon: 'clock' },
  ];
}
