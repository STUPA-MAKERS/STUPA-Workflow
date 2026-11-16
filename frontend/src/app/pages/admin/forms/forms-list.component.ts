import { FeatureService } from '@core/features/feature.service';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { I18nMap, Uuid } from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import {
  FabComponent,
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  ConfirmDialogComponent,
  DataTableComponent,
  DialogComponent,
  EmptyStateComponent,
  IconComponent,
  InputComponent,
  MoveButtonsComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SectionComponent,
  SelectFieldComponent,
  type SelectFieldOption,
  TextareaComponent,
  StatusTextComponent,
  ToastService,
  PageHeaderComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { AdminApiService } from '../admin-api.service';
import {
  type ApplicationTypeFull,
  type ApplicationTypeGroupFull,
  type Gremium,
  slugify,
} from '../admin.models';
import { renderMarkdown } from '../../../features/meetings/meetings.util';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';

/** Edit state of the create dialog: title in DE and EN, Gremium, and budget flag. */
interface NewForm {
  readonly nameDe: string;
  readonly nameEn: string;
  readonly gremiumId: string;
  readonly hasBudget: boolean;
}

function emptyForm(): NewForm {
  return { nameDe: '', nameEn: '', gremiumId: '', hasBudget: false };
}

/** Edit state of the group dialog: the name and the Markdown text in DE and EN. */
interface GroupForm {
  readonly nameDe: string;
  readonly nameEn: string;
  readonly textDe: string;
  readonly textEn: string;
}

function emptyGroupForm(): GroupForm {
  return { nameDe: '', nameEn: '', textDe: '', textEn: '' };
}

/** One block of the page: a group with its types, or the types without a group. */
interface TypeBlock {
  readonly id: string;
  /** `null` for the types without a group. */
  readonly group: ApplicationTypeGroupFull | null;
  readonly types: readonly ApplicationTypeFull[];
}

/**
 * Overview of the forms and application types.
 *
 * The table lists all application types: the name, the Gremium, "Mit Budget" or
 * "Ohne Budget", the status as text (Aktiv while a form version is active, else Entwurf)
 * and the number of the active form version. A dialog creates a new type. It asks for the
 * title in DE and EN and the budget flag. The key comes from the DE title automatically.
 * The name and the edit icon open the subpage of the form (`/admin/forms/:id`).
 *
 * The types stand by group (specs 001180, 001183): each group is a section with its name,
 * its text, the arrows that move it and a menu to edit or delete it; the types without a
 * group follow under "Weitere Anträge". Without a group the page is one table, as before.
 * The arrows of a row move the type inside its group, and its menu changes the group. The
 * order is the order of step 1 of the apply wizard.
 */
@Component({
  selector: 'app-forms-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LoadStateComponent,
    FabComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    FormsModule,
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    InputComponent,
    PageHeaderComponent,
    BreadcrumbsComponent,
    StatusTextComponent,
    RowMenuComponent,
    IconComponent,
    MoveButtonsComponent,
    SectionComponent,
    SelectFieldComponent,
    TextareaComponent,
  ],
  templateUrl: './forms-list.component.html',
  styleUrl: './forms-list.component.scss',
})
export class FormsListComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  /** "Mit Budget" shows only while `Budget` is on (spec 000761). */
  protected readonly budgetOn = inject(FeatureService).isOn('budget');
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  /**
   * Create posts to `POST /api/admin/application-types`, which needs `admin.types`.
   * The page itself opens on `form.configure`, so a form manager reaches it without
   * that key. Without this gate the button is offered and the save answers 403.
   * The gate is UX only. The server stays authoritative.
   */
  protected readonly canCreate = computed(() => this.auth.can('admin.types'));

  /** Delete needs its own permission. This gate is UX only. The server is authoritative. */
  protected readonly canDelete = computed(() => this.auth.can('admin.types_delete'));
  protected readonly confirmDelete = signal<ApplicationTypeFull | null>(null);
  /**
   * The ⋮ menu of each type, by type id: move up and down inside its group, change the
   * group, delete. The moves sit in the menu, not as arrows in the row, so the table keeps
   * the width of its columns. The row itself opens the editor.
   */
  protected readonly rowMenus = computed<ReadonlyMap<string, readonly RowMenuSection[]>>(() => {
    const edit = this.canCreate();
    const del = this.canDelete();
    const atEnd = this.i18n.translate('admin.forms.moveAtEnd');
    return new Map(
      this.blocks().flatMap((b) =>
        b.types.map((t, i) => {
          const sections: RowMenuSection[] = [
            ...(edit
              ? [
                  {
                    items: [
                      {
                        id: 'up',
                        label: this.i18n.translate('admin.forms.moveUp'),
                        icon: 'up' as const,
                        disabledReason: i === 0 ? atEnd : null,
                      },
                      {
                        id: 'down',
                        label: this.i18n.translate('admin.forms.moveDown'),
                        icon: 'down' as const,
                        disabledReason: i === b.types.length - 1 ? atEnd : null,
                      },
                      { id: 'group', label: this.i18n.translate('admin.forms.groupChange'), icon: 'tag' as const },
                    ],
                  },
                ]
              : []),
            ...(del
              ? [
                  {
                    items: [
                      {
                        id: 'delete',
                        label: this.i18n.translate('admin.forms.delete'),
                        icon: 'trash' as const,
                        danger: true,
                      },
                    ],
                  },
                ]
              : []),
          ];
          return [t.id, sections] as const;
        }),
      ),
    );
  });
  /** The ⋮ menu of a group: edit and delete. */
  protected readonly groupMenu = computed<RowMenuSection[]>(() => [
    {
      items: [
        { id: 'edit', label: this.i18n.translate('admin.forms.groupEdit'), icon: 'edit' },
        { id: 'delete', label: this.i18n.translate('admin.forms.groupDelete'), icon: 'trash', danger: true },
      ],
    },
  ]);

  protected readonly groups = signal<ApplicationTypeGroupFull[]>([]);
  /**
   * The blocks of the page in the order of step 1: the groups, then the types without a
   * group (a type of an unknown group counts as one without a group). The server sends
   * both lists in their order.
   */
  protected readonly blocks = computed<readonly TypeBlock[]>(() => {
    const types = this.types();
    const groups = this.groups();
    const known = new Set(groups.map((g) => g.id));
    const rest = types.filter((t) => !t.groupId || !known.has(t.groupId));
    return [
      ...groups.map((g) => ({ id: g.id, group: g, types: types.filter((t) => t.groupId === g.id) })),
      ...(rest.length || !groups.length ? [{ id: 'other', group: null, types: rest }] : []),
    ];
  });

  protected open(type: ApplicationTypeFull): void {
    void this.router.navigate(['/admin/forms', type.id]);
  }
  protected readonly deleting = signal(false);

  protected readonly types = signal<ApplicationTypeFull[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  private readonly gremien = signal<Gremium[]>([]);
  private readonly gremiumMap = computed(() => new Map(this.gremien().map((g) => [g.id, g.name])));

  protected readonly dialogOpen = signal(false);
  protected readonly saving = signal(false);
  protected readonly form = signal<NewForm>(emptyForm());

  /** The group dialog: `null` closed, `'new'` creates, else the group it edits. */
  protected readonly groupDialog = signal<ApplicationTypeGroupFull | 'new' | null>(null);
  protected readonly groupForm = signal<GroupForm>(emptyGroupForm());
  protected readonly confirmGroupDelete = signal<ApplicationTypeGroupFull | null>(null);
  /** The type whose group the "Gruppe ändern" dialog changes, and the picked group id. */
  protected readonly regroup = signal<ApplicationTypeFull | null>(null);
  protected readonly regroupTo = signal('');
  /** The options of a group choice: "Keine Gruppe", then every group. */
  protected readonly groupOptions = computed<SelectFieldOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.forms.groupNone') },
    ...this.groups().map((g) => ({ value: g.id, label: this.groupName(g) })),
  ]);

  /**
   * The dropdown source is the authenticated /committees, not admin/committees, so a form manager with
   * form.configure fills the Gremium column without the admin.gremien permission.
   */
  constructor() {
    this.reload();
    this.api.listGremienOptions().subscribe({
      next: (g) => this.gremien.set(g),
      error: () => this.gremien.set([]),
    });
  }

  /** The retry of the load error. */
  protected retryLoad(): void {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    forkJoin([this.api.listApplicationTypesFull(), this.api.listApplicationTypeGroups()]).subscribe({
      next: ([t, g]) => {
        this.types.set(t);
        this.groups.set(g);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.forms.col.name'), card: 'title' },
    { key: 'gremium', label: this.i18n.translate('admin.forms.col.gremium') },
    ...(this.budgetOn
      ? [{ key: 'budget', label: this.i18n.translate('admin.forms.col.budget'), width: '8rem' }]
      : []),
    { key: 'status', label: this.i18n.translate('admin.forms.col.status'), width: '7rem' },
    { key: 'version', label: this.i18n.translate('admin.forms.col.version'), width: '5rem' },
    {
      key: 'actions',
      label: this.i18n.translate('admin.common.actions'),
      align: 'end',
      width: '3.5rem',
      card: 'actions',
    },
  ]);
  protected readonly rowId = (t: unknown): string => (t as ApplicationTypeFull).id;

  protected readonly keyPreview = computed(() => slugify(this.form().nameDe) || '—');

  protected name(t: ApplicationTypeFull): string {
    return resolveI18n(t.name, this.i18n.uiLocale()) || this.i18n.translate('admin.forms.untitled');
  }

  /** "v7" for the active form version, a dash while the type is a draft. */
  protected versionLabel(t: ApplicationTypeFull): string {
    return t.activeFormVersion ? `v${t.activeFormVersion}` : '—';
  }

  protected groupName(g: ApplicationTypeGroupFull): string {
    return resolveI18n(g.name, this.i18n.uiLocale()) || this.i18n.translate('admin.forms.untitled');
  }

  /** The text of a group as rendered Markdown, in the UI language; empty without one. */
  protected groupText(g: ApplicationTypeGroupFull): string {
    const text = resolveI18n(g.text, this.i18n.uiLocale()).trim();
    return text ? renderMarkdown(text) : '';
  }

  /** The heading of a block: the group name, or "Weitere Anträge" next to groups. */
  protected blockHeading(b: TypeBlock): string {
    if (b.group) return this.groupName(b.group);
    return this.groups().length ? this.i18n.translate('apply.type.other') : '';
  }

  /** A menu choice of a type row. */
  protected typeAction(t: ApplicationTypeFull, item: RowMenuItem): void {
    if (item.id === 'delete') this.askDelete(t);
    else if (item.id === 'up' || item.id === 'down') this.moveType(t, item.id === 'up' ? -1 : 1);
    else if (item.id === 'group') {
      this.regroupTo.set(t.groupId ?? '');
      this.regroup.set(t);
    }
  }

  /** Move a type one place inside its group (spec 001183). */
  protected moveType(t: ApplicationTypeFull, by: -1 | 1): void {
    this.api.moveApplicationType(t.id, by).subscribe({
      next: (list) => this.types.set(list),
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  /** Move a group one place (spec 001183). */
  protected moveGroup(g: ApplicationTypeGroupFull, by: -1 | 1): void {
    this.api.moveApplicationTypeGroup(g.id, by).subscribe({
      next: (list) => this.groups.set(list),
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  /** Save the group of the "Gruppe ändern" dialog; the type goes to the end of the group. */
  protected saveRegroup(): void {
    const t = this.regroup();
    if (!t || this.saving()) return;
    const groupId = this.regroupTo() || null;
    if (groupId === (t.groupId ?? null)) {
      this.regroup.set(null);
      return;
    }
    this.saving.set(true);
    this.api.updateApplicationType(t.id, { groupId }).subscribe({
      next: () => {
        this.saving.set(false);
        this.regroup.set(null);
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.reload();
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  protected openGroupCreate(): void {
    if (!this.canCreate()) return;
    this.groupForm.set(emptyGroupForm());
    this.groupDialog.set('new');
  }

  /** A menu choice of a group. */
  protected groupAction(g: ApplicationTypeGroupFull, item: RowMenuItem): void {
    if (item.id === 'delete') {
      this.confirmGroupDelete.set(g);
      return;
    }
    this.groupForm.set({
      nameDe: g.name['de'] ?? '',
      nameEn: g.name['en'] ?? '',
      textDe: g.text['de'] ?? '',
      textEn: g.text['en'] ?? '',
    });
    this.groupDialog.set(g);
  }

  protected patchGroup<K extends keyof GroupForm>(key: K, value: GroupForm[K]): void {
    this.groupForm.update((f) => ({ ...f, [key]: value }));
  }

  /** Create or change the group of the dialog. Empty languages are not sent. */
  protected saveGroup(event: Event): void {
    event.preventDefault();
    const target = this.groupDialog();
    const f = this.groupForm();
    const nameDe = f.nameDe.trim();
    if (!target || !nameDe || this.saving()) return;
    const name: I18nMap = f.nameEn.trim() ? { de: nameDe, en: f.nameEn.trim() } : { de: nameDe };
    const text: I18nMap = {
      ...(f.textDe.trim() ? { de: f.textDe.trim() } : {}),
      ...(f.textEn.trim() ? { en: f.textEn.trim() } : {}),
    };
    this.saving.set(true);
    const save$ =
      target === 'new'
        ? this.api.createApplicationTypeGroup({ name, text })
        : this.api.updateApplicationTypeGroup(target.id, { name, text });
    save$.subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.groupDialog.set(null);
        this.groups.update((list) =>
          target === 'new' ? [...list, saved] : list.map((g) => (g.id === saved.id ? saved : g)),
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  /** Delete the group of the confirm dialog; its types stay without a group (spec 001180). */
  protected deleteGroup(): void {
    const g = this.confirmGroupDelete();
    if (!g || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteApplicationTypeGroup(g.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmGroupDelete.set(null);
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.reload();
      },
      error: () => {
        this.deleting.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  protected gremiumName(id?: Uuid | null): string {
    return (id && this.gremiumMap().get(id)) || '—';
  }

  protected patch<K extends keyof NewForm>(key: K, value: NewForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  protected openCreate(): void {
    if (!this.canCreate()) return;
    this.form.set(emptyForm());
    this.dialogOpen.set(true);
  }

  protected confirmDeleteName(): string {
    const t = this.confirmDelete();
    return t ? this.name(t) : '';
  }

  protected askDelete(t: ApplicationTypeFull): void {
    this.confirmDelete.set(t);
  }

  protected cancelDelete(): void {
    this.confirmDelete.set(null);
  }

  protected confirmDeleteType(): void {
    const t = this.confirmDelete();
    if (!t || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteApplicationType(t.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(null);
        this.types.update((rows) => rows.filter((r) => r.id !== t.id));
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => {
        this.deleting.set(false);
        this.toast.error(this.i18n.translate('admin.forms.deleteFailed'));
      },
    });
  }

  protected closeDialog(): void {
    this.dialogOpen.set(false);
  }

  protected submit(event: Event): void {
    event.preventDefault();
    const f = this.form();
    const nameDe = f.nameDe.trim();
    if (!nameDe || this.saving()) return;
    const name: I18nMap = { de: nameDe, en: f.nameEn.trim() };
    this.saving.set(true);
    this.api
      .createApplicationType({
        key: slugify(nameDe),
        name,
        gremiumId: f.gremiumId || null,
        hasBudget: f.hasBudget,
      })
      .subscribe({
        next: (created) => {
          this.saving.set(false);
          this.dialogOpen.set(false);
          this.toast.success(this.i18n.translate('admin.common.saved'));
          this.router.navigate(['/admin/forms', created.id]);
        },
        error: () => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate('admin.common.saveFailed'));
        },
      });
  }
}
