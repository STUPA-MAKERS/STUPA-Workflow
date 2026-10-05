import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { IconComponent } from '@stupa-makers/ui-kit';
import { AdminApiService } from './admin-api.service';
import type { Gremium } from './admin.models';

/**
 * The admin home page `/admin` (board Verwaltung).
 *
 * The admin frame shows the overview beside it: the "Zustand" tiles and every admin
 * page with one line each. This page lists the gremien: name, slug, "n Mitglieder ·
 * n Rollen", and the links to the members and the gremium roles.
 *
 * `admin.gremien` reads the admin list with the counts. A principal with only
 * `admin.gremium_roles` gets the master-data list without counts, so the role pages of
 * each gremium stay reachable. Without either permission the frame shows no page here.
 */
@Component({
  selector: 'app-admin-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent, EmptyStateComponent, SkeletonComponent],
  templateUrl: './admin-home.component.html',
  styleUrl: './admin-home.component.scss',
})
export class AdminHomeComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);

  /** The gremien list and its manage link (`admin.gremien`). */
  protected readonly canGremien = this.auth.can('admin.gremien');
  /** The roles link of each gremium (`admin.gremium_roles`). */
  protected readonly canRoles = this.auth.can('admin.gremium_roles');
  /** The page shows at all. */
  protected readonly visible = this.canGremien || this.canRoles;

  protected readonly gremien = signal<Gremium[]>([]);
  protected readonly loading = signal(true);
  protected readonly failed = signal(false);

  constructor() {
    if (!this.visible) return;
    const list = this.canGremien
      ? this.api.listGremien({ quiet: true })
      : this.api.listGremienOptions();
    list.subscribe({
      next: (rows) => {
        this.gremien.set(rows);
        this.loading.set(false);
      },
      error: () => {
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }
}
