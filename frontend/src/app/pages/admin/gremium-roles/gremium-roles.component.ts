import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { PageHeaderComponent } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import { GremiumRoleMatrixComponent } from './gremium-role-matrix.component';

/**
 * The roles of one gremium on their own page (`/admin/gremien/:id/roles`, permission
 * `admin.gremium_roles`).
 *
 * The gremien page shows the same matrix inside the row of a gremium. This page serves a
 * principal with `admin.gremium_roles` but without `admin.gremien`, and the "Rollen"
 * links of the admin home page. The gremium name comes from `GET /gremien`, which every
 * signed-in principal may read.
 */
@Component({
  selector: 'app-gremium-roles',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, PageHeaderComponent, GremiumRoleMatrixComponent],
  templateUrl: './gremium-roles.component.html',
  styleUrl: './gremium-roles.component.scss',
})
export class GremiumRolesComponent {
  private readonly api = inject(AdminApiService);

  /** The gremium that owns these roles. Each role belongs to one gremium. */
  protected readonly gremiumId = (inject(ActivatedRoute).snapshot.paramMap.get('id') ?? '') as Uuid;
  protected readonly gremiumName = signal('');
  protected readonly titleSuffix = computed(() =>
    this.gremiumName() ? `: ${this.gremiumName()}` : '',
  );

  constructor() {
    this.api.listGremienOptions().subscribe({
      next: (list) => this.gremiumName.set(list.find((g) => g.id === this.gremiumId)?.name ?? ''),
      error: () => this.gremiumName.set(''),
    });
  }
}
