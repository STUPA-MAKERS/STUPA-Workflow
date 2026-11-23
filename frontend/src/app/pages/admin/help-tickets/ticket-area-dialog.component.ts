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
  viewChild,
} from '@angular/core';
import type { Uuid } from '@core/api/models';
import {
  TicketsApiService,
  type TicketArea,
  type TicketAreaInput,
} from '@core/api/tickets.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ConfirmDialogComponent,
  DialogBodyDirective,
  DialogComponent,
  ToastService,
  type Action,
  type FieldDef,
  type FormDef,
} from '@stupa-makers/ui-kit';
import { FormComponent, type FormValue } from '@stupa-makers/ui-kit/screens';

/** A Gremium of the select. */
export interface AreaGremium {
  readonly id: Uuid;
  readonly name: string;
}

/** The refusals of a save or a delete that have their own text. */
const AREA_ERROR: Readonly<Record<string, TranslationKey>> = {
  ticket_area_name_taken: 'admin.helpTickets.areas.error.nameTaken',
  ticket_area_has_tickets: 'admin.helpTickets.areas.error.hasTickets',
  ticket_categories_invalid: 'admin.helpTickets.areas.error.categories',
};

/** The names of the Kategorie rows of a form value. */
function categoryNames(value: FormValue): readonly string[] {
  const rows = Array.isArray(value['categories']) ? (value['categories'] as unknown[]) : [];
  return rows.map((row) => String((row as { name?: unknown } | null)?.name ?? ''));
}

/**
 * The ids of the Kategorie rows after one change of the form. The form reports only the
 * names, so the ids follow the three changes a person can make: a new row at the end
 * (no id), a removed row (its id goes) and a changed name (the ids stay).
 */
export function idsAfter(
  before: readonly string[],
  ids: readonly (Uuid | null)[],
  after: readonly string[],
): readonly (Uuid | null)[] {
  if (after.length > before.length) {
    return [...ids, ...after.slice(before.length).map(() => null)];
  }
  if (after.length < before.length) {
    const differs = after.findIndex((name, i) => name !== before[i]);
    const gone = differs < 0 ? after.length : differs;
    return ids.filter((_, i) => i !== gone);
  }
  return ids;
}

/**
 * The dialog that creates or edits one Bereich of the tickets, with the form of the kit.
 *
 * The fields are the name, the Gremium whose roles give the work right `ticket.work`
 * (none: only the holders of `ticket.manage` work in the Bereich), the switches "Neue
 * Tickets per E-Mail" and "In der App erreichbar" (a signed-in person can choose the
 * Bereich in the ticket dialog of the help menu) and the list of the Kategorien in their order. The Bereich
 * "Plattform" keeps its name, has no Gremium and has the four kinds of a report as its
 * Kategorien, so its dialog shows only a note and the switch. "Bereich löschen" shows for
 * a stored Bereich other than "Plattform"; the server refuses it while the Bereich holds
 * a ticket.
 */
@Component({
  selector: 'app-ticket-area-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ConfirmDialogComponent, DialogBodyDirective, DialogComponent, FormComponent],
  templateUrl: './ticket-area-dialog.component.html',
})
export class TicketAreaDialogComponent {
  private readonly api = inject(TicketsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly formRef = viewChild(FormComponent);

  readonly open = input(false);
  /** The Bereich to edit. `null` creates a new one. */
  readonly area = input<TicketArea | null>(null);
  readonly gremien = input<readonly AreaGremium[]>([]);

  readonly closed = output<void>();
  readonly saved = output<TicketArea>();
  readonly deleted = output<TicketArea>();

  /** The value of the form; the ids of its Kategorie rows stand in `ids`. */
  protected readonly value = signal<FormValue>({});
  private readonly ids = signal<readonly (Uuid | null)[]>([]);
  protected readonly saving = signal(false);
  protected readonly confirmDelete = signal(false);
  /** The answer of the server to the last save, shown under the name (409). */
  protected readonly errors = signal<Readonly<Record<string, string>>>({});

  protected readonly isNew = computed(() => this.area() === null);
  protected readonly platform = computed(() => this.area()?.platform === true);
  protected readonly title = computed<TranslationKey>(() =>
    this.isNew() ? 'admin.helpTickets.areas.create' : 'admin.helpTickets.areas.edit',
  );

  protected readonly form = computed<FormDef>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const notify: FieldDef = { key: 'notifyNew', kind: 'switch', label: t('admin.helpTickets.notify') };
    if (this.platform()) {
      const note: FieldDef = {
        key: 'note',
        kind: 'display',
        label: '',
        text: t('admin.helpTickets.areas.platformNote'),
      };
      return { sections: [{ key: 'area', fields: [note, notify] }] };
    }
    const fields: readonly FieldDef[] = [
      {
        key: 'name',
        kind: 'text',
        label: t('admin.helpTickets.areas.name'),
        required: true,
        maxLength: 80,
      },
      {
        key: 'gremiumId',
        kind: 'select',
        label: t('admin.helpTickets.areas.gremium'),
        options: [
          { value: '', label: t('admin.helpTickets.areas.noGremium') },
          ...this.gremien().map((g) => ({ value: g.id, label: g.name })),
        ],
      },
      notify,
      { key: 'inApp', kind: 'switch', label: t('admin.helpTickets.areas.inApp') },
      {
        key: 'categories',
        kind: 'repeat',
        label: t('admin.helpTickets.areas.categories'),
        addLabel: t('admin.helpTickets.areas.categoryAdd'),
        max: 50,
        fields: [
          {
            key: 'name',
            kind: 'text',
            label: t('admin.helpTickets.areas.category'),
            required: true,
            maxLength: 80,
          },
        ],
      },
    ];
    return { sections: [{ key: 'area', fields }] };
  });

  protected readonly actions = computed<Action[]>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const remove: Action[] =
      this.area() && !this.platform()
        ? [{ key: 'delete', label: t('admin.helpTickets.areas.delete'), kind: 'danger' }]
        : [];
    return [
      ...remove,
      { key: 'cancel', label: t('action.cancel') },
      { key: 'save', label: t('action.save'), kind: 'main', busy: this.saving() },
    ];
  });

  constructor() {
    effect(() => {
      if (!this.open()) return;
      const area = this.area();
      untracked(() => {
        this.errors.set({});
        this.saving.set(false);
        this.confirmDelete.set(false);
        this.ids.set((area?.categories ?? []).map((c) => c.id));
        this.value.set({
          name: area?.name ?? '',
          gremiumId: area?.gremiumId ?? '',
          notifyNew: area?.notifyNew ?? true,
          inApp: area?.inApp ?? false,
          categories: (area?.categories ?? []).map((c) => ({ name: c.name })),
        });
      });
    });
  }

  protected onValue(next: FormValue): void {
    this.ids.update((ids) => idsAfter(categoryNames(this.value()), ids, categoryNames(next)));
    this.value.set(next);
  }

  protected close(): void {
    this.closed.emit();
  }

  protected onAction(key: string): void {
    if (key === 'delete') this.confirmDelete.set(true);
    else if (key === 'cancel') this.close();
    else this.save();
  }

  private body(): TicketAreaInput {
    const v = this.value();
    const ids = this.ids();
    return {
      name: String(v['name'] ?? '').trim(),
      gremiumId: (v['gremiumId'] as string) || null,
      notifyNew: v['notifyNew'] === true,
      inApp: v['inApp'] === true,
      categories: categoryNames(v).map((name, i) => ({
        ...(ids[i] ? { id: ids[i] } : {}),
        name: name.trim(),
      })),
    };
  }

  protected save(): void {
    if (this.saving() || this.formRef()?.showErrors() === false) return;
    const area = this.area();
    const body = this.body();
    const req = !area
      ? this.api.createArea(body)
      : area.platform
        ? this.api.updateArea(area.id, { notifyNew: body.notifyNew })
        : this.api.updateArea(area.id, body);
    this.saving.set(true);
    req.subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.saved.emit(saved);
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.saving.set(false);
        const code = err.error?.code ?? '';
        if (code === 'ticket_area_name_taken') {
          this.errors.set({ name: this.i18n.translate(AREA_ERROR[code]) });
          return;
        }
        this.toast.show(
          this.i18n.translate(AREA_ERROR[code] ?? 'admin.helpTickets.areas.error.save'),
          'error',
        );
      },
    });
  }

  protected doDelete(): void {
    const area = this.area();
    this.confirmDelete.set(false);
    if (!area || this.saving()) return;
    this.saving.set(true);
    this.api.deleteArea(area.id).subscribe({
      next: () => {
        this.saving.set(false);
        this.deleted.emit(area);
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.saving.set(false);
        const code = err.error?.code ?? '';
        this.toast.show(
          this.i18n.translate(AREA_ERROR[code] ?? 'admin.helpTickets.areas.error.delete'),
          'error',
        );
      },
    });
  }
}
