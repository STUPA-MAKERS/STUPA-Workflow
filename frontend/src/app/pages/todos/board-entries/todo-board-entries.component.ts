import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { map, type Observable } from 'rxjs';
import { TodosApiService, type TodoBoardEntry, type TodoEntryRole } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  AvatarComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
} from '@stupa-makers/ui-kit';
import { GremiumLogoComponent } from '../../../features/gremien/gremium-logo/gremium-logo.component';
import {
  GremiumPersonPickerComponent,
  type PickerHit,
  type PickerPerson,
  type PickerTeam,
} from '../../../features/gremien/gremium-person-picker/gremium-person-picker.component';

/** The roles in their order, with their names (spec 001062). */
export const ENTRY_ROLES: readonly { readonly role: TodoEntryRole; readonly label: TranslationKey }[] = [
  { role: 'read', label: 'todos.entries.role.read' },
  { role: 'edit', label: 'todos.entries.role.edit' },
  { role: 'manage', label: 'todos.entries.role.manage' },
];

/** An entry of the picker as a row before the server knows it (the dialog "Neues Board"). */
export function entryOf(hit: PickerHit, role: TodoEntryRole): TodoBoardEntry {
  return {
    id: null,
    kind: hit.kind,
    targetId: hit.id,
    name: hit.name,
    role,
    fixed: false,
    logoUrl: hit.kind === 'team' ? hit.logoUrl : null,
  };
}

/** The role of a new entry. */
export const NEW_ENTRY_ROLE: TodoEntryRole = 'edit';

/**
 * The member entries of a board (section "Mitglieder", spec 001064, 001077, 003068): each
 * team with its logo and each person with the avatar, its role, and a × that removes it.
 * The fixed own team of a team board shows its role only. The picker of spec 001074 adds
 * a team or a person with the role "Bearbeiten". The host saves each change, or
 * keeps the list itself (the dialog "Neues Board").
 */
@Component({
  selector: 'app-todo-board-entries',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    AvatarComponent,
    FilterSelectComponent,
    GremiumLogoComponent,
    GremiumPersonPickerComponent,
    IconComponent,
    TranslatePipe,
  ],
  templateUrl: './todo-board-entries.component.html',
  styleUrl: './todo-board-entries.component.scss',
})
export class TodoBoardEntriesComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);

  readonly entries = input.required<readonly TodoBoardEntry[]>();
  /** A request runs: the controls wait. */
  readonly busy = input(false);

  readonly added = output<{ readonly hit: PickerHit; readonly role: TodoEntryRole }>();
  readonly roleChanged = output<{ readonly entry: TodoBoardEntry; readonly role: TodoEntryRole }>();
  readonly removed = output<TodoBoardEntry>();

  readonly teams = signal<readonly PickerTeam[]>([]);
  readonly taken = computed(() => this.entries().map((e) => e.targetId));
  readonly roleOptions = computed<FilterSelectOption[]>(() =>
    ENTRY_ROLES.map((r) => ({ value: r.role, label: this.i18n.translate(r.label) })),
  );
  readonly findPeople = (q: string): Observable<readonly PickerPerson[]> =>
    this.api.entryOptions(q).pipe(map((o) => o.persons));

  constructor() {
    this.api.entryOptions().subscribe({
      next: (o) => this.teams.set(o.teams),
      error: () => this.teams.set([]),
    });
  }

  roleName(role: TodoEntryRole): string {
    return this.i18n.translate(ENTRY_ROLES.find((r) => r.role === role)?.label ?? 'todos.entries.role.edit');
  }

  /** The key of a row: the id, or the target for the fixed team and a new entry. */
  key(entry: TodoBoardEntry): string {
    return entry.id ?? `${entry.kind}:${entry.targetId}`;
  }

  setRole(entry: TodoBoardEntry, value: string): void {
    const role = ENTRY_ROLES.find((r) => r.role === value)?.role;
    if (role && role !== entry.role) this.roleChanged.emit({ entry, role });
  }

  add(hit: PickerHit): void {
    this.added.emit({ hit, role: NEW_ENTRY_ROLE });
  }
}
