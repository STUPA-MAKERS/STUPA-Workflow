import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { longDate } from '@shared/date-format';
import { LoadStateComponent, loadStateOf } from '@shared/ui/load-state/load-state.component';
import {
  ButtonComponent,
  DialogComponent,
  EmptyStateComponent,
  SelectFieldComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';

/**
 * The meetings that can approve the protocol of `own`: the later ones of the same Gremium
 * that run or are closed. A planned meeting has approved nothing yet.
 */
export function approvalCandidates(own: Meeting, all: readonly Meeting[]): readonly Meeting[] {
  const later = all.filter(
    (m) => m.id !== own.id && m.status !== 'planned' && (m.date ?? '') >= (own.date ?? ''),
  );
  return [...later].sort((a, b) => (a.date ?? '').localeCompare(b.date ?? ''));
}

/**
 * "Als genehmigt markieren": pick the meeting that approved a final protocol (§ 000924).
 *
 * The list holds the later meetings of the same Gremium that started, the next one first
 * and preselected, because a Gremium approves a protocol in its next Sitzung. A failed
 * read shows the error with "Erneut versuchen", not the empty list. The dialog only
 * picks; the caller saves.
 */
@Component({
  selector: 'app-protocol-approval-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    SelectFieldComponent,
    EmptyStateComponent,
    LoadStateComponent,
  ],
  templateUrl: './protocol-approval-dialog.component.html',
})
export class ProtocolApprovalDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);

  readonly open = input(false);
  /** The meeting of the protocol. */
  readonly meeting = input.required<Meeting>();
  readonly saving = input(false);
  readonly closed = output<void>();
  /** "Markieren": the meeting that approved the protocol. */
  readonly picked = output<Uuid>();

  readonly meetings = signal<readonly Meeting[]>([]);
  readonly loading = signal(false);
  readonly failed = signal(false);
  readonly state = loadStateOf(this.loading, this.failed);
  readonly choice = signal('');

  readonly options = computed<SelectOption[]>(() => {
    const locale = this.i18n.formatLocale();
    return this.meetings().map((m) => ({
      value: m.id,
      label: [m.title, longDate(m.date ?? '', locale)].filter(Boolean).join(' · '),
    }));
  });
  /** The read answered and no later meeting that started exists. */
  readonly none = computed(() => this.state() === 'ok' && !this.meetings().length);

  constructor() {
    effect(() => {
      if (this.open()) untracked(() => this.load());
    });
  }

  load(): void {
    const own = this.meeting();
    this.meetings.set([]);
    this.loading.set(true);
    this.failed.set(false);
    this.choice.set('');
    this.api.listMeetings(own.gremiumId ?? undefined).subscribe({
      next: (all) => {
        const candidates = approvalCandidates(own, all);
        this.meetings.set(candidates);
        this.choice.set(candidates[0]?.id ?? '');
        this.loading.set(false);
      },
      error: () => {
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  cancel(): void {
    this.closed.emit();
  }

  submit(): void {
    if (this.choice() && !this.saving()) this.picked.emit(this.choice());
  }
}
