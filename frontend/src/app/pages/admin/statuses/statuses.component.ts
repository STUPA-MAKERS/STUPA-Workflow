import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { type Observable, forkJoin, map, of } from 'rxjs';
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
import { FeatureService } from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { setI18n } from '@shared/forms/i18n-text';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import {
  ButtonComponent,
  ButtonGroupComponent,
  IconComponent,
  InputComponent,
  MoveButtonsComponent,
  NoteComponent,
  SelectFieldComponent,
  type SelectOption,
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
  type Removed,
  type StatusRow,
  bodyOf,
  draftOf,
  listValid,
  missingPhases,
  moveRow,
  nameText,
  newRow,
  removedInUse,
  unchanged,
} from './statuses.util';

type Stored = Readonly<Record<StatusListKind, readonly StatusDef[]>>;
type Draft = Readonly<Record<StatusListKind, ListDraft>>;
/** The lists that the save sends: only a changed list. */
type Body = Readonly<Partial<Record<StatusListKind, StatusListBody>>>;

const KINDS: readonly StatusListKind[] = ['order', 'event'];

/** The most statuses of one list, as the server takes them. */
export const MAX_STATUSES = 30;

const TITLE: Readonly<Record<StatusListKind, TranslationKey>> = {
  order: 'admin.statuses.order',
  event: 'admin.statuses.event',
};

/**
 * "Status & Phasen" (`/admin/statuses`, permission `admin.statuses`, spec 003035-003040).
 *
 * One section per kind of element with a status list: the Bestellungen (while the feature
 * is on) and the Veranstaltungen. Each section edits its statuses like the steps of a
 * Haushaltsplan under Budgets: a numbered list, per row the name, the buttons up and down
 * and the delete, under it the selects of the phase, the color and, for a Bestellung, the
 * date that the status sets; "+ Status" under the list. The order of the list is the
 * position, and the first status is the start status of a new element, so it needs the
 * phase `open`.
 *
 * A removed status that elements have needs a replacement of the same list (003038): the
 * section lists it with a select under the statuses, and the save moves its elements.
 * "Speichern" sends each changed list; the server writes an audit entry and a config
 * revision for each.
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
    MoveButtonsComponent,
    NoteComponent,
    SelectFieldComponent,
  ],
  templateUrl: './statuses.component.html',
  styleUrl: './statuses.component.scss',
})
export class AdminStatusesComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly features = inject(FeatureService);
  private readonly catalog = inject(StatusCatalog);

  /** The lists of the page: the Bestellungen only while their feature is on. */
  protected readonly kinds = computed<readonly StatusListKind[]>(() =>
    KINDS.filter((kind) => kind !== 'order' || this.features.isOn('orders')),
  );

  private readonly lang = computed(() => this.i18n.uiLocale());

  protected readonly form: SettingsForm<Stored, Draft> = settingsForm<Stored, Draft, Body>({
    allowed: () => this.auth.can('admin.statuses'),
    load: () =>
      forkJoin({ order: this.api.getStatusList('order'), event: this.api.getStatusList('event') }).pipe(
        map(({ order, event }) => ({ order: order.statuses, event: event.statuses })),
      ),
    put: (body) => this.put(body),
    draftOf: (stored) => ({ order: draftOf(stored.order), event: draftOf(stored.event) }),
    initial: { order: { rows: [], replacements: {} }, event: { rows: [], replacements: {} } },
    body: () => this.body(),
    unchanged: (body) => Object.keys(body).length === 0,
    onApply: (stored) => KINDS.forEach((kind) => this.catalog.set(kind, stored[kind])),
    errorText: (err) => this.errorText(err),
  });
  protected readonly draft = this.form.draft;

  /** The body of the save, or `null` while a list breaks a rule. */
  protected readonly body = computed<Body | null>(() => {
    const stored = this.form.saved();
    if (!stored) return null;
    const draft = this.draft();
    const lang = this.lang();
    if (!KINDS.every((kind) => listValid(draft[kind], stored[kind], lang))) return null;
    return Object.fromEntries(
      KINDS.map((kind) => [kind, bodyOf(kind, draft[kind], stored[kind], lang)] as const).filter(
        ([kind, body]) => !unchanged(body, stored[kind]),
      ),
    );
  });

  protected readonly groups = computed<SettingsGroup[]>(() =>
    this.kinds().map((kind) => ({ key: kind, label: this.i18n.translate(TITLE[kind]), rows: [] })),
  );

  protected readonly screenState = computed<SettingsState>(() => {
    switch (this.form.state()) {
      case 'loading':
        return { state: 'loading', skeleton: { variant: 'rows', count: 4 } };
      case 'forbidden':
        return { state: 'forbidden', message: this.i18n.translate('admin.statuses.forbidden') };
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
    STATUS_PHASES.map((phase) => ({ value: phase, label: this.i18n.translate(`admin.statuses.phase.${phase}`) })),
  );

  protected readonly toneOptions = computed<SelectOption[]>(() =>
    STATUS_TONES.map((tone) => ({ value: tone, label: this.i18n.translate(`admin.statuses.tone.${tone}`) })),
  );

  protected readonly dateOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.statuses.date.none') },
    ...STATUS_DATES.map((date) => ({ value: date, label: this.i18n.translate(`admin.statuses.date.${date}`) })),
  ]);

  protected rows(kind: StatusListKind): readonly StatusRow[] {
    return this.draft()[kind].rows;
  }

  protected name(row: StatusRow): string {
    return nameText(row.name, this.lang());
  }

  protected nameError(row: StatusRow): string {
    return this.name(row).trim() ? '' : this.i18n.translate('admin.statuses.nameRequired');
  }

  /** The first status is the start status, so its phase is `open` (spec 003035). */
  protected phaseError(kind: StatusListKind, index: number): string {
    return index === 0 && this.rows(kind)[0]?.phase !== 'open'
      ? this.i18n.translate('admin.statuses.startOpen')
      : '';
  }

  /** The phases that the list misses, as one line under the list; empty when none. */
  protected missing(kind: StatusListKind): string {
    const phases = missingPhases(this.rows(kind));
    return phases.length
      ? this.i18n.translate('admin.statuses.missingPhase', {
          phases: phases.map((p) => this.i18n.translate(`admin.statuses.phase.${p}`)).join(', '),
        })
      : '';
  }

  /** The removed statuses that elements have; each needs a replacement. */
  protected removed(kind: StatusListKind): readonly Removed[] {
    const stored = this.form.saved()?.[kind] ?? [];
    return removedInUse(stored, this.rows(kind));
  }

  protected removedLabel(kind: StatusListKind, removed: Removed): string {
    return this.i18n.translate(`admin.statuses.replace.${kind}`, {
      name: nameText(removed.name, this.lang()) || removed.key,
      count: removed.used,
    });
  }

  /** The stored statuses that stay in the list: the targets of a replacement. */
  protected replacementOptions(kind: StatusListKind): SelectOption[] {
    return this.rows(kind)
      .filter((row) => !row.fresh)
      .map((row) => ({ value: row.key, label: this.name(row) || row.key }));
  }

  protected replacement(kind: StatusListKind, key: string): string {
    return this.draft()[kind].replacements[key] ?? '';
  }

  protected setReplacement(kind: StatusListKind, key: string, to: string | null): void {
    this.patchList(kind, (list) => ({ ...list, replacements: { ...list.replacements, [key]: to ?? '' } }));
  }

  protected canAdd(kind: StatusListKind): boolean {
    return this.rows(kind).length < MAX_STATUSES;
  }

  protected add(kind: StatusListKind): void {
    this.patchList(kind, (list) => ({ ...list, rows: [...list.rows, newRow()] }));
  }

  protected remove(kind: StatusListKind, index: number): void {
    this.patchList(kind, (list) => ({ ...list, rows: list.rows.filter((_, i) => i !== index) }));
  }

  protected move(kind: StatusListKind, index: number, by: -1 | 1): void {
    this.patchList(kind, (list) => ({ ...list, rows: moveRow(list.rows, index, by) }));
  }

  protected setName(kind: StatusListKind, index: number, text: string): void {
    this.patchRow(kind, index, (row) => ({ ...row, name: setI18n(row.name, this.lang(), text) }));
  }

  protected patch(kind: StatusListKind, index: number, change: Partial<StatusRow>): void {
    this.patchRow(kind, index, (row) => ({ ...row, ...change }));
  }

  /** "Verwerfen": back to the stored lists. */
  protected discard(): void {
    this.form.reset();
  }

  protected save(): void {
    this.form.save();
  }

  private patchRow(kind: StatusListKind, index: number, change: (row: StatusRow) => StatusRow): void {
    this.patchList(kind, (list) => ({ ...list, rows: list.rows.map((row, i) => (i === index ? change(row) : row)) }));
  }

  private patchList(kind: StatusListKind, change: (list: ListDraft) => ListDraft): void {
    this.draft.update((draft) => ({ ...draft, [kind]: change(draft[kind]) }));
  }

  /** Save each changed list; the answer is both stored lists. */
  private put(body: Body): Observable<Stored> {
    const stored = this.form.saved() ?? { order: [], event: [] };
    const calls = KINDS.map((kind) => {
      const list = body[kind];
      return list ? this.api.putStatusList(kind, list).pipe(map((out) => out.statuses)) : of(stored[kind]);
    });
    return forkJoin(calls).pipe(map(([order, event]) => ({ order, event })));
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
