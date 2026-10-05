import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  FilterSelectComponent,
  type FilterSelectOption,
  PageHeaderComponent,
  SkeletonComponent,
} from '@shared/ui';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { Gremium } from '../admin.models';
import { SubstitutePoolComponent } from './substitute-pool.component';

/** Today as a local `YYYY-MM-DD` date, the format of `Delegation.meetingDate`. */
export function localToday(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * The admin overview of the delegations (`/admin/delegations`, board Admin-Vertretung).
 *
 * "Aktive Vertretungen": the delegations of the meetings from today on (or without a
 * date), newest meeting last, each with meeting, date, from → to, the tags "Stimmrecht"
 * and "Pool", and "Widerrufen" (danger, with a confirmation). An admin may revoke at any
 * time. The delegations of past meetings stay behind "Frühere Vertretungen".
 *
 * "Stellvertretungen": the substitute pool of one gremium (`app-substitute-pool`); the
 * gremium chip picks the gremium. A member creates the own delegation on the meeting
 * page; the gremium must allow it.
 */
@Component({
  selector: 'app-delegations',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    FilterSelectComponent,
    PageHeaderComponent,
    SkeletonComponent,
    SubstitutePoolComponent,
  ],
  templateUrl: './delegations.component.html',
  styleUrl: './delegations.component.scss',
})
export class DelegationsComponent {
  private readonly api = inject(DelegationsApiService);
  private readonly admin = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly delegations = signal<Delegation[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly busy = signal(false);
  protected readonly confirmRevoke = signal<Delegation | null>(null);
  protected readonly showPast = signal(false);

  protected readonly gremien = signal<Gremium[]>([]);
  protected readonly gremiumId = signal('');

  private readonly today = localToday();

  /** A delegation of a meeting from today on, or of a meeting without a date. */
  private isActive(d: Delegation): boolean {
    return !d.meetingDate || d.meetingDate >= this.today;
  }

  /** By meeting date, then by meeting title. */
  private sort(list: Delegation[], dir: 1 | -1): Delegation[] {
    return [...list].sort(
      (a, b) =>
        dir * (a.meetingDate ?? '9999').localeCompare(b.meetingDate ?? '9999') ||
        (a.meetingTitle ?? '').localeCompare(b.meetingTitle ?? ''),
    );
  }

  protected readonly active = computed(() =>
    this.sort(
      this.delegations().filter((d) => this.isActive(d)),
      1,
    ),
  );
  protected readonly past = computed(() =>
    this.sort(
      this.delegations().filter((d) => !this.isActive(d)),
      -1,
    ),
  );

  protected readonly gremiumOptions = computed<FilterSelectOption[]>(() =>
    this.gremien().map((g) => ({ value: g.id, label: g.name })),
  );
  protected readonly poolGremiumId = computed(() => this.gremiumId() as Uuid);

  constructor() {
    this.reload();
    this.admin.listGremienOptions().subscribe({
      // The server order; the first gremium opens.
      next: (list) => {
        this.gremien.set(list);
        if (!this.gremiumId() && list.length) this.gremiumId.set(list[0].id);
      },
      error: () => this.gremien.set([]),
    });
  }

  protected who(d: Delegation, side: 'from' | 'to'): string {
    const name = side === 'from' ? d.delegatorName : d.delegateName;
    return name || this.i18n.translate('admin.gremien.unknownMember');
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
