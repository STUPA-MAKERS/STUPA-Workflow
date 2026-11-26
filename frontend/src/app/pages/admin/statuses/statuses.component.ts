import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { type Observable, map } from 'rxjs';
import { problemCode } from '@core/api/problem';
import {
  STATUS_DATES,
  STATUS_PHASES,
  STATUS_TONES,
  type StatusDef,
  type StatusListKind,
  StatusCatalog,
} from '@core/api/statuses.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { setI18n } from '@shared/forms/i18n-text';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import {
  ButtonComponent,
  ButtonGroupComponent,
  IconComponent,
  InputComponent,
  NoteComponent,
  SelectFieldComponent,
  type SelectOption,
  SelectSheetComponent,
  type SelectSheetOption,
  StepListComponent,
  StepRowComponent,
} from '@stupa-makers/ui-kit';
import {
  ScreenGroupDirective,
  SettingsScreenComponent,
  type SettingsGroup,
  type SettingsState,
} from '@stupa-makers/ui-kit/screens';
import { AdminApiService } from '../admin-api.service';
import type { StatusListBody } from '../admin.models';
import {
  type ListDraft,
  type StatusRow,
  bodyOf,
  draftOf,
  elementsOf,
  listValid,
  missingPhases,
  nameText,
  newRow,
  removeRow,
  startRow,
  unchanged,
} from './statuses.util';

/** The most statuses of one list, as the server takes them. */
export const MAX_STATUSES = 30;

/** The permission of the page of each list (spec 003035). */
export const STATUS_LIST_PERMISSION: Readonly<Record<StatusListKind, string>> = {
  order: 'admin.order_statuses',
  event: 'admin.event_statuses',
};

/** The route data that names the list of the page. */
export const STATUS_LIST_DATA = 'statusList';

/** A delete that waits for the pick of a replacement. */
interface Deleting {
  readonly index: number;
  readonly row: StatusRow;
  /** The elements that move: the row's own and those it took from deleted rows. */
  readonly count: number;
}

/**
 * "Bestellzustände" (`/admin/order-statuses`) and "Veranstaltungszustände" (`/admin/event-statuses`):
 * one page per status list (spec 003035-003040). The route data `statusList` names the list,
 * and each page needs its own permission.
 *
 * Above the list the field "Startzustand" picks the start status of a new element among the
 * statuses of the kind `open`. The list is the kit step list without numbers, because the
 * statuses have no sequence (003040): per row the name and the delete, under it the selects of
 * the kind (`open`, `done`, `void`), the color and, for a Bestellung, the date that the status
 * sets; the add button under the list. A new status goes to the end.
 *
 * The delete of a stored row that elements have opens a select sheet: the admin picks the
 * row that takes the elements, and only the pick removes the row (003038). "Speichern" sends
 * the list; the server writes an audit entry and a config revision.
 */
@Component({
  selector: 'app-admin-statuses',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    SettingsScreenComponent,
    ScreenGroupDirective,
    ButtonComponent,
    ButtonGroupComponent,
    IconComponent,
    InputComponent,
      NoteComponent,
    SelectFieldComponent,
    SelectSheetComponent,
    StepListComponent,
    StepRowComponent,
  ],
  templateUrl: './statuses.component.html',
})
export class AdminStatusesComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly catalog = inject(StatusCatalog);

  /** The list of the page, from the route data. */
  protected readonly kind: StatusListKind =
    inject(ActivatedRoute).snapshot.data[STATUS_LIST_DATA] === 'event' ? 'event' : 'order';

  private readonly lang = computed(() => this.i18n.uiLocale());

  protected readonly form: SettingsForm<readonly StatusDef[], ListDraft> = settingsForm<
    readonly StatusDef[],
    ListDraft,
    StatusListBody
  >({
    allowed: () => this.auth.can(STATUS_LIST_PERMISSION[this.kind]),
    load: () => this.api.getStatusList(this.kind).pipe(map((list) => list.statuses)),
    put: (body) => this.put(body),
    draftOf,
    initial: { rows: [], replacements: {} },
    body: () => this.body(),
    unchanged,
    onApply: (stored) => this.catalog.set(this.kind, stored),
    errorText: (err) => this.errorText(err),
  });
  protected readonly draft = this.form.draft;

  /** The body of the save, or `null` while the list breaks a rule. */
  protected readonly body = computed<StatusListBody | null>(() => {
    const stored = this.form.saved();
    if (!stored) return null;
    const lang = this.lang();
    return listValid(this.draft(), stored, lang)
      ? bodyOf(this.kind, this.draft(), stored, lang)
      : null;
  });

  /** One group without a head: the page holds one list. */
  protected readonly groups: SettingsGroup[] = [{ key: 'list', rows: [] }];

  protected readonly title = computed(() =>
    this.i18n.translate(`admin.statuses.title.${this.kind}`),
  );

  protected readonly screenState = computed<SettingsState>(() => {
    switch (this.form.state()) {
      case 'loading':
        return { state: 'loading', skeleton: { variant: 'rows', count: 4 } };
      case 'forbidden':
        return {
          state: 'forbidden',
          message: this.i18n.translate(`admin.statuses.forbidden.${this.kind}`),
        };
      case 'error':
        return {
          state: 'error',
          message: this.i18n.translate('admin.statuses.loadError'),
          retry: () => this.form.reload(),
        };
      default:
        return { state: 'ready' };
    }
  });

  protected readonly phaseOptions = computed<SelectOption[]>(() =>
    STATUS_PHASES.map((phase) => ({
      value: phase,
      label: this.i18n.translate(`admin.statuses.phase.${phase}`),
    })),
  );

  protected readonly toneOptions = computed<SelectOption[]>(() =>
    STATUS_TONES.map((tone) => ({
      value: tone,
      label: this.i18n.translate(`admin.statuses.tone.${tone}`),
    })),
  );

  protected readonly dateOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.statuses.date.none') },
    ...STATUS_DATES.map((date) => ({
      value: date,
      label: this.i18n.translate(`admin.statuses.date.${date}`),
    })),
  ]);

  protected readonly rows = computed(() => this.draft().rows);

  /** The columns of the selects under a name: phase and color, and the date of a Bestellung. */
  protected readonly columns = computed(() => (this.kind === 'order' ? 3 : 2));

  /** The phases that the list misses, as one line under the list; empty when none. */
  protected readonly missing = computed(() => {
    const phases = missingPhases(this.rows());
    return phases.length
      ? this.i18n.translate('admin.statuses.missingPhase', {
          phases: phases.map((p) => this.i18n.translate(`admin.statuses.phase.${p}`)).join(', '),
        })
      : '';
  });

  protected readonly canAdd = computed(() => this.rows().length < MAX_STATUSES);

  /** The delete that waits for its replacement; `null` while the sheet is closed. */
  protected readonly deleting = signal<Deleting | null>(null);

  protected readonly deleteTitle = computed(() => {
    const d = this.deleting();
    return d
      ? this.i18n.translate('admin.statuses.delete.title', { name: this.name(d.row) || d.row.key })
      : '';
  });

  protected readonly deleteSub = computed(() => {
    const d = this.deleting();
    return d
      ? this.i18n.translate(`admin.statuses.delete.sub.${this.kind}`, { count: d.count })
      : '';
  });

  /** The stored rows that stay in the list: the targets of a replacement. */
  protected readonly targets = computed<SelectSheetOption[]>(() => {
    const d = this.deleting();
    return this.rows()
      .filter((row, i) => !row.fresh && i !== d?.index)
      .map((row) => ({ value: row.key, label: this.name(row) || row.key }));
  });

  protected name(row: StatusRow): string {
    return nameText(row.name, this.lang());
  }

  protected nameError(row: StatusRow): string {
    return this.name(row).trim() ? '' : this.i18n.translate('admin.statuses.nameRequired');
  }

  /** The statuses of the kind `open`: the choices of the start status (spec 003040). */
  protected readonly startOptions = computed<SelectOption[]>(() =>
    this.rows()
      .map((row, i) => ({ row, i }))
      .filter(({ row }) => row.phase === 'open')
      .map(({ row, i }) => ({ value: String(i), label: this.name(row) || row.key || '…' })),
  );

  /** The index of the start row as the value of the field, or '' while none is valid. */
  protected readonly startValue = computed(() => {
    const start = startRow(this.rows());
    return start ? String(this.rows().indexOf(start)) : '';
  });

  protected readonly startError = computed(() =>
    this.startValue() ? '' : this.i18n.translate('admin.statuses.startRequired'),
  );

  protected setStart(value: string): void {
    const index = Number(value);
    this.draft.update((list) => ({
      ...list,
      rows: list.rows.map((row, i) => (row.start === (i === index) ? row : { ...row, start: i === index })),
    }));
  }

  protected add(): void {
    this.draft.update((list) => ({ ...list, rows: [...list.rows, newRow()] }));
  }

  /** Delete a row; a stored row that elements have asks for its replacement first (003038). */
  protected remove(index: number): void {
    const row = this.rows()[index];
    if (!row) return;
    const count = elementsOf(row, this.draft(), this.form.saved() ?? []);
    if (count > 0) {
      this.deleting.set({ index, row, count });
      return;
    }
    this.draft.update((list) => removeRow(list, index, null));
  }

  /** The pick of the sheet: the row goes, and its elements move to `to` at the save. */
  protected replaceWith(to: string | readonly string[]): void {
    const d = this.deleting();
    if (!d || typeof to !== 'string') return;
    this.draft.update((list) => removeRow(list, d.index, to));
    this.deleting.set(null);
  }

  protected cancelDelete(): void {
    this.deleting.set(null);
  }

  protected setName(index: number, text: string): void {
    this.patchRow(index, (row) => ({ ...row, name: setI18n(row.name, this.lang(), text) }));
  }

  protected patch(index: number, change: Partial<StatusRow>): void {
    this.patchRow(index, (row) => ({ ...row, ...change }));
  }

  /** "Verwerfen": back to the stored list. */
  protected discard(): void {
    this.form.reset();
  }

  protected save(): void {
    this.form.save();
  }

  private patchRow(index: number, change: (row: StatusRow) => StatusRow): void {
    this.draft.update((list) => ({
      ...list,
      rows: list.rows.map((row, i) => (i === index ? change(row) : row)),
    }));
  }

  private put(body: StatusListBody): Observable<readonly StatusDef[]> {
    return this.api.putStatusList(this.kind, body).pipe(map((out) => out.statuses));
  }

  private errorText(err: unknown): string | null {
    switch (problemCode(err)) {
      case 'status_in_flow':
        return this.i18n.translate('admin.statuses.inFlow');
      case 'status_in_use':
        return this.i18n.translate('admin.statuses.inUse');
      default:
        return null;
    }
  }
}
