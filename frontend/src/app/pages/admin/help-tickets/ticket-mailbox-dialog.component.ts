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
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  TicketsApiService,
  type TicketArea,
  type TicketMailbox,
  type TicketMailboxInput,
  type TicketMailboxTest,
} from '@core/api/tickets.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ConfirmDialogComponent,
  DialogBodyDirective,
  DialogComponent,
  InputComponent,
  NoteComponent,
  SectionComponent,
  SwitchComponent,
  ToastService,
  type Action,
} from '@stupa-makers/ui-kit';

/** The folder for done mails of a new Postfach, as on the server. */
export const DEFAULT_DONE_FOLDER = 'Erledigt';

/** The text fields of the dialog; a port is text until the save. */
export interface MailboxDraft {
  readonly address: string;
  readonly imapHost: string;
  readonly imapPort: string;
  readonly imapUser: string;
  readonly imapPassword: string;
  readonly smtpHost: string;
  readonly smtpPort: string;
  readonly smtpUser: string;
  readonly smtpPassword: string;
  readonly doneFolder: string;
  readonly enabled: boolean;
}

type TextField = Exclude<keyof MailboxDraft, 'enabled'>;

/** The four fields of one account. */
interface Side {
  readonly key: 'imap' | 'smtp';
  readonly heading: TranslationKey;
  readonly host: TextField;
  readonly port: TextField;
  readonly user: TextField;
  readonly password: TextField;
}

const SIDES: readonly Side[] = [
  {
    key: 'imap',
    heading: 'admin.helpTickets.mailbox.imap',
    host: 'imapHost',
    port: 'imapPort',
    user: 'imapUser',
    password: 'imapPassword',
  },
  {
    key: 'smtp',
    heading: 'admin.helpTickets.mailbox.smtp',
    host: 'smtpHost',
    port: 'smtpPort',
    user: 'smtpUser',
    password: 'smtpPassword',
  },
];

/** The cause codes of a connection that have their own text. */
const CAUSES: Readonly<Record<string, TranslationKey>> = {
  connect_failed: 'admin.helpTickets.mailbox.cause.connect_failed',
  timeout: 'admin.helpTickets.mailbox.cause.timeout',
  tls_failed: 'admin.helpTickets.mailbox.cause.tls_failed',
  tls_missing: 'admin.helpTickets.mailbox.cause.tls_missing',
  login_failed: 'admin.helpTickets.mailbox.cause.login_failed',
};

const ADDRESS = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** The draft of a stored Postfach, or of a new one with the usual TLS ports. */
export function draftOf(mailbox: TicketMailbox | null): MailboxDraft {
  return {
    address: mailbox?.address ?? '',
    imapHost: mailbox?.imapHost ?? '',
    imapPort: String(mailbox?.imapPort ?? 993),
    imapUser: mailbox?.imapUser ?? '',
    imapPassword: '',
    smtpHost: mailbox?.smtpHost ?? '',
    smtpPort: String(mailbox?.smtpPort ?? 465),
    smtpUser: mailbox?.smtpUser ?? '',
    smtpPassword: '',
    doneFolder: mailbox?.doneFolder ?? DEFAULT_DONE_FOLDER,
    enabled: mailbox?.enabled ?? false,
  };
}

/** True for a whole number from 1 to 65535. */
function isPort(text: string): boolean {
  const n = Number(text);
  return /^\d+$/.test(text.trim()) && n >= 1 && n <= 65535;
}

/**
 * The fields that a person must still fill or correct, by field. A stored Postfach keeps
 * a password that the draft leaves empty.
 */
export function draftErrors(
  draft: MailboxDraft,
  stored: boolean,
): Readonly<Partial<Record<TextField, TranslationKey>>> {
  const required: readonly TextField[] = [
    'address',
    'imapHost',
    'imapUser',
    'smtpHost',
    'smtpUser',
    'doneFolder',
    ...(stored ? [] : (['imapPassword', 'smtpPassword'] as const)),
  ];
  const missing = required
    .filter((field) => !draft[field].trim())
    .map((field) => [field, 'admin.helpTickets.mailbox.required'] as const);
  const address =
    draft.address.trim() && !ADDRESS.test(draft.address.trim())
      ? [['address', 'admin.helpTickets.mailbox.addressInvalid'] as const]
      : [];
  const ports = (['imapPort', 'smtpPort'] as const)
    .filter((field) => !isPort(draft[field]))
    .map((field) => [field, 'admin.helpTickets.mailbox.portInvalid'] as const);
  return Object.fromEntries([...missing, ...address, ...ports]);
}

/** The body of a save: every field, and a password only when the person typed one. */
export function mailboxBody(draft: MailboxDraft): Partial<TicketMailboxInput> {
  return {
    address: draft.address.trim(),
    imapHost: draft.imapHost.trim().toLowerCase(),
    imapPort: Number(draft.imapPort),
    imapUser: draft.imapUser.trim(),
    ...(draft.imapPassword ? { imapPassword: draft.imapPassword } : {}),
    smtpHost: draft.smtpHost.trim().toLowerCase(),
    smtpPort: Number(draft.smtpPort),
    smtpUser: draft.smtpUser.trim(),
    ...(draft.smtpPassword ? { smtpPassword: draft.smtpPassword } : {}),
    doneFolder: draft.doneFolder.trim(),
    enabled: draft.enabled,
  };
}

/**
 * The dialog of the Postfach of one Bereich (`admin.ticket_mail`): the address, the switch,
 * the IMAP and the SMTP account and the folder for done mails.
 *
 * No read returns a password, so both password fields start empty; an empty field keeps
 * the stored password. "Verbindung testen" logs in to both accounts of the stored Postfach
 * and shows each result, so it is off while the draft has a change. The server refuses a
 * host outside the deploy setting `TICKET_MAIL_HOST_ALLOWLIST`; the dialog then names the
 * allowed hosts under the field. "Postfach entfernen" asks first.
 */
@Component({
  selector: 'app-ticket-mailbox-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ConfirmDialogComponent,
    DialogBodyDirective,
    DialogComponent,
    InputComponent,
    NoteComponent,
    SectionComponent,
    SwitchComponent,
  ],
  templateUrl: './ticket-mailbox-dialog.component.html',
})
export class TicketMailboxDialogComponent {
  private readonly api = inject(TicketsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  /** The Bereich of the Postfach. */
  readonly area = input<TicketArea | null>(null);
  /** The stored Postfach. `null` creates one. */
  readonly mailbox = input<TicketMailbox | null>(null);
  readonly allowedHosts = input<readonly string[]>([]);

  readonly closed = output<void>();
  readonly saved = output<TicketMailbox>();
  readonly deleted = output<TicketArea>();

  protected readonly sides = SIDES;
  protected readonly draft = signal<MailboxDraft>(draftOf(null));
  private readonly start = signal<MailboxDraft>(draftOf(null));
  /** The person pressed "Speichern" once, so the missing fields show. */
  private readonly tried = signal(false);
  /** The hosts that the server refused at the last save. */
  private readonly refused = signal<readonly TextField[]>([]);
  protected readonly saving = signal(false);
  protected readonly testing = signal(false);
  protected readonly confirmDelete = signal(false);
  private readonly test = signal<TicketMailboxTest | null>(null);

  protected readonly dirty = computed(
    () => JSON.stringify(this.draft()) !== JSON.stringify(this.start()),
  );

  protected readonly passwordLabel = computed<TranslationKey>(() =>
    this.mailbox() ? 'admin.helpTickets.mailbox.passwordNew' : 'admin.helpTickets.mailbox.password',
  );

  protected readonly errors = computed<Readonly<Partial<Record<TextField, string>>>>(() => {
    const local = this.tried() ? draftErrors(this.draft(), this.mailbox() !== null) : {};
    const texts = Object.fromEntries(
      Object.entries(local).map(([field, key]) => [field, this.i18n.translate(key)]),
    );
    const hosts = this.allowedHosts().join(', ');
    const refused = Object.fromEntries(
      this.refused().map((field) => [
        field,
        this.i18n.translate('admin.helpTickets.mailbox.hostNotAllowed', { hosts }),
      ]),
    );
    return { ...refused, ...texts };
  });

  private cause(code: string | null | undefined): string {
    return this.i18n.translate(CAUSES[code ?? ''] ?? 'admin.helpTickets.mailbox.cause.unknown');
  }

  /** The error of the fetch after eight failed runs, as a text. */
  protected readonly fetchError = computed(() => {
    const code = this.mailbox()?.error;
    return code ? this.cause(code) : '';
  });

  protected readonly testLines = computed(() => {
    const result = this.test();
    if (!result) return [];
    const line = (ok: boolean, okKey: TranslationKey, failKey: TranslationKey, code?: string | null) => ({
      ok,
      text: ok
        ? this.i18n.translate(okKey)
        : this.i18n.translate(failKey, { cause: this.cause(code) }),
    });
    return [
      line(
        result.imap.ok,
        'admin.helpTickets.mailbox.testImapOk',
        'admin.helpTickets.mailbox.testImapFailed',
        result.imap.error,
      ),
      line(
        result.smtp.ok,
        'admin.helpTickets.mailbox.testSmtpOk',
        'admin.helpTickets.mailbox.testSmtpFailed',
        result.smtp.error,
      ),
    ];
  });

  protected readonly actions = computed<Action[]>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const stored: Action[] = this.mailbox()
      ? [
          { key: 'delete', label: t('admin.helpTickets.mailbox.delete'), kind: 'danger' },
          {
            key: 'test',
            label: t('admin.helpTickets.mailbox.test'),
            busy: this.testing(),
            disabled: this.dirty() || this.saving(),
          },
        ]
      : [];
    return [
      ...stored,
      { key: 'cancel', label: t('action.cancel') },
      { key: 'save', label: t('action.save'), kind: 'main', busy: this.saving() },
    ];
  });

  constructor() {
    effect(() => {
      if (!this.open()) return;
      const first = draftOf(this.mailbox());
      untracked(() => {
        this.draft.set(first);
        this.start.set(first);
        this.tried.set(false);
        this.refused.set([]);
        this.saving.set(false);
        this.testing.set(false);
        this.confirmDelete.set(false);
        this.test.set(null);
      });
    });
  }

  protected patch(part: Partial<MailboxDraft>): void {
    this.draft.update((d) => ({ ...d, ...part }));
    this.refused.set([]);
    this.test.set(null);
  }

  protected patchField(field: TextField, value: unknown): void {
    this.patch({ [field]: value === null || value === undefined ? '' : String(value) });
  }

  protected onAction(key: string): void {
    if (key === 'delete') this.confirmDelete.set(true);
    else if (key === 'test') this.runTest();
    else if (key === 'cancel') this.closed.emit();
    else this.save();
  }

  protected save(): void {
    const area = this.area();
    if (!area || this.saving()) return;
    this.tried.set(true);
    if (Object.keys(draftErrors(this.draft(), this.mailbox() !== null)).length) return;
    const body = mailboxBody(this.draft());
    const req = this.mailbox()
      ? this.api.updateMailbox(area.id, body)
      : this.api.createMailbox(area.id, body as TicketMailboxInput);
    this.saving.set(true);
    req.subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.saved.emit(saved);
      },
      error: (err: {
        error?: { code?: string; errors?: readonly { field?: string }[] } | null;
      }) => {
        this.saving.set(false);
        const code = err.error?.code ?? '';
        if (code === 'mail_host_not_allowed') {
          const fields = (err.error?.errors ?? []).map((e) => e.field);
          this.refused.set(
            (['imapHost', 'smtpHost'] as const).filter((field) => fields.includes(field)),
          );
          return;
        }
        this.toast.show(
          this.i18n.translate(
            code === 'ticket_mailbox_exists'
              ? 'admin.helpTickets.mailbox.error.exists'
              : 'admin.helpTickets.mailbox.error.save',
          ),
          'error',
        );
      },
    });
  }

  private runTest(): void {
    const area = this.area();
    if (!area || this.testing() || this.dirty()) return;
    this.testing.set(true);
    this.test.set(null);
    this.api.testMailbox(area.id).subscribe({
      next: (result) => {
        this.testing.set(false);
        this.test.set(result);
      },
      error: () => {
        this.testing.set(false);
        this.toast.show(this.i18n.translate('admin.helpTickets.mailbox.error.test'), 'error');
      },
    });
  }

  protected doDelete(): void {
    const area = this.area();
    this.confirmDelete.set(false);
    if (!area || this.saving()) return;
    this.saving.set(true);
    this.api.deleteMailbox(area.id).subscribe({
      next: () => {
        this.saving.set(false);
        this.deleted.emit(area);
      },
      error: () => {
        this.saving.set(false);
        this.toast.show(this.i18n.translate('admin.helpTickets.mailbox.error.delete'), 'error');
      },
    });
  }
}
