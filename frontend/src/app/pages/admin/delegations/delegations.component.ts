import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';

/**
 * Admin-Übersicht der **sitzungsgebundenen** Vertretungen (#delegation-rework).
 *
 * Delegationen legen die Mitglieder selbst auf der Sitzungsseite an (Self-Service,
 * Gremium muss es erlauben); Admins sehen hier alle aktiven/angelegten Vertretungen
 * und können sie notfalls widerrufen. Der Stellvertreter-Pool wird je Gremium in
 * der Mitgliederverwaltung gepflegt.
 */
@Component({
  selector: 'app-delegations',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    BadgeComponent,
    ButtonComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
  ],
  templateUrl: './delegations.component.html',
  styleUrl: '../config/config.shared.scss',
})
export class DelegationsComponent {
  private readonly api = inject(DelegationsApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly delegations = signal<Delegation[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly busy = signal(false);
  protected readonly confirmRevoke = signal<Delegation | null>(null);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'meeting', label: this.i18n.translate('admin.deleg.meeting') },
    { key: 'who', label: this.i18n.translate('admin.deleg.who') },
    { key: 'flags', label: this.i18n.translate('admin.deleg.flags') },
    { key: 'actions', label: this.i18n.translate('admin.deleg.actions'), align: 'end' },
  ]);
  protected readonly rowId = (d: unknown): string => (d as Delegation).id;

  constructor() {
    this.reload();
  }

  protected askRevoke(d: Delegation): void {
    this.confirmRevoke.set(d);
  }

  protected revoke(): void {
    const d = this.confirmRevoke();
    if (!d || this.busy()) return;
    this.busy.set(true);
    this.api.revoke(d.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.confirmRevoke.set(null);
        this.delegations.update((list) => list.filter((x) => x.id !== d.id));
        this.toast.success(this.i18n.translate('admin.deleg.revoked'));
      },
      error: () => {
        this.busy.set(false);
        this.toast.error(this.i18n.translate('admin.deleg.revokeFailed'));
      },
    });
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.list().subscribe({
      next: (list) => {
        this.delegations.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }
}
