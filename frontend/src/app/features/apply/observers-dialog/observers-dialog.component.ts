import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationObserver, Uuid } from '@core/api/models';
import { problemCode } from '@core/api/problem';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  AvatarComponent,
  ButtonComponent,
  DialogComponent,
  EmptyStateComponent,
  IconComponent,
  InputComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ToastService,
} from '@stupa-makers/ui-kit';

/** The most observers of one Antrag (`MAX_OBSERVERS` of the server). */
export const MAX_OBSERVERS = 5;

/** The field message of each refusal code of `POST /observers`. */
const REFUSALS: Readonly<Record<string, TranslationKey>> = {
  observer_exists: 'observers.error.exists',
  observer_is_applicant: 'observers.error.applicant',
  observer_limit: 'observers.error.limit',
};

/**
 * The dialog "Beobachter:innen" of an Antrag (spec 000751): the list of the observers, a
 * row menu per observer that removes it, and the field that adds an address. The field
 * hides at `MAX_OBSERVERS`. The dialog loads the list each time it opens.
 *
 * The answers never tell whether an address belongs to an account
 * (`NF/security/access/000278`), so the dialog shows only the address.
 */
@Component({
  selector: 'app-observers-dialog',
  standalone: true,
  imports: [
    FormsModule,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    IconComponent,
    InputComponent,
    AvatarComponent,
    RowMenuComponent,
    EmptyStateComponent,
  ],
  templateUrl: './observers-dialog.component.html',
  styleUrl: './observers-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ObserversDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input.required<Uuid>();
  readonly open = input(false);
  readonly closed = output<void>();

  readonly observers = signal<readonly ApplicationObserver[]>([]);
  readonly loading = signal(false);
  readonly text = signal('');
  readonly error = signal<TranslationKey | null>(null);
  readonly saving = signal(false);
  readonly full = computed(() => this.observers().length >= MAX_OBSERVERS);

  constructor() {
    effect(() => {
      if (this.open()) untracked(() => this.load());
    });
  }

  /** The row menu of one observer. */
  menu(observer: ApplicationObserver): RowMenuSection[] {
    return [
      {
        items: [
          {
            id: observer.id,
            label: this.i18n.translate('observers.remove'),
            icon: 'trash',
            danger: true,
          },
        ],
      },
    ];
  }

  private load(): void {
    const id = this.applicationId();
    this.loading.set(true);
    this.error.set(null);
    this.text.set('');
    this.api.applicationObservers(id).subscribe({
      next: (list) => {
        this.observers.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.observers.set([]);
        this.loading.set(false);
        this.toast.error(this.i18n.translate('observers.error.load'));
      },
    });
  }

  /** Add the address of the field. */
  add(): void {
    const email = this.text().trim();
    if (!email || this.saving()) return;
    this.saving.set(true);
    this.error.set(null);
    this.api.addApplicationObserver(this.applicationId(), email).subscribe({
      next: (row) => {
        this.observers.update((list) => [...list, row]);
        this.text.set('');
        this.saving.set(false);
        this.toast.success(this.i18n.translate('observers.added'));
      },
      error: (err: unknown) => {
        this.saving.set(false);
        const code = problemCode(err);
        const refusal = REFUSALS[code];
        if (refusal) this.error.set(refusal);
        else if (code === '' && (err as { status?: number }).status === 422)
          this.error.set('observers.error.email');
        else this.toast.error(this.i18n.translate('observers.error.save'));
      },
    });
  }

  /** Remove the observer of a row menu item. */
  remove(item: RowMenuItem): void {
    const observerId = item.id;
    this.api.removeApplicationObserver(this.applicationId(), observerId).subscribe({
      next: () => {
        this.observers.update((list) => list.filter((o) => o.id !== observerId));
        this.toast.success(this.i18n.translate('observers.removed'));
      },
      error: () => this.toast.error(this.i18n.translate('observers.error.save')),
    });
  }

  /** The field changed: its message goes. */
  onText(value: string): void {
    this.text.set(value);
    this.error.set(null);
  }
}
