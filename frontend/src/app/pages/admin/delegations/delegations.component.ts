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
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';

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
  template: `
    <section class="cfg">
      <header class="cfg__head">
        <h1>{{ 'admin.deleg.title' | t }}</h1>
      </header>
      <p class="cfg__empty">{{ 'admin.deleg.subtitle' | t }}</p>

      @if (loading()) {
        <p class="cfg__empty" aria-live="polite">{{ 'admin.deleg.loading' | t }}</p>
      } @else if (loadError()) {
        <p class="cfg__empty" role="alert">{{ 'admin.deleg.error' | t }}</p>
      } @else {
        <app-data-table
          [columns]="columns()"
          [rows]="delegations()"
          [rowKey]="rowId"
          [emptyText]="'admin.deleg.none' | t"
        >
          <ng-template appCell="meeting" let-d>
            <a [routerLink]="['/meetings', $any(d).meetingId]">
              {{ $any(d).meetingTitle || $any(d).meetingId }}
            </a>
            @if ($any(d).meetingDate) {
              <span class="cfg__muted"> · {{ $any(d).meetingDate | ldate: 'mediumDate' }}</span>
            }
          </ng-template>
          <ng-template appCell="who" let-d>
            {{ $any(d).delegatorName || $any(d).delegatorId }} →
            {{ $any(d).delegateName || $any(d).delegateId }}
          </ng-template>
          <ng-template appCell="flags" let-d>
            @if ($any(d).delegateVoting) {
              <app-badge variant="info">{{ 'delegation.card.votingBadge' | t }}</app-badge>
            }
            @if ($any(d).viaPool) {
              <app-badge variant="neutral">{{ 'delegation.card.poolBadge' | t }}</app-badge>
            }
          </ng-template>
          <ng-template appCell="actions" let-d>
            <app-button
              variant="ghost"
              size="sm"
              [ariaLabel]="'admin.deleg.revoke' | t"
              (click)="askRevoke($any(d))"
            >
              {{ 'admin.deleg.revoke' | t }}
            </app-button>
          </ng-template>
        </app-data-table>
      }
    </section>

    <app-dialog
      [open]="confirmRevoke() !== null"
      [title]="'admin.deleg.revokeTitle' | t"
      [closeLabel]="'admin.deleg.cancel' | t"
      (closed)="confirmRevoke.set(null)"
    >
      <p>{{ 'admin.deleg.revokeConfirm' | t: { name: confirmRevoke()?.delegateName ?? '' } }}</p>
      <div dialog-footer class="cfg__row-foot">
        <app-button variant="ghost" (click)="confirmRevoke.set(null)">
          {{ 'admin.deleg.cancel' | t }}
        </app-button>
        <app-button variant="danger" [loading]="busy()" (click)="revoke()">
          {{ 'admin.deleg.revoke' | t }}
        </app-button>
      </div>
    </app-dialog>
  `,
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
