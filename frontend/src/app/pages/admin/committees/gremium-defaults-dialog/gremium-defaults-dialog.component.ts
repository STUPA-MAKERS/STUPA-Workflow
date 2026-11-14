import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  InputComponent,
  SkeletonComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { LoadStateComponent, loadStateOf } from '@shared/ui/load-state/load-state.component';
import { AdminApiService } from '../../admin-api.service';
import type { GremiumDefaults } from '../../admin.models';
import { MAX_DELEGATION_LEAD_MINUTES, percentOrNull } from '../gremium-dialog/gremium-dialog.component';

/**
 * "Vorgaben für neue Gremien": the values that the form of a new Gremium starts with
 * (§ 000906): the quorum, the quorum of a Wiederholungssitzung, the guest ballot, the
 * vote delegation and its lead time. A save changes no Gremium that exists.
 */
@Component({
  selector: 'app-gremium-defaults-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    InputComponent,
    SkeletonComponent,
    SwitchComponent,
    LoadStateComponent,
  ],
  templateUrl: './gremium-defaults-dialog.component.html',
  styleUrl: './gremium-defaults-dialog.component.scss',
})
export class GremiumDefaultsDialogComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  readonly closed = output<void>();

  protected readonly form = signal<GremiumDefaults | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal(false);
  protected readonly state = loadStateOf(this.loading, this.loadError);
  protected readonly saving = signal(false);

  constructor() {
    effect(() => {
      if (this.open()) untracked(() => this.load());
    });
  }

  /** Read the stored values; also the retry of the load error. */
  protected load(): void {
    this.form.set(null);
    this.saving.set(false);
    this.loadError.set(false);
    this.loading.set(true);
    this.api.getGremiumDefaults().subscribe({
      next: (d) => {
        this.form.set(d);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  protected patch(change: Partial<GremiumDefaults>): void {
    this.form.update((f) => (f ? { ...f, ...change } : f));
  }

  protected patchPercent(key: 'quorumPercent' | 'repeatQuorumPercent', value: number | string | null): void {
    this.patch({ [key]: percentOrNull(value) });
  }

  /** Lead time: empty or invalid gives 0, else whole minutes from 0 to 30 days. */
  protected patchLead(value: number | string | null): void {
    const n = Math.round(Number(value));
    this.patch({
      delegationLeadMinutes: Number.isFinite(n)
        ? Math.min(MAX_DELEGATION_LEAD_MINUTES, Math.max(0, n))
        : 0,
    });
  }

  protected close(): void {
    this.closed.emit();
  }

  protected save(): void {
    const body = this.form();
    if (!body || this.saving()) return;
    this.saving.set(true);
    this.api.putGremiumDefaults(body).subscribe({
      next: () => {
        this.saving.set(false);
        this.toast.success(this.i18n.translate('admin.gremien.defaults.saved'));
        this.closed.emit();
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.gremien.defaults.saveFailed'));
      },
    });
  }
}
