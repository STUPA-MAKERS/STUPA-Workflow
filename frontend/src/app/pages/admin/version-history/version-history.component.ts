import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CardComponent,
  ConfigDiffComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { ConfigRevision, ConfigRevisionDiff } from '../admin.models';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

/**
 * Version sidebar for the immutable config snapshots of an entity.
 *
 * An entity is a form, the flow, or the branding. The sidebar shows the field diff of
 * each snapshot. A restore writes an earlier state forward as a new active version.
 * The sidebar has no delete control on purpose. A version is never removable.
 *
 * `entityType` and `entityId` select the history to load.
 */
@Component({
  selector: 'app-version-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SkeletonComponent, 
    TranslatePipe,
    LocalizedDatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    ConfigDiffComponent,
    DialogComponent,
    IconComponent,
  ],
  templateUrl: './version-history.component.html',
  styleUrl: './version-history.component.scss',
})
export class VersionHistoryComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  readonly entityType = input.required<string>();
  readonly entityId = input.required<string>();
  /** Emits after a successful restore. The editor then reloads its state. */
  readonly restored = output<void>();

  protected readonly revisions = signal<ConfigRevision[]>([]);
  protected readonly loading = signal(false);
  protected readonly openDiffId = signal<string | null>(null);
  protected readonly diff = signal<ConfigRevisionDiff | null>(null);
  protected readonly confirmRestore = signal<ConfigRevision | null>(null);
  protected readonly restoring = signal(false);

  constructor() {
    effect(() => {
      const type = this.entityType();
      const id = this.entityId();
      if (type && id) this.load(type, id);
    });
  }

  /** Reload the list. The editor calls this after a save. */
  reload(): void {
    this.load(this.entityType(), this.entityId());
  }

  private load(type: string, id: string): void {
    this.loading.set(true);
    this.openDiffId.set(null);
    this.api.listConfigRevisions(type, id).subscribe({
      next: (rows) => {
        this.revisions.set(rows);
        this.loading.set(false);
      },
      error: () => {
        this.revisions.set([]);
        this.loading.set(false);
      },
    });
  }

  protected toggleDiff(rev: ConfigRevision): void {
    if (this.openDiffId() === rev.id) {
      this.openDiffId.set(null);
      return;
    }
    this.openDiffId.set(rev.id);
    this.diff.set(null);
    this.api.getConfigRevisionDiff(rev.id).subscribe({
      next: (d) => this.diff.set(d),
      error: () => this.diff.set(null),
    });
  }

  protected askRestore(rev: ConfigRevision): void {
    this.confirmRestore.set(rev);
  }

  protected doRestore(): void {
    const rev = this.confirmRestore();
    if (!rev) return;
    this.confirmRestore.set(null);
    this.restoring.set(true);
    this.api.restoreConfigRevision(rev.id).subscribe({
      next: () => {
        this.restoring.set(false);
        this.toast.success(
          this.i18n.translate('admin.config.restore.success', { version: rev.version }),
        );
        this.reload();
        this.restored.emit();
      },
      error: () => {
        this.restoring.set(false);
        this.toast.error(this.i18n.translate('admin.config.restore.error'));
      },
    });
  }

  protected actor(rev: ConfigRevision): string {
    return rev.createdByName ?? rev.createdBy ?? this.i18n.translate('admin.audit.system');
  }
}
