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
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { weekdayDate } from '@shared/date-format';
import { ToastService } from '@stupa-makers/ui-kit';
import { type PickRow, TodoPickDialogComponent } from '../pick-dialog/todo-pick-dialog.component';

/**
 * "Auf Tagesordnung setzen" of a card on the board of a Gremium or on a free board (spec
 * 000553, 001069): pick one of the planned meetings, by Gremium and the next one first, and
 * the card becomes a TOP of it. Meetings of several Gremien name their Gremium.
 * The card menu passes the meetings, so it can hide the item when there is none.
 */
@Component({
  selector: 'app-todo-agenda-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TodoPickDialogComponent],
  templateUrl: './todo-agenda-dialog.component.html',
})
export class TodoAgendaDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = model(false);
  readonly cardId = input.required<Uuid>();
  /** The planned meetings whose agenda the person edits, the next one first. */
  readonly meetings = input.required<readonly Meeting[]>();
  readonly added = output<Uuid>();

  readonly pick = signal<Uuid | null>(null);
  readonly busy = signal(false);

  readonly rows = computed<PickRow[]>(() => {
    const locale = this.i18n.formatLocale();
    const several = new Set(this.meetings().map((m) => m.gremiumId)).size > 1;
    return this.meetings().map((m) => ({
      id: m.id,
      title: m.title,
      sub: [
        several ? m.gremiumName : null,
        m.date ? weekdayDate(m.date, locale) : null,
        m.startTime ? m.startTime.slice(0, 5) : null,
      ]
        .filter(Boolean)
        .join(' · '),
    }));
  });

  readonly heading = this.i18n.translate('todos.agenda.title');
  readonly listLabel = this.i18n.translate('todos.agenda.meetings');
  readonly emptyHeading = this.i18n.translate('todos.agenda.none');
  readonly submitLabel = this.i18n.translate('todos.agenda.submit');

  constructor() {
    effect(() => {
      if (!this.open()) return;
      const first = this.meetings()[0]?.id ?? null;
      untracked(() => this.pick.set(first));
    });
  }

  submit(meetingId: Uuid): void {
    this.busy.set(true);
    this.api.addAgendaTodo(meetingId, this.cardId()).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.show({ text: this.i18n.translate('todos.agenda.done'), kind: 'success' });
        this.added.emit(meetingId);
        this.open.set(false);
      },
      error: (err: { error?: { code?: string } }) => {
        this.busy.set(false);
        const taken = err?.error?.code === 'todo_already_on_agenda';
        this.toast.show({
          text: this.i18n.translate(taken ? 'todos.agenda.taken' : 'todos.agenda.error'),
          kind: 'error',
        });
      },
    });
  }
}
