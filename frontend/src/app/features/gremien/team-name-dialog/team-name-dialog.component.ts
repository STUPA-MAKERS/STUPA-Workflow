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
import type { Uuid } from '@core/api/models';
import { problemCode } from '@core/api/problem';
import { type TeamDetail, TeamsApiService } from '@core/api/teams.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { DialogBodyDirective, DialogComponent, InputComponent, ToastService } from '@stupa-makers/ui-kit';

/**
 * The dialog that names a team: "Team anlegen" at the top (`team.create`), "Sub-Team
 * anlegen" under a parent (a manager of the parent, spec 003065), or "Umbenennen" of a free
 * team (`renameId`). `saved` gives the answer of the server to the host.
 */
@Component({
  selector: 'app-team-name-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DialogBodyDirective, DialogComponent, FormsModule, InputComponent, TranslatePipe],
  template: `
    <app-dialog
      [open]="open()"
      size="sm"
      [heading]="heading() | t"
      [closeLabel]="'action.close' | t"
      (closed)="open.set(false)"
      [actions]="[
        { key: 'cancel', label: ('action.cancel' | t) },
        { key: 'submit', label: (submitLabel() | t), kind: 'main', disabled: !valid(), busy: saving() },
      ]"
      (action)="$event.key === 'submit' ? submit() : open.set(false)"
    >
      <ng-template dialogBody>
        <form (submit)="$event.preventDefault(); submit()">
          <app-input
            name="teamName"
            id="team-name"
            [label]="'teams.name' | t"
            [required]="true"
            [ngModel]="name()"
            (ngModelChange)="name.set($event)"
          />
          <button type="submit" hidden></button>
        </form>
      </ng-template>
    </app-dialog>
  `,
})
export class TeamNameDialogComponent {
  private readonly api = inject(TeamsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = model(false);
  /** The parent of a new team; null for a team at the top. */
  readonly parentId = input<Uuid | null>(null);
  /** The free team to rename; null creates a team. */
  readonly renameId = input<Uuid | null>(null);
  /** The current name of the team to rename. */
  readonly current = input('');
  readonly saved = output<TeamDetail>();

  readonly name = signal('');
  readonly saving = signal(false);
  readonly valid = computed(() => this.name().trim().length > 0);
  readonly heading = computed<TranslationKey>(() =>
    this.renameId() ? 'teams.rename' : this.parentId() ? 'teams.createSub' : 'teams.create',
  );
  readonly submitLabel = computed<TranslationKey>(() => (this.renameId() ? 'action.save' : 'teams.createAction'));

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => this.name.set(this.renameId() ? this.current() : ''));
    });
  }

  submit(): void {
    if (!this.valid() || this.saving()) return;
    const name = this.name().trim();
    const id = this.renameId();
    this.saving.set(true);
    (id ? this.api.patch(id, { name }) : this.api.create(name, this.parentId())).subscribe({
      next: (detail) => {
        this.saving.set(false);
        this.open.set(false);
        this.saved.emit(detail);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        const key: TranslationKey =
          problemCode(err) === 'team_create_required' || problemCode(err) === 'team_manage_required'
            ? 'teams.toast.forbidden'
            : 'teams.toast.failed';
        this.toast.show(this.i18n.translate(key), 'error');
      },
    });
  }
}
