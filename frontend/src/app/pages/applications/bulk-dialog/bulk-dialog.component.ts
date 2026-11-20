import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { BulkItemResult, BulkTransitionOption, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { formatMoney } from '@shared/format-money';
import {
  ButtonComponent,
  DialogComponent,
  EmptyStateComponent,
  IconComponent,
  ScrollFadeDirective,
  SkeletonComponent,
  ErrorTextComponent,
} from '@stupa-makers/ui-kit';

/** The two bulk actions of the Antrag list (001700). */
export type BulkMode = 'transition' | 'message';

/** One selected Antrag, as the list shows it. */
export interface BulkTarget {
  readonly id: Uuid;
  readonly title: string;
}

/** One line of the result (001703): the Antrag and "Erledigt" or the error text. */
interface ResultLine {
  readonly id: Uuid;
  readonly title: string;
  readonly ok: boolean;
  readonly text: string;
}

/** Most Anträge one bulk action takes (001700). */
export const BULK_MAX = 100;

/**
 * A bulk action on the selected Anträge of the list.
 *
 * `transition` (001701) loads the targets that every selected Antrag reaches and lists the
 * requested amounts of an approving target before the confirm. `message` (001702) sends
 * one public comment to each Antrag. Both end in the result list of 001703: the server runs
 * each Antrag on its own, so one error does not stop the others. `done` fires after the
 * action ran, so the list can load again.
 */
@Component({
  selector: 'app-bulk-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ErrorTextComponent,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    EmptyStateComponent,
    IconComponent,
    ScrollFadeDirective,
    SkeletonComponent,
  ],
  templateUrl: './bulk-dialog.component.html',
  styleUrl: './bulk-dialog.component.scss',
})
export class BulkDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);

  readonly open = model(false);
  readonly mode = input<BulkMode>('transition');
  readonly targets = input<readonly BulkTarget[]>([]);
  /** The action ran; the list loads again. */
  readonly done = output<void>();

  /** The selection as the dialog opened: a reload of the list does not change the result. */
  private readonly snapshot = signal<readonly BulkTarget[]>([]);
  readonly loading = signal(false);
  readonly options = signal<readonly BulkTransitionOption[]>([]);
  readonly pick = signal<Uuid | null>(null);
  readonly body = signal('');
  readonly running = signal(false);
  readonly failed = signal(false);
  readonly results = signal<readonly ResultLine[] | null>(null);

  readonly title = computed(() =>
    this.i18n.translate(
      this.mode() === 'transition' ? 'applications.bulk.transition' : 'applications.bulk.message',
    ),
  );
  readonly subtitle = computed(() =>
    this.i18n.translate('applications.bulk.count', { count: String(this.snapshot().length) }),
  );
  readonly chosen = computed(() => this.options().find((o) => o.toStateId === this.pick()) ?? null);
  /** The requested amounts that an approving target approves, by Antrag (001701). */
  readonly amounts = computed(() =>
    (this.chosen()?.amounts ?? []).map((a) => ({
      id: a.applicationId,
      title: a.title?.trim() || this.titleOf(a.applicationId),
      amount: a.amount === null ? '' : formatMoney(a.amount, this.i18n.formatLocale()) || a.amount,
    })),
  );
  readonly canConfirm = computed(() => {
    if (this.running() || this.results()) return false;
    return this.mode() === 'transition' ? this.chosen() !== null : this.body().trim() !== '';
  });
  readonly okCount = computed(() => (this.results() ?? []).filter((r) => r.ok).length);

  private seq = 0;

  constructor() {
    effect(() => {
      const open = this.open();
      untracked(() => {
        if (open) this.reset();
      });
    });
  }

  close(): void {
    this.open.set(false);
  }

  private reset(): void {
    this.snapshot.set(this.targets());
    this.pick.set(null);
    this.body.set('');
    this.results.set(null);
    this.failed.set(false);
    this.options.set([]);
    if (this.mode() !== 'transition') return;
    this.seq = this.seq + 1;
    const seq = this.seq;
    this.loading.set(true);
    this.api.bulkTransitions(this.ids()).subscribe({
      next: (options) => {
        if (seq !== this.seq) return;
        this.loading.set(false);
        this.options.set(options);
      },
      error: () => {
        if (seq !== this.seq) return;
        this.loading.set(false);
        this.failed.set(true);
      },
    });
  }

  submit(): void {
    if (!this.canConfirm()) return;
    const choice = this.chosen();
    const call: Observable<readonly BulkItemResult[]> =
      this.mode() === 'transition' && choice
        ? this.api.fireBulkTransition(this.ids(), choice.toStateId)
        : this.api.bulkComment(this.ids(), this.body().trim());
    this.running.set(true);
    this.failed.set(false);
    call.subscribe({
      next: (results) => {
        this.running.set(false);
        this.results.set(results.map((r) => this.line(r)));
        this.done.emit();
      },
      error: () => {
        this.running.set(false);
        this.failed.set(true);
      },
    });
  }

  private ids(): Uuid[] {
    return this.snapshot().map((t) => t.id);
  }

  private titleOf(id: Uuid): string {
    return (
      this.snapshot().find((t) => t.id === id)?.title ??
      this.i18n.translate('applications.list.untitled')
    );
  }

  private line(r: BulkItemResult): ResultLine {
    const text = r.ok
      ? this.i18n.translate('applications.bulk.ok')
      : r.error || this.i18n.translate('applications.actions.error');
    return { id: r.applicationId, title: this.titleOf(r.applicationId), ok: r.ok, text };
  }
}
