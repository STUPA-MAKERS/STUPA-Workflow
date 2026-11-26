import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import type { Uuid } from '@core/api/models';
import type { TodoBoardEntry, TodoEntryRole } from '@core/api/todos.service';
import { type TeamDetail, type TeamMember, type TeamRole, TeamsApiService } from '@core/api/teams.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { ToastService } from '@stupa-makers/ui-kit';
import { TodoBoardEntriesComponent } from '../../../pages/todos/board-entries/todo-board-entries.component';
import type { PickerHit } from '../gremium-person-picker/gremium-person-picker.component';

/** The two roles of a free team, shown on the board roles `edit` and `manage` (spec 003063). */
export const TEAM_ROLES: readonly { readonly role: TodoEntryRole; readonly label: TranslationKey }[] = [
  { role: 'edit', label: 'teams.role.member' },
  { role: 'manage', label: 'teams.role.manager' },
];

const roleOf = (role: TodoEntryRole): TeamRole => (role === 'manage' ? 'manager' : 'member');

/** A member of a free team as a row of the entry list; only a manager changes it. */
export function memberEntry(m: TeamMember, editable: boolean): TodoBoardEntry {
  return {
    id: m.principalId,
    kind: 'person',
    targetId: m.principalId,
    name: m.displayName,
    role: m.role === 'manager' ? 'manage' : 'edit',
    fixed: !editable,
    logoUrl: null,
  };
}

/**
 * The tab "Mitglieder" of a free team (spec 003063): each person with the role "Mitglied" or
 * "Verwaltung". A manager adds a person with the picker, changes a role and removes a person;
 * the server keeps the last manager (409 `last_manager`). The list is the entry list of a
 * board with the two team roles, so the tab needs no styles of its own.
 */
@Component({
  selector: 'app-team-members',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TodoBoardEntriesComponent],
  template: `
    <app-todo-board-entries
      [entries]="entries()"
      [roles]="roles"
      [withTeams]="false"
      [editable]="canManage()"
      [busy]="busy()"
      listLabel="gremien.tab.members"
      addLabel="teams.members.add"
      (added)="add($event.hit)"
      (roleChanged)="setRole($event.entry, $event.role)"
      (removed)="remove($event)"
    />
  `,
})
export class TeamMembersComponent {
  private readonly api = inject(TeamsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly teamId = input.required<Uuid>();
  readonly canManage = input(false);
  /** A write changed the team: the host reads the list again (the own role may change). */
  readonly changed = output<TeamDetail>();

  protected readonly roles = TEAM_ROLES;
  readonly detail = signal<TeamDetail | null>(null);
  readonly busy = signal(false);
  readonly entries = computed(() =>
    (this.detail()?.members ?? []).map((m) => memberEntry(m, this.canManage())),
  );

  constructor() {
    effect(() => {
      const id = this.teamId();
      this.api.detail(id).subscribe({ next: (d) => this.detail.set(d), error: () => this.detail.set(null) });
    });
  }

  add(hit: PickerHit): void {
    if (hit.kind !== 'person') return;
    this.write(this.api.setMember(this.teamId(), hit.id, 'member'));
  }

  setRole(entry: TodoBoardEntry, role: TodoEntryRole): void {
    this.write(this.api.setMember(this.teamId(), entry.targetId, roleOf(role)));
  }

  remove(entry: TodoBoardEntry): void {
    this.write(this.api.removeMember(this.teamId(), entry.targetId));
  }

  private write(req: ReturnType<TeamsApiService['setMember']>): void {
    this.busy.set(true);
    req.subscribe({
      next: (d) => {
        this.detail.set(d);
        this.busy.set(false);
        this.changed.emit(d);
      },
      error: (err: { error?: { code?: string } }) => {
        this.busy.set(false);
        const key: TranslationKey =
          err.error?.code === 'last_manager' ? 'teams.toast.lastManager' : 'teams.toast.failed';
        this.toast.show(this.i18n.translate(key), 'error');
      },
    });
  }
}
