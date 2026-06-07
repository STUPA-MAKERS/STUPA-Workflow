import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { USE_MOCK_API } from '@core/api/api.config';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { CardComponent } from '@shared/ui';

interface AdminTile {
  link: string;
  title: TranslationKey;
  desc: TranslationKey;
}

/**
 * Admin-Landing (T-34). Einstieg in die Config-UIs; jede Kachel ist eine eigene
 * (lazy) Route. Bei aktivem Mock (`USE_MOCK_API`) wird klar markiert, dass die
 * Admin-API (T-24) noch nicht real ist.
 */
@Component({
  selector: 'app-admin-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, CardComponent],
  template: `
    <section class="admin-home">
      <header class="admin-home__head">
        <h1>{{ 'admin.home.title' | t }}</h1>
        <p class="admin-home__sub">{{ 'admin.home.subtitle' | t }}</p>
        @if (isMock) {
          <p class="admin-home__mock" role="status">{{ 'admin.home.mockNotice' | t }}</p>
        }
      </header>

      <div class="admin-home__grid">
        @for (tile of tiles; track tile.link) {
          <a class="admin-home__tile" [routerLink]="tile.link">
            <app-card [heading]="tile.title | t" [interactive]="true">
              {{ tile.desc | t }}
            </app-card>
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
        gap: var(--space-6);
      }
      .admin-home__sub {
        color: var(--color-text-muted);
      }
      .admin-home__mock {
        margin-top: var(--space-3);
        padding: var(--space-3) var(--space-4);
        border-radius: var(--radius-md);
        background: var(--color-warning-subtle);
        color: var(--color-warning);
        font-size: var(--fs-sm);
      }
      .admin-home__grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
        gap: var(--space-5);
      }
      .admin-home__tile {
        text-decoration: none;
        color: inherit;
      }
    `,
  ],
})
export class AdminHomeComponent {
  protected readonly isMock = inject(USE_MOCK_API);

  protected readonly tiles: AdminTile[] = [
    { link: 'forms', title: 'admin.home.formBuilder', desc: 'admin.home.formBuilderDesc' },
    { link: 'flow', title: 'admin.home.flowEditor', desc: 'admin.home.flowEditorDesc' },
    { link: 'branding', title: 'admin.home.branding', desc: 'admin.home.brandingDesc' },
    { link: 'webhooks', title: 'admin.home.webhooks', desc: 'admin.home.webhooksDesc' },
    { link: 'notifications', title: 'admin.home.notifications', desc: 'admin.home.notificationsDesc' },
  ];
}
