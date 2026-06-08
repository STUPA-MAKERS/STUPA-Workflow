import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { USE_MOCK_API } from '@core/api/api.config';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import { BadgeComponent, type BadgeVariant, CardComponent } from '@shared/ui';
import { AdminApiService } from './admin-api.service';
import type { FormOverviewItem, FormStatus, Gremium } from './admin.models';

interface AdminTile {
  link: string;
  title: TranslationKey;
  desc: TranslationKey;
}

const STATUS_VARIANT: Record<FormStatus, BadgeVariant> = {
  active: 'success',
  draft: 'warning',
  inactive: 'neutral',
};

/**
 * Admin-Landing (T-34). Einstieg in die Config-UIs + Überblick aktiver Formulare
 * (#75). Jede Kachel ist eine eigene (lazy) Route. Bei aktivem Mock
 * (`USE_MOCK_API`) wird klar markiert, dass die Admin-API (T-24) noch nicht real
 * ist.
 */
@Component({
  selector: 'app-admin-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, CardComponent, BadgeComponent],
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
            <app-card [heading]="tile.title | t" [headingLevel]="2" [interactive]="true">
              {{ tile.desc | t }}
            </app-card>
          </a>
        }
      </div>

      <!-- Überblick aktiver Formulare (#75) -->
      <section class="admin-home__forms" aria-labelledby="forms-overview-h">
        <div class="admin-home__forms-head">
          <div>
            <h2 id="forms-overview-h">{{ 'admin.forms.overviewTitle' | t }}</h2>
            <p class="admin-home__sub">{{ 'admin.forms.overviewSubtitle' | t }}</p>
          </div>
          <a class="admin-home__forms-cta" routerLink="forms">{{ 'admin.forms.manage' | t }} →</a>
        </div>

        @if (loading()) {
          <p class="admin-home__empty" aria-live="polite">{{ 'admin.forms.overviewLoading' | t }}</p>
        } @else if (error()) {
          <p class="admin-home__empty admin-home__error" role="alert">{{ 'admin.forms.overviewError' | t }}</p>
        } @else if (forms().length === 0) {
          <p class="admin-home__empty">{{ 'admin.forms.overviewEmpty' | t }}</p>
        } @else {
          <table class="admin-home__table">
            <thead>
              <tr>
                <th scope="col">{{ 'admin.forms.col.name' | t }}</th>
                <th scope="col">{{ 'admin.forms.col.gremium' | t }}</th>
                <th scope="col">{{ 'admin.forms.col.status' | t }}</th>
                <th scope="col" class="admin-home__num">{{ 'admin.forms.col.version' | t }}</th>
                <th scope="col"><span class="visually-hidden">{{ 'admin.forms.edit' | t }}</span></th>
              </tr>
            </thead>
            <tbody>
              @for (form of forms(); track form.id) {
                <tr>
                  <td class="admin-home__name">{{ name(form) }}</td>
                  <td>{{ gremiumName(form.gremiumId) }}</td>
                  <td><app-badge [variant]="statusVariant(form.status)">{{ statusLabel(form.status) }}</app-badge></td>
                  <td class="admin-home__num">{{ form.version ? 'v' + form.version : '—' }}</td>
                  <td class="admin-home__row-cta"><a routerLink="forms">{{ 'admin.forms.edit' | t }}</a></td>
                </tr>
              }
            </tbody>
          </table>
        }
      </section>
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
        display: grid;
        text-decoration: none;
        color: inherit;
      }
      .admin-home__forms {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
        padding: var(--space-5);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-sm);
      }
      .admin-home__forms-head {
        display: flex;
        align-items: start;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .admin-home__forms-cta {
        color: var(--color-primary);
        font-weight: var(--fw-medium);
        font-size: var(--fs-sm);
        text-decoration: none;
        white-space: nowrap;
      }
      .admin-home__forms-cta:hover {
        text-decoration: underline;
      }
      .admin-home__empty {
        color: var(--color-text-muted);
      }
      .admin-home__error {
        color: var(--color-danger);
      }
      .admin-home__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .admin-home__table th,
      .admin-home__table td {
        padding: var(--space-3) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
        text-align: start;
      }
      .admin-home__table th {
        font-weight: var(--fw-semibold);
        color: var(--color-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
      }
      .admin-home__table tbody tr:hover {
        background: var(--color-surface-sunken);
      }
      .admin-home__name {
        font-weight: var(--fw-medium);
      }
      .admin-home__num {
        text-align: end;
        font-variant-numeric: tabular-nums;
      }
      .admin-home__row-cta {
        text-align: end;
      }
      .admin-home__row-cta a {
        color: var(--color-primary);
        text-decoration: none;
      }
      .admin-home__row-cta a:hover {
        text-decoration: underline;
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
    `,
  ],
})
export class AdminHomeComponent {
  protected readonly isMock = inject(USE_MOCK_API);
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);

  protected readonly forms = signal<FormOverviewItem[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal(false);
  private readonly gremien = signal<Gremium[]>([]);
  private readonly gremiumMap = computed(
    () => new Map(this.gremien().map((g) => [g.id, g.name])),
  );

  protected readonly tiles: AdminTile[] = [
    { link: 'users', title: 'admin.home.users', desc: 'admin.home.usersDesc' },
    { link: 'roles', title: 'admin.home.roles', desc: 'admin.home.rolesDesc' },
    { link: 'gremien', title: 'admin.home.gremien', desc: 'admin.home.gremienDesc' },
    { link: 'budget-pots', title: 'budget.tree.title', desc: 'admin.home.budgetPotsDesc' },
    { link: 'forms', title: 'admin.home.formBuilder', desc: 'admin.home.formBuilderDesc' },
    { link: 'flow', title: 'admin.home.flowEditor', desc: 'admin.home.flowEditorDesc' },
    { link: 'branding', title: 'admin.home.branding', desc: 'admin.home.brandingDesc' },
    { link: 'webhooks', title: 'admin.home.webhooks', desc: 'admin.home.webhooksDesc' },
    { link: 'notifications', title: 'admin.home.notifications', desc: 'admin.home.notificationsDesc' },
  ];

  constructor() {
    this.api.listForms().subscribe({
      next: (f) => {
        this.forms.set(f);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
    this.api.listGremien().subscribe({
      next: (g) => this.gremien.set(g),
      error: () => this.gremien.set([]),
    });
  }

  protected name(form: FormOverviewItem): string {
    return resolveI18n(form.name, this.i18n.locale());
  }

  protected gremiumName(id?: string | null): string {
    return (id && this.gremiumMap().get(id)) || '—';
  }

  protected statusVariant(status: FormStatus): BadgeVariant {
    return STATUS_VARIANT[status];
  }

  protected statusLabel(status: FormStatus): string {
    return this.i18n.translate(`admin.forms.status.${status}` as TranslationKey);
  }
}
