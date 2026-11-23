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
import type { Observable } from 'rxjs';
import { CalendarApiService } from '@core/api/calendar.service';
import {
  TICKET_KINDS,
  TicketsApiService,
  type TicketArea,
  type TicketDetail,
  type TicketKind,
  type TicketManualCreate,
} from '@core/api/tickets.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ChipComponent,
  DialogBodyDirective,
  DialogComponent,
  ErrorTextComponent,
  ToastService,
  type Action,
  type FieldDef,
  type FormDef,
} from '@stupa-makers/ui-kit';
import { FormComponent, type FormValue } from '@stupa-makers/ui-kit/screens';
import {
  GremiumPersonPickerComponent,
  type PickerHit,
  type PickerPerson,
} from '../../features/gremien/gremium-person-picker/gremium-person-picker.component';
import { KIND_LABEL } from './tickets.util';

/** The refusals of the create that have their own text. */
const CREATE_ERROR: Readonly<Record<string, TranslationKey>> = {
  ticket_reporter_invalid: 'tickets.new.error.person',
  ticket_area_without_mailbox: 'tickets.new.error.mailbox',
  category_invalid: 'tickets.new.error.category',
  mailbox_off: 'tickets.mail.off',
};

const ADDRESS = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** The address of the form when it is an e-mail address, else an empty text. */
export function manualAddress(value: FormValue): string {
  const address = String(value['email'] ?? '').trim();
  return ADDRESS.test(address) ? address : '';
}

/**
 * The body of the create from the form value and the chosen person. Without a person the
 * ticket is for the address of the form.
 */
export function manualBody(
  value: FormValue,
  area: TicketArea,
  personId: string | null,
): TicketManualCreate {
  const category = String(value['category'] ?? '');
  return {
    areaId: area.id,
    title: String(value['title'] ?? '').trim(),
    body: String(value['body'] ?? '').trim(),
    message: String(value['message'] ?? '').trim(),
    ...(personId ? { reporterId: personId } : { email: manualAddress(value) }),
    ...(area.platform
      ? { kind: (TICKET_KINDS.find((k) => k === category) ?? 'question') satisfies TicketKind }
      : category
        ? { categoryId: category }
        : {}),
  };
}

/**
 * "Ticket anlegen": a person of the team writes a ticket by hand for an account, for
 * example after a call. The fields are the Bereich (the own Bereiche), the person, the
 * title, the Kategorie, the note of the team and the first message to the person.
 *
 * The note stays with the team: the person reads only the title and the public messages
 * in the tab "Tickets". Without an account the ticket is for an e-mail address: the
 * Bereich then needs a Postfach, and the first message goes out as a mail.
 */
@Component({
  selector: 'app-ticket-new-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ChipComponent,
    DialogBodyDirective,
    DialogComponent,
    ErrorTextComponent,
    FormComponent,
    GremiumPersonPickerComponent,
  ],
  templateUrl: './ticket-new-dialog.component.html',
})
export class TicketNewDialogComponent {
  private readonly api = inject(TicketsApiService);
  private readonly calendar = inject(CalendarApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly formRef = viewChild(FormComponent);

  readonly open = input(false);
  /** The Bereiche in which the person works. */
  readonly areas = input<readonly TicketArea[]>([]);
  /** The Bereich that the list filters by, as the first choice. */
  readonly preset = input('');

  readonly closed = output<void>();
  readonly created = output<TicketDetail>();

  protected readonly value = signal<FormValue>({});
  protected readonly person = signal<PickerPerson | null>(null);
  protected readonly saving = signal(false);
  /** The person tried to save: a missing person shows its error. */
  protected readonly tried = signal(false);

  protected readonly area = computed(
    () => this.areas().find((a) => a.id === this.value()['areaId']) ?? this.areas()[0] ?? null,
  );
  /** Neither an account nor an e-mail address names the person of the ticket. */
  protected readonly personMissing = computed(() => !this.person() && !manualAddress(this.value()));
  protected readonly taken = computed(() => (this.person() ? [this.person()!.id] : []));
  protected readonly findPeople = (q: string): Observable<readonly PickerPerson[]> => this.calendar.people(q);

  protected readonly form = computed<FormDef>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const area = this.area();
    const areaField: readonly FieldDef[] =
      this.areas().length > 1
        ? [
            {
              key: 'areaId',
              kind: 'select',
              label: t('tickets.detail.area'),
              required: true,
              options: this.areas().map((a) => ({ value: a.id, label: a.name })),
            },
          ]
        : [];
    const categories = area?.platform
      ? TICKET_KINDS.map((k) => ({ value: k, label: t(KIND_LABEL[k]) }))
      : [
          { value: '', label: t('tickets.detail.noCategory') },
          ...(area?.categories ?? []).map((c) => ({ value: c.id, label: c.name })),
        ];
    const categoryField: readonly FieldDef[] =
      categories.length > 1
        ? [{ key: 'category', kind: 'select', label: t('tickets.detail.kind'), options: categories }]
        : [];
    const emailField: readonly FieldDef[] = this.person()
      ? []
      : [{ key: 'email', kind: 'text', label: t('tickets.new.email'), maxLength: 254 }];
    const fields: readonly FieldDef[] = [
      ...emailField,
      ...areaField,
      { key: 'title', kind: 'text', label: t('tickets.new.title'), required: true, maxLength: 200 },
      ...categoryField,
      {
        key: 'body',
        kind: 'textarea',
        label: t('tickets.new.body'),
        maxLength: 10000,
      },
      {
        key: 'message',
        kind: 'textarea',
        label: t('tickets.new.message'),
        maxLength: 10000,
      },
    ];
    return { sections: [{ key: 'ticket', fields }] };
  });

  protected readonly actions = computed<Action[]>(() => [
    { key: 'cancel', label: this.i18n.translate('action.cancel') },
    { key: 'save', label: this.i18n.translate('tickets.new.save'), kind: 'main', busy: this.saving() },
  ]);

  constructor() {
    effect(() => {
      if (!this.open()) return;
      const areas = this.areas();
      const preset = this.preset();
      untracked(() => {
        const first = areas.find((a) => a.id === preset) ?? areas[0] ?? null;
        this.saving.set(false);
        this.tried.set(false);
        this.person.set(null);
        this.value.set({
          areaId: first?.id ?? '',
          title: '',
          category: first?.platform ? 'question' : '',
          email: '',
          body: '',
          message: '',
        });
      });
    });
  }

  /** A change of the Bereich clears the Kategorie, because each Bereich has its own. */
  protected onValue(next: FormValue): void {
    const moved = next['areaId'] !== this.value()['areaId'];
    const target = this.areas().find((a) => a.id === next['areaId']);
    this.value.set(moved ? { ...next, category: target?.platform ? 'question' : '' } : next);
  }

  protected onPicked(hit: PickerHit): void {
    if (hit.kind === 'person') this.person.set({ id: hit.id, name: hit.name });
  }

  protected onAction(key: string): void {
    if (key === 'cancel') this.closed.emit();
    else this.save();
  }

  protected save(): void {
    this.tried.set(true);
    const area = this.area();
    const person = this.person();
    const formOk = this.formRef()?.showErrors() !== false;
    if (this.saving() || !formOk || !area || this.personMissing()) return;
    this.saving.set(true);
    this.api.createManual(manualBody(this.value(), area, person?.id ?? null)).subscribe({
      next: (ticket) => {
        this.saving.set(false);
        this.created.emit(ticket);
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.saving.set(false);
        const key = CREATE_ERROR[err.error?.code ?? ''] ?? 'tickets.new.error.save';
        this.toast.show(this.i18n.translate(key), 'error');
      },
    });
  }
}
